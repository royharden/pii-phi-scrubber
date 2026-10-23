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
from .filesystem import CustodyFilesystem, checked_path, strict_json


def write_bundle(bundle: CorpusBundle, destination: Path, *, private_root: Path | None = None,
                 filesystem: CustodyFilesystem | None = None) -> None:
    """Create a NEW directory; manifest written last is the completion marker.

    Caller provisions OS custody permissions. This function is not an ACL sandbox.
    A failed partial write is retained for custody investigation, never overwritten.
    """
    verify_bundle(bundle)
    if bundle.manifest.scope == 'custodian_sealed':
        if private_root is None or filesystem is None:
            raise ValueError('claimed_private_custody_filesystem_required')
        destination = filesystem.require_path('private', destination, must_exist=False)
        root = checked_path(private_root)
        if root != filesystem.roots()['private']:
            raise ValueError('private_root_policy_mismatch')
        if not root.is_dir() or destination == root or not destination.is_relative_to(root):
            raise ValueError('destination_outside_private_custody')
    else:
        destination = destination.resolve()
    destination.mkdir(parents=False, exist_ok=False)
    channels = (
        ('records.json', bundle.records), ('gold.json', bundle.gold),
        ('provenance.json', bundle.provenance), ('assignments.json', bundle.assignments),
        ('audit.json', bundle.audit), ('manifest.json', bundle.manifest),
    )
    for filename, value in channels:
        path = destination / filename
        if filesystem is not None:
            path = filesystem.require_path('private', path, must_exist=False)
        with path.open('xb') as stream:
            stream.write(canonical_bytes(value))


def _read(path: Path, limit: int = 16000000) -> bytes:
    with checked_path(path).open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('custody_channel_too_large')
    strict_json(data)
    return data


def read_bundle(directory: Path, *, filesystem: CustodyFilesystem | None = None) -> CorpusBundle:
    """Custodian/evaluator ONLY. Detector processes must not be given this directory."""
    directory = checked_path(directory)
    manifest = CorpusManifest.model_validate_json(_read(directory / 'manifest.json'))
    if manifest.scope == 'custodian_sealed':
        if filesystem is None:
            raise ValueError('claimed_private_custody_filesystem_required')
        directory = filesystem.require_path('private', directory)

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
