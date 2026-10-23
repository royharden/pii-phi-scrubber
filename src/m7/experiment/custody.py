"""D4 bundle to two separate evaluator inputs; no sibling data in inference."""
from __future__ import annotations

from typing import TYPE_CHECKING

from m7.contracts import LogRecord

from .models import CustodyGold, LockedEdition, check_channels

if TYPE_CHECKING:
    from m7.data.models import CorpusBundle


def channels_from_bundle(edition: LockedEdition, bundle: CorpusBundle
                         ) -> tuple[tuple[LogRecord, ...], tuple[CustodyGold, ...]]:
    # Lazy import prevents corpus generation or optional producers being loaded
    # by the adapter-only execution process.
    from m7.data.corpus import inference_records, verify_bundle
    from m7.data.provenance import commitment

    verify_bundle(bundle)
    if (bundle.manifest.scope != 'custodian_sealed'
            or bundle.manifest.edition_id != edition.edition_id
            or commitment(bundle.manifest) != edition.corpus_manifest_sha256):
        raise ValueError('sealed_corpus_manifest_mismatch')
    selected = {row.record_id: row for row in bundle.provenance if row.split == 'test'}
    records = inference_records(bundle, split='test')
    gold = tuple(CustodyGold(record_id=row.record_id, content_sha256=row.content_sha256,
                            spans=row.spans, block_id=selected[row.record_id].block_id,
                            slice_name=selected[row.record_id].difficulty)
                 for row in bundle.gold if row.record_id in selected)
    check_channels(edition, records, gold)
    # Mechanical counts are useful checks; they do not issue an audit verdict.
    if len({row.block_id for row in gold}) < 20:
        raise ValueError('insufficient_test_blocks')
    return records, gold
