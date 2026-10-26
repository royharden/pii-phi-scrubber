"""Independent regression for outcome/availability counters sharing an 'answered' key."""

import pytest

from m7.experiment.executor import aggregate_edition
from m7.experiment.journal import CellResult

from .scenario import ARMS, GOLD, arm, edition, gold_channel, prediction, records


@pytest.mark.parametrize("outcomes,expected", [
    (("answered", "answered"), (2, 2, 0, 0)),
    (("answered", "backend_failure"), (2, 1, 1, 0)),
    (("backend_failure", "backend_failure"), (2, 0, 2, 0)),
    (("adapter_unavailable", "adapter_unavailable"), (0, 0, 0, 2)),
])
def test_answered_and_failed_cells_count_once(outcomes, expected):
    # what_bug_this_catches: counts[outcome] and counts['answered'] previously
    # both counted the same success, causing negative errors and rejected reports.
    cells = {}
    for name in ARMS:
        for record, outcome in zip(records(), outcomes, strict=True):
            cell = CellResult(
                arm=name, record_id=record.record_id, content_sha256=record.content_sha256,
                attempted=outcome != "adapter_unavailable", outcome=outcome,
                prediction=prediction(name, record.record_id, GOLD[record.record_id])
                if outcome == "answered" else None,
            )
            cells[(name, record.record_id)] = cell
    result = aggregate_edition(edition(), records(), gold_channel(), cells, closed=True)
    for name in ARMS:
        row = arm(result, name)
        assert tuple(row[key] for key in ("attempted_N", "answered_N", "error_N", "unattempted_N")) == expected
        assert row["answered_N"] + row["error_N"] == row["attempted_N"]
        assert row["attempted_N"] + row["unattempted_N"] == row["corpus_N"] == 2
