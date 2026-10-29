"""Explicit training export and released evaluator channel bridges; no raw logging."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, TYPE_CHECKING

from m7.contracts import Boundary, Digest, LogRecord

from .corpus import inference_records, verify_bundle
from .lifecycle import CustodyLifecycle, utc
from .lifecycle_models import TrainingExportAuthorization
from .models import CorpusBundle, GoldRow
from .provenance import canonical_bytes, commitment

if TYPE_CHECKING:
    from m7.experiment import LockedEdition


class TrainingChannels(Boundary):
    schema_version: Literal['TrainingChannels/v1'] = 'TrainingChannels/v1'
    split: Literal['train', 'dev']
    corpus_manifest_sha256: Digest
    records: tuple[LogRecord, ...]
    gold: tuple[GoldRow, ...]


def _new_channel_files(destination: Path, payloads: tuple) -> None:
    destination.mkdir(parents=False, exist_ok=False)
    for filename, payload in payloads:
        with (destination / filename).open('xb') as stream:
            stream.write(canonical_bytes(payload))


def training_channels(bundle: CorpusBundle, *, split: Literal['train', 'dev'],
                      authorization: TrainingExportAuthorization,
                      verify_receipt: Callable[[str, str], bool],
                      lifecycle: CustodyLifecycle | None = None,
                      now: datetime | None = None) -> TrainingChannels:
    """Filter custodian-side BEFORE exporting. No test-source/gold/provenance path.

    D5 prepare_training_dataset(channels.records, channels.gold, split=channels.split)
    consumes this exactly; no D5 module is imported or executed here.
    """
    verify_bundle(bundle)
    if split not in ('train', 'dev'):
        raise ValueError('training_split_required')
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or not utc(authorization.issued_at) <= instant < utc(authorization.expires_at):
        raise ValueError('training_export_authorization_expired')
    manifest_digest = commitment(bundle.manifest)
    if (authorization.edition_id != bundle.manifest.edition_id or authorization.split != split
            or authorization.corpus_manifest_sha256 != manifest_digest):
        raise ValueError('training_export_binding_mismatch')
    if verify_receipt('training_export_authorization', commitment(authorization)) is not True:
        raise ValueError('training_export_not_authenticated_or_revoked')
    if bundle.manifest.scope == 'custodian_sealed':
        if lifecycle is None:
            raise ValueError('sealed_training_export_requires_lifecycle')
        lifecycle.require_training_export(bundle)
    wanted = 'train' if split == 'train' else 'development'
    records = tuple(record.model_copy(update={'split_id': split})
                    for record in inference_records(bundle, split=wanted))
    ids = {record.record_id for record in records}
    gold = tuple(row for row in bundle.gold if row.record_id in ids)
    if not records or len(gold) != len(records):
        raise ValueError('empty_or_incomplete_training_export')
    return TrainingChannels(split=split, corpus_manifest_sha256=manifest_digest,
                            records=records, gold=gold)


def write_training_channels(channels: TrainingChannels, destination: Path) -> dict:
    """New training directory only; no custody bundle/provenance gets serialized."""
    channels = TrainingChannels.model_validate_json(channels.model_dump_json())
    ids = {r.record_id: r.content_sha256 for r in channels.records}
    if (len(ids) != len(channels.records) or not ids
            or len(channels.gold) != len(channels.records)
            or {g.record_id: g.content_sha256 for g in channels.gold} != ids
            or any(r.split_id != channels.split for r in channels.records)):
        raise ValueError('invalid_training_channel_join')
    records = {r.record_id: r for r in channels.records}
    if any(span.end > len(records[row.record_id].log.message) for row in channels.gold for span in row.spans):
        raise ValueError('training_gold_bounds_invalid')
    receipt = {'schema_version': 'TrainingChannelExport/v1', 'split': channels.split,
               'corpus_manifest_sha256': channels.corpus_manifest_sha256,
               'record_count': len(channels.records), 'records_sha256': commitment(channels.records),
               'gold_sha256': commitment(channels.gold)}
    _new_channel_files(destination, (('records.json', channels.records), ('gold.json', channels.gold), ('manifest.json', receipt)))
    return receipt


def released_channels(lifecycle: CustodyLifecycle, edition: LockedEdition, bundle: CorpusBundle,
                      *, authority: Callable) -> tuple:
    """Require authenticated release before returning D7's two custody channels.

    Adapter processes receive only return value[0], never value[1]/bundle/lifecycle.
    Caller must still enforce process/ACL isolation. No model or experiment executes.
    """
    from m7.experiment.custody import channels_from_bundle

    # No execution open is consumed here; execute_edition owns that transition.
    authority(edition, False)
    lifecycle.require_released(edition)
    return channels_from_bundle(edition, bundle)


def write_released_channels(lifecycle: CustodyLifecycle, edition: LockedEdition, bundle: CorpusBundle,
                            *, authority: Callable, inference_root: Path, evaluator_root: Path,
                            inference_directory: Path, evaluator_directory: Path) -> dict:
    """Materialize separate private worker/evaluator channels after release checks.

    Roots must already exist with operator-provisioned permissions, be disjoint,
    and contain new child directories. This cannot install ACLs or recall bytes
    already delivered when a later revocation arrives.
    """
    worker_root, gold_root = inference_root.resolve(strict=True), evaluator_root.resolve(strict=True)
    worker_dir, gold_dir = inference_directory.resolve(), evaluator_directory.resolve()
    if (not worker_root.is_dir() or not gold_root.is_dir()
            or worker_root == gold_root or worker_root.is_relative_to(gold_root) or gold_root.is_relative_to(worker_root)
            or worker_dir == worker_root or gold_dir == gold_root
            or not worker_dir.is_relative_to(worker_root) or not gold_dir.is_relative_to(gold_root)
            or worker_dir.exists() or gold_dir.exists()):
        raise ValueError('separate_new_custody_destinations_required')
    records, gold = released_channels(lifecycle, edition, bundle, authority=authority)
    base = {'schema_version': 'ReleasedChannel/v1', 'edition_id': edition.edition_id,
            'run_id': edition.run_id, 'custody_release_sha256': edition.custody_release_sha256,
            'record_count': len(records)}
    worker_manifest = {**base, 'channel': 'inference', 'records_sha256': commitment(records)}
    evaluator_manifest = {**base, 'channel': 'evaluator_gold', 'gold_sha256': commitment(gold)}
    _new_channel_files(worker_dir, (('records.json', records), ('manifest.json', worker_manifest)))
    _new_channel_files(gold_dir, (('gold.json', gold), ('manifest.json', evaluator_manifest)))
    return {'schema_version': 'ReleasedChannelExport/v1', 'edition_id': edition.edition_id,
            'record_count': len(records), 'inference_manifest_sha256': commitment(worker_manifest),
            'gold_manifest_sha256': commitment(evaluator_manifest)}
