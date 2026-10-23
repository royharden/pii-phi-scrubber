"""Two-phase Windows qualification: prepared shared P, then exact live process L.

No native API, filesystem observation or process query runs at import/construction.
Native activation is explicit; no credentials, launches, termination or OS mutation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
from typing import Callable

from .access import _time
from .filesystem import CustodyFilesystem, checked_path
from .native_windows_models import (
    NativeObservation, NativeQualificationResult, WindowsControlVerifier,
    WindowsPolicyEvidence, WindowsProcessApproval,
)
from .provenance import commitment

DENY_BITS = (0x1, 0x2, 0x4, 0x10, 0x100, 0x10000, 0x40000, 0x80000)
MUTATE_BITS = (0x2, 0x4, 0x10, 0x40, 0x100, 0x10000, 0x40000, 0x80000)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _current(issued: str, expires: str) -> None:
    _require(_time(issued) <= datetime.now(timezone.utc) < _time(expires), 'native_authorization_expired')


def _pin(path: Path, expected: str) -> None:
    path = checked_path(path)
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    _require(actual == expected, 'native_image_or_entrypoint_changed')


def _objects(roots: dict[str, Path], *, max_objects: int = 10000):
    """Inspect EVERY descendant, not just parent ACLs; never follow reparse points."""
    seen = 0
    for role, root in sorted(roots.items()):
        pending = [checked_path(root)]
        while pending:
            path = checked_path(pending.pop())
            seen += 1
            _require(seen <= max_objects, 'native_inventory_bound_exceeded')
            _require(path == root or path.is_relative_to(root), 'native_root_escape')
            yield role, root, path
            if path.is_dir():
                pending.extend(sorted(path.iterdir(), reverse=True))


def _snapshot(api, roots, token=None):
    rows, denied, readonly = [], 0, 0
    for role, root, path in _objects(roots):
        with api.descriptor(path) as (descriptor, raw):
            if token is not None:
                if role in ('private', 'evaluator', 'training'):
                    _require(not any(api.allows(descriptor, token, bit) for bit in DENY_BITS), 'worker_sensitive_access_granted')
                    denied += 1
                elif role == 'scratch':
                    _require(api.allows(descriptor, token, 0xC0000000), 'worker_scratch_access_unavailable')
                    _require(not any(api.allows(descriptor, token, bit) for bit in (0x40000, 0x80000)), 'worker_scratch_control_escape')
                else:
                    _require(api.allows(descriptor, token, 0x80000000), 'worker_read_access_unavailable')
                    _require(not any(api.allows(descriptor, token, bit) for bit in MUTATE_BITS), 'worker_approved_input_writable')
                    readonly += 1
            rows.append((role, path.is_dir(), hashlib.sha256(raw).hexdigest()))
    # Semantic descriptor closure, not value/path hashes. New journal files with
    # the same protected ACL do not require a different profile; every actual
    # descendant is STILL checked above on every qualification.
    return commitment(sorted(set(rows))), len(rows), denied, readonly


class WindowsIsolationVerifier:
    """Prelaunch shared-profile qualification, never a claim about a future PID.

    Prepared native controls are verified by mandatory trusted host code. This
    adapter additionally reads the current root descriptor inventory and pins P.
    It neither requires a running worker nor infers one from a prepared campaign.
    """
    def __init__(self, filesystem: CustodyFilesystem, profile, evidence: WindowsPolicyEvidence, *,
                 verify_receipt: Callable[[str, str], bool], control_verifier: WindowsControlVerifier):
        self.filesystem, self.profile, self.evidence = filesystem, profile, evidence
        self.verify_receipt, self.control_verifier = verify_receipt, control_verifier

    def verify(self, capability, request) -> bool:
        try:
            from m7.providers.worker_profile import worker_profile_digest
            from .native_windows_api import Win32ReadOnly
            e = self.evidence
            _current(e.issued_at, e.expires_at)
            _require(e.capability_sha256 == commitment(capability) and e.request_sha256 == commitment(request)
                and e.profile_sha256 == worker_profile_digest(self.profile) == request.worker_policy_sha256
                and e.prepared_controls_sha256 == capability.enforcement_evidence_sha256
                and e.filesystem_policy_sha256 == self.filesystem.sha256 == request.filesystem_policy_sha256,
                'native_policy_binding_mismatch')
            for kind, digest in (('windows_policy_qualification', commitment(e)),
                                 ('worker_profile_approval', e.profile_sha256),
                                 ('windows_prepared_controls', e.prepared_controls_sha256)):
                _require(self.verify_receipt(kind, digest) is True, 'native_policy_not_authenticated')
            _require(self.control_verifier is not None and
                self.control_verifier.verify_policy(e, capability, request, self.profile) is True,
                'native_prepared_controls_unverified')
            roots = self.filesystem.roots()
            for role, root in roots.items():
                self.filesystem.require_path(role, root / '.custody-root-policy.json')
            digest, _, _, _ = _snapshot(Win32ReadOnly(), roots)
            _require(digest == e.descriptor_tree_sha256, 'native_policy_descriptor_changed')
            return True
        except Exception:
            return False


class WindowsWorkerProcessVerifier:
    """Postlaunch exact-PID/start/image/token/P/L qualification before messages.

    Separate native control verification is mandatory for exact job limits,
    inherited handles, environment, network and descendants. IsProcessInJob(any)
    and handle count are consistency facts, not proof of those controls.
    """
    def __init__(self, filesystem: CustodyFilesystem, profile, approvals: tuple[WindowsProcessApproval, ...], *,
                 verify_receipt: Callable[[str, str], bool], control_verifier: WindowsControlVerifier):
        self.filesystem, self.profile, self.approvals = filesystem, profile, approvals
        self.verify_receipt, self.control_verifier = verify_receipt, control_verifier
        self.last_result = NativeQualificationResult(status='validation_only', reason_codes=('native_activation_not_requested',))

    def verify(self, pid: int, start_identity: str, spec, verified_isolation, policy) -> bool:
        result = self.qualify(pid, start_identity, spec, verified_isolation, policy, allow_native_inspection=True)
        return result.status == 'qualified_snapshot'

    def qualify(self, pid: int, start_identity: str, spec, verified_isolation, policy, *,
                allow_native_inspection: bool = False) -> NativeQualificationResult:
        if not allow_native_inspection:
            return NativeQualificationResult(status='validation_only', reason_codes=(
                'explicit_native_activation_required', 'authenticated_exact_process_approval_required',
                'preprovisioned_native_controls_required'))
        if sys.platform != 'win32':
            return NativeQualificationResult(status='unqualified', reason_codes=('unsupported_native_platform',))
        entered = False
        try:
            from m7.providers.worker_profile import validate_worker_membership
            from m7.providers.worker_transport import launch_spec
            from .native_windows_api import Win32ReadOnly
            membership = validate_worker_membership(self.profile, policy)
            _require(type(pid) is int and 0 < pid <= 4294967295 and type(start_identity) is str,
                     'native_process_identity_invalid')
            matches = [a for a in self.approvals if a.pid == pid and a.start_identity == start_identity]
            _require(len(matches) == 1, 'native_exact_process_approval_required')
            a = matches[0]
            _current(a.issued_at, a.expires_at)
            _require(spec == launch_spec(policy) and a.profile_sha256 == membership.profile_sha256
                and a.launch_sha256 == membership.launch_sha256 and a.bootstrap_sha256 == policy.bootstrap_sha256
                and a.filesystem_policy_sha256 == self.filesystem.sha256 == policy.filesystem_policy_sha256
                and a.capability_sha256 == verified_isolation.capability_sha256
                and membership.profile_sha256 == verified_isolation.worker_policy_sha256
                and a.image_sha256 == policy.executable_sha256 and a.entrypoint_sha256 == policy.entrypoint_sha256,
                'native_process_policy_binding_mismatch')
            for kind, digest in (('windows_process_qualification', commitment(a)),
                                 ('windows_process_controls', a.process_controls_sha256),
                                 ('worker_profile_approval', membership.profile_sha256),
                                 ('worker_launch_approval', membership.launch_sha256)):
                _require(self.verify_receipt(kind, digest) is True, 'native_process_not_authenticated')
            roots = self.filesystem.roots()
            for role, root in roots.items():
                self.filesystem.require_path(role, root / '.custody-root-policy.json')
            scratch = checked_path(policy.working_directory)
            extra = [checked_path(policy.executable), checked_path(policy.entrypoint)]
            _pin(extra[0], a.image_sha256)
            _pin(extra[1], a.entrypoint_sha256)
            if policy.artifact_root is not None:
                roots['artifact'] = checked_path(policy.artifact_root)
            _require(scratch.is_dir() and all(not (scratch == r or scratch.is_relative_to(r) or r.is_relative_to(scratch))
                for r in roots.values()) and all(not p.is_relative_to(scratch) for p in extra), 'native_scratch_root_overlap')
            roots['scratch'] = scratch
            api = Win32ReadOnly()
            entered = True
            with api.process(pid) as process, api.token(process) as token:
                before = api.process_identity(process)
                _require(before[0] == start_identity and checked_path(before[1]) == extra[0]
                    and before[2] == a.expected_handle_count, 'native_process_identity_changed')
                summary = api.token_summary(token)
                _require(summary['sid'] == a.worker_sid and summary['sid'] != a.custodian_sid
                    and summary['sid'] not in ('S-1-5-18', 'S-1-5-19', 'S-1-5-20')
                    and summary['primary'] and not summary['elevated'] and not summary['ui_access']
                    and not summary['appcontainer'] and summary['restricted'] and summary['restricted_sids']
                    and summary['integrity_rid'] <= 4096 and summary['mandatory_policy'] & 1
                    and not summary['mandatory_policy'] & ~3
                    and summary['token_id'] == a.token_id and summary['modified_id'] == a.token_modified_id,
                    'native_token_identity_or_restriction_mismatch')
                _require(set(summary['privileges']) <= {'SeChangeNotifyPrivilege'} and
                    not any(sid == 'S-1-5-32-544' and attributes & 0xC and not attributes & 0x10
                            for sid, attributes in summary['groups']), 'native_broad_privilege_or_group')
                _require(api.job_member(process), 'native_job_membership_missing')
                with api.access_token(token) as client:
                    digest, count, denied, readonly = _snapshot(api, roots, client)
                    # Parent DELETE_CHILD/ACL control can otherwise bypass a child's DACL.
                    for role in ('private', 'evaluator', 'training'):
                        for parent in roots[role].parents:
                            with api.descriptor(checked_path(parent)) as (sd, _):
                                _require(not any(api.allows(sd, client, bit) for bit in (0x40, 0x40000, 0x80000)),
                                         'native_sensitive_ancestor_mutable')
                    for path in extra:
                        with api.descriptor(path) as (sd, _):
                            _require(api.allows(sd, client, 0xA0000000 if path == extra[0] else 0x80000000)
                                and not any(api.allows(sd, client, bit) for bit in MUTATE_BITS), 'native_executable_access_mismatch')
                _require(digest == a.descriptor_tree_sha256, 'native_process_descriptor_changed')
                with api.token(process) as current:
                    after_token = api.token_summary(current)
                _require(after_token == summary and api.process_identity(process) == before,
                         'native_process_or_token_changed_during_qualification')
                observation = NativeObservation(pid=pid, start_identity=start_identity,
                    profile_sha256=membership.profile_sha256, launch_sha256=membership.launch_sha256,
                    image_sha256=a.image_sha256, descriptor_tree_sha256=digest, token_id=a.token_id,
                    token_modified_id=a.token_modified_id, checked_objects=count, denied_objects=denied,
                    read_only_objects=readonly, handle_count=before[2], in_job=True)
                _require(self.control_verifier is not None and
                    self.control_verifier.verify_process(a, observation, spec, policy) is True,
                    'native_exact_controls_unverified')
            result = NativeQualificationResult(status='qualified_snapshot', reason_codes=(), observation=observation,
                                               native_inspection_performed=True)
        except Exception:
            # Never stringify exceptions or return token/SID/path/descriptor bodies.
            result = NativeQualificationResult(status='unqualified', reason_codes=('native_qualification_unavailable',),
                                               native_inspection_performed=entered)
        self.last_result = result
        return result
