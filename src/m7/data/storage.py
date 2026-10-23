"""Separate custody channels on disk; no automatic publication or detector access."""
from __future__ import annotations

import json
from pathlib import Path

from .models import (
    BlockAssignment, CorpusBundle, CorpusManifest, GoldRow, RecordProvenance, SplitAudit,
)
from .corpus import verify_bundle
from .provenance import canonical_bytes
from m7.contracts import LogRecord


def write_bundle(bundle: CorpusBundle, destination: Path, *, private_root: Path | None = None) -> None:
    """Create a NEW directory; manifest written last is the completion marker.

    Caller provisions OS custody permissions. This function is not an ACL sandbox.
    A failed partial write is retained for custody investigation, never overwritten.
    """
    verify_bundle(bundle)
    destination = destination.resolve()
    if bundle.manifest.scope == 'custodian_sealed':
        if private_root is None:
            raise ValueError('private_custody_root_required')
        root = private_root.resolve(strict=True)
        if not root.is_dir() or destination == root or not destination.is_relative_to(root):
            raise ValueError('destination_outside_private_custody')
    destination.mkdir(parents=False, exist_ok=False)
    channels = (
        ('records.json', bundle.records), ('gold.json', bundle.gold),
        ('provenance.json', bundle.provenance), ('assignments.json', bundle.assignments),
        ('audit.json', bundle.audit), ('manifest.json', bundle.manifest),
    )
    for filename, value in channels:
        with (destination / filename).open('xb') as stream:
            stream.write(canonical_bytes(value))


def _read(path: Path, limit: int = 16000000) -> bytes:
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('custody_channel_too_large')
    return data


def read_bundle(directory: Path) -> CorpusBundle:
    """Custodian/evaluator ONLY. Detector processes must not be given this directory."""
    directory = directory.resolve(strict=True)
    manifest = CorpusManifest.model_validate_json(_read(directory / 'manifest.json'))

    def rows(name: str, model):
        data = json.loads(_read(directory / name))
        if not isinstance(data, list) or len(data) > 10000:
            raise ValueError('invalid_custody_channel')
        # JSON validation accepts JSON arrays for strict immutable tuple fields.
        return tuple(model.model_validate_json(json.dumps(row, allow_nan=False)) for row in data)

    bundle = CorpusBundle(manifest=manifest,
        records=rows('records.json', LogRecord), gold=rows('gold.json', GoldRow),
        provenance=rows('provenance.json', RecordProvenance),
        assignments=rows('assignments.json', BlockAssignment),
        audit=SplitAudit.model_validate_json(_read(directory / 'audit.json')))
    verify_bundle(bundle)
    return bundle
