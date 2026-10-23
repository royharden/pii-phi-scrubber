"""Custody path/immutable-file policy, distinct from actual OS enforcement."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
from typing import Callable, Literal

from m7.contracts import Boundary, Digest, Identifier, LogRecord

from .access import _time
from .provenance import canonical_bytes, commitment

Role = Literal['private', 'inference', 'evaluator', 'training']


def checked_path(raw: str | Path, *, must_exist: bool = True) -> Path:
    """Reject traversal AND any existing symlink/junction/reparse ancestor.

    No resolve-then-trust: inspect lexical ancestors first, including Windows
    reparse points. Native enforcement is still required against TOCTOU races.
    """
    text = str(raw)
    if text.startswith(('\\\\', '//')):
        raise ValueError('local_custody_path_required')
    if '\x00' in text or any(part in ('.', '..') for part in re.split(r'[\\/]', text)):
        raise ValueError('custody_path_traversal')
    path = Path(text)
    if not path.is_absolute():
        raise ValueError('absolute_custody_path_required')
    for candidate in (*reversed(path.parents), path):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            if must_exist:
                raise ValueError('custody_path_missing') from None
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('custody_link_or_reparse_point')
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError('custody_hardlinked_file')
    resolved = path.resolve(strict=must_exist)
    if resolved != path:
        raise ValueError('custody_path_alias')
    return resolved


def strict_json(raw: bytes) -> object:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_custody_json_key')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('nonfinite_custody_json')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


class CustodyPathPolicy(Boundary):
    schema_version: Literal['CustodyPathPolicy/v1'] = 'CustodyPathPolicy/v1'
    policy_id: Identifier
    custodian_id: Identifier
    private_root: str
    inference_root: str
    evaluator_root: str
    training_root: str


class FilesystemPolicyApproval(Boundary):
    schema_version: Literal['FilesystemPolicyApproval/v1'] = 'FilesystemPolicyApproval/v1'
    authorization_id: Identifier
    policy_sha256: Digest
    custodian_id: Identifier
    issued_at: str
    expires_at: str
    action: Literal['claim_exclusive_custody_roots'] = 'claim_exclusive_custody_roots'


class RootClaim(Boundary):
    schema_version: Literal['CustodyRootClaim/v1'] = 'CustodyRootClaim/v1'
    policy_sha256: Digest
    role: Role
    custodian_id: Identifier
    authorization_sha256: Digest


class ExportCommitment(Boundary):
    schema_version: Literal['CustodyExportCommitment/v1'] = 'CustodyExportCommitment/v1'
    export_id: Identifier
    policy_sha256: Digest
    role: Literal['inference', 'evaluator', 'training']
    directory_name: Identifier
    files_sha256: dict[str, Digest]


class _InferenceManifest(Boundary):
    schema_version: Literal['ReleasedChannel/v1']
    edition_id: Identifier
    run_id: Identifier
    custody_release_sha256: Digest
    record_count: int
    channel: Literal['inference']
    records_sha256: Digest


class _EvaluatorManifest(Boundary):
    schema_version: Literal['ReleasedChannel/v1']
    edition_id: Identifier
    run_id: Identifier
    custody_release_sha256: Digest
    record_count: int
    channel: Literal['evaluator_gold']
    gold_sha256: Digest


class _TrainingManifest(Boundary):
    schema_version: Literal['TrainingChannelExport/v1']
    split: Literal['train', 'dev']
    corpus_manifest_sha256: Digest
    record_count: int
    records_sha256: Digest
    gold_sha256: Digest


class CustodyFilesystem:
    """Authenticated exclusive root claims and guarded local IO.

    A marker authorizes this API's use; it is NOT evidence that OS access is denied.
    That evidence is separately required through IsolationGuard for held-out release.
    """
    def __init__(self, policy: CustodyPathPolicy, approval: FilesystemPolicyApproval, *,
                 verify_receipt: Callable[[str, str], bool]):
        self.policy, self.approval, self.verify_receipt = policy, approval, verify_receipt

    @property
    def sha256(self) -> str:
        return commitment(self.policy)

    def roots(self) -> dict[str, Path]:
        roots = {role: checked_path(getattr(self.policy, role + '_root'))
                 for role in ('private', 'inference', 'evaluator', 'training')}
        if any(not root.is_dir() for root in roots.values()):
            raise ValueError('custody_root_not_directory')
        values = list(roots.values())
        for index, root in enumerate(values):
            if any(root == other or root.is_relative_to(other) or other.is_relative_to(root)
                   for other in values[index + 1:]):
                raise ValueError('custody_roots_must_be_disjoint')
        return roots

    def _authority(self) -> None:
        now = datetime.now(timezone.utc)
        if (self.approval.policy_sha256 != self.sha256 or self.approval.custodian_id != self.policy.custodian_id
                or not _time(self.approval.issued_at) <= now < _time(self.approval.expires_at)
                or self.verify_receipt('custody_filesystem_policy', commitment(self.approval)) is not True):
            raise ValueError('filesystem_policy_not_authenticated_or_current')

    def claim_roots(self) -> None:
        """Future explicit claim of preprovisioned EMPTY roots, no permission changes."""
        self._authority()
        roots = self.roots()
        # Validate every root before any claim; incomplete writes remain visible.
        for role, root in roots.items():
            files = list(root.iterdir())
            if files and {p.name for p in files} != {'.custody-root-policy.json'}:
                raise ValueError('custody_root_not_empty_for_claim')
            if files:
                self._claim(role, root)
        for role, root in roots.items():
            marker = root / '.custody-root-policy.json'
            if not marker.exists():
                claim = RootClaim(policy_sha256=self.sha256, role=role, custodian_id=self.policy.custodian_id,
                                  authorization_sha256=commitment(self.approval))
                with marker.open('xb') as stream:
                    stream.write(canonical_bytes(claim))

    def _claim(self, role: str, root: Path) -> None:
        path = checked_path(root / '.custody-root-policy.json')
        if path.stat().st_size > 10000:
            raise ValueError('invalid_root_claim')
        claim = RootClaim.model_validate_json(canonical_bytes(strict_json(path.read_bytes())))
        if (claim.policy_sha256 != self.sha256 or claim.role != role or claim.custodian_id != self.policy.custodian_id
                or (claim.authorization_sha256 != commitment(self.approval)
                    and self.verify_receipt('custody_root_claim_origin', claim.authorization_sha256) is not True)):
            raise ValueError('root_claim_binding_mismatch')

    def require_path(self, role: Role, path: Path, *, must_exist: bool = True) -> Path:
        self._authority()
        roots = self.roots()
        for key, root in roots.items():
            self._claim(key, root)
        result = checked_path(path, must_exist=must_exist)
        if result == roots[role] or not result.is_relative_to(roots[role]):
            raise ValueError('path_outside_custody_role')
        return result

    def read_private(self, path: Path, *, limit: int = 16000000) -> bytes:
        target = self.require_path('private', path)
        with target.open('rb') as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('private_channel_too_large')
        return raw

    def write_export(self, role: Literal['inference', 'evaluator', 'training'], directory: Path,
                     payloads: tuple, *, export_id: str) -> ExportCommitment:
        target = self.require_path(role, directory, must_exist=False)
        if target.exists():
            raise ValueError('immutable_export_already_exists')
        allowed = {'inference': {'records.json', 'manifest.json'},
                   'evaluator': {'gold.json', 'manifest.json'},
                   'training': {'records.json', 'gold.json', 'manifest.json'}}[role]
        if {name for name, _ in payloads} != allowed or len(payloads) != len(allowed):
            raise ValueError('invalid_export_channel_files')
        encoded = {name: canonical_bytes(value) for name, value in payloads}
        if any(len(raw) > 16000000 for raw in encoded.values()):
            raise ValueError('export_channel_too_large')
        manifest_type = {'inference': _InferenceManifest, 'evaluator': _EvaluatorManifest, 'training': _TrainingManifest}[role]
        manifest = manifest_type.model_validate_json(encoded['manifest.json'])
        if role in ('inference', 'training'):
            rows = strict_json(encoded['records.json'])
            if not isinstance(rows, list):
                raise ValueError('record_array_required')
            for row in rows:
                record = LogRecord.model_validate_json(canonical_bytes(row))
                if record.split_id not in (('inference',) if role == 'inference' else ('train', 'dev')):
                    raise ValueError('wrong_record_export_role')
            if manifest.record_count != len(rows) or manifest.records_sha256 != hashlib.sha256(encoded['records.json']).hexdigest():
                raise ValueError('record_export_manifest_mismatch')
        if role == 'evaluator':
            from m7.experiment.models import CustodyGold
            rows = strict_json(encoded['gold.json'])
            if not isinstance(rows, list):
                raise ValueError('gold_array_required')
            for row in rows:
                CustodyGold.model_validate_json(canonical_bytes(row))
            if manifest.record_count != len(rows):
                raise ValueError('gold_export_count_mismatch')
        if role == 'training':
            from .models import GoldRow
            gold = strict_json(encoded['gold.json'])
            if not isinstance(gold, list):
                raise ValueError('gold_array_required')
            for row in gold:
                GoldRow.model_validate_json(canonical_bytes(row))
        if role in ('evaluator', 'training') and manifest.gold_sha256 != hashlib.sha256(encoded['gold.json']).hexdigest():
            raise ValueError('gold_export_manifest_mismatch')
        receipt = ExportCommitment(export_id=export_id, policy_sha256=self.sha256, role=role,
            directory_name=target.name,
            files_sha256={name: hashlib.sha256(raw).hexdigest() for name, raw in encoded.items()})
        target.mkdir(exist_ok=False)
        for filename in sorted(encoded, key=lambda name: name == 'manifest.json'):
            path = self.require_path(role, target / filename, must_exist=False)
            with path.open('xb') as stream:
                stream.write(encoded[filename])
        marker = self.require_path(role, target / 'commitment.json', must_exist=False)
        with marker.open('xb') as stream:
            stream.write(canonical_bytes(receipt))
        return receipt

    def verify_export(self, role: Literal['inference', 'evaluator', 'training'], directory: Path,
                      expected_sha256: str) -> ExportCommitment:
        target = self.require_path(role, directory)
        marker = self.require_path(role, target / 'commitment.json')
        if marker.stat().st_size > 16000:
            raise ValueError('export_commitment_too_large')
        receipt = ExportCommitment.model_validate_json(canonical_bytes(strict_json(marker.read_bytes())))
        if (commitment(receipt) != expected_sha256 or receipt.policy_sha256 != self.sha256
                or receipt.role != role or receipt.directory_name != target.name
                or {p.name for p in target.iterdir()} != set(receipt.files_sha256) | {'commitment.json'}):
            raise ValueError('immutable_export_binding_mismatch')
        required = {'inference': {'records.json', 'manifest.json'},
                    'evaluator': {'gold.json', 'manifest.json'},
                    'training': {'records.json', 'gold.json', 'manifest.json'}}[role]
        if set(receipt.files_sha256) != required:
            raise ValueError('export_channel_file_set_mismatch')
        for name, digest in receipt.files_sha256.items():
            if name not in {'records.json', 'gold.json', 'manifest.json'}:
                raise ValueError('invalid_export_filename')
            path = self.require_path(role, target / name)
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != digest:
                raise ValueError('immutable_export_changed')
        return receipt
