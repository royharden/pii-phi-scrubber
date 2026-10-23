"""Train/dev-only handoff from the custodian, without a sealed-bundle reader."""
from __future__ import annotations

from collections.abc import Iterable

from m7.contracts import LogRecord


def prepare_training_dataset(records: Iterable[LogRecord], gold: Iterable[object], *, split: str) -> dict:
    """Accept already-filtered D4 channels; reject mixed splits/extra gold rows.

    Gold objects implement D4 GoldRow's record_id/content_sha256/spans fields.
    This is not a custody approval, file writer, corpus generator or test reader.
    """
    if split not in ("train", "dev"):
        raise ValueError("training_split_required")
    by_id = {}
    for row in gold:
        if row.record_id in by_id:
            raise ValueError("duplicate_training_gold")
        by_id[row.record_id] = row
    output, seen = [], set()
    for record in records:
        if record.split_id != split or record.record_id in seen:
            raise ValueError("mixed_training_split")
        seen.add(record.record_id)
        row = by_id.get(record.record_id)
        if row is None or row.content_sha256 != record.content_sha256:
            raise ValueError("training_gold_join_mismatch")
        output.append({"record": record.model_dump(mode="json"),
                       "gold": [{"start": s.start, "end": s.end, "label": s.label} for s in row.spans]})
    if seen != set(by_id) or not output:
        raise ValueError("training_gold_coverage_mismatch")
    return {"schema_version": "TrainingDataset/v1", "split": split, "records": output}
