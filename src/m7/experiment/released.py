"""Evaluator-only reader for D4's separately committed released channels."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from m7.contracts import LogRecord
from m7.data.filesystem import strict_json
from .models import CustodyGold, LockedEdition, canonical, check_channels

if TYPE_CHECKING:
    from m7.data.filesystem import CustodyFilesystem


def read_released_channels(edition: LockedEdition, *, filesystem: CustodyFilesystem,
                            inference_directory: Path, gold_directory: Path,
                            inference_export_sha256: str, gold_export_sha256: str,
                            verify_receipt: Callable[[str, str], bool]
                            ) -> tuple[tuple[LogRecord, ...], tuple[CustodyGold, ...]]:
    """Caller authenticates release/isolation BEFORE calling. Never pass paths on.

    Reuses D4's exact immutable-export verifier and strict JSON parser. Digests
    are externally authenticated custody export commitments, not guessed file hashes.
    No raw CorpusBundle, private family generator or training channel is opened.
    """
    for kind, digest in (('released_inference_export', inference_export_sha256),
                         ('released_gold_export', gold_export_sha256)):
        if verify_receipt(kind, digest) is not True:
            raise ValueError('released_export_receipt_not_authenticated')
    inference_receipt = filesystem.verify_export('inference', inference_directory, inference_export_sha256)
    gold_receipt = filesystem.verify_export('evaluator', gold_directory, gold_export_sha256)

    def read(role, directory, receipt, name):
        path = filesystem.require_path(role, directory / name)
        with path.open('rb') as handle:
            raw = handle.read(16_000_001)
        if len(raw) > 16_000_000 or hashlib.sha256(raw).hexdigest() != receipt.files_sha256[name]:
            raise ValueError('released_channel_changed_or_oversize')
        return raw, strict_json(raw)

    records_raw, rows = read('inference', inference_directory, inference_receipt, 'records.json')
    gold_raw, annotations = read('evaluator', gold_directory, gold_receipt, 'gold.json')
    if (not isinstance(rows, list) or not isinstance(annotations, list)
            or len(rows) != len(edition.population) or len(annotations) != len(rows)):
        raise ValueError('released_channel_population_mismatch')
    expected = {'schema_version': 'ReleasedChannel/v1', 'edition_id': edition.edition_id,
                'run_id': edition.run_id, 'custody_release_sha256': edition.custody_release_sha256,
                'record_count': len(rows)}
    for role, directory, receipt, channel, key, raw in (
        ('inference', inference_directory, inference_receipt, 'inference', 'records_sha256', records_raw),
        ('evaluator', gold_directory, gold_receipt, 'evaluator_gold', 'gold_sha256', gold_raw),
    ):
        _, manifest = read(role, directory, receipt, 'manifest.json')
        if manifest != {**expected, 'channel': channel, key: hashlib.sha256(raw).hexdigest()}:
            raise ValueError('released_manifest_binding_mismatch')
    records = tuple(LogRecord.model_validate_json(canonical(row)) for row in rows)
    gold = tuple(CustodyGold.model_validate_json(canonical(row)) for row in annotations)
    check_channels(edition, records, gold)
    if len({row.block_id for row in gold}) < 20:
        raise ValueError('insufficient_released_test_blocks')
    return records, gold


__all__ = ['read_released_channels']
