"""Reject incomplete compute metadata instead of silently losing known evidence."""

import pytest

from m7.experiment.costing import cost_report

from .test_costing_passthrough import CATEGORIES, summary


@pytest.mark.parametrize("category", CATEGORIES)
@pytest.mark.parametrize("missing", ("known_compute_seconds", "unknown_compute_attempts", "both"))
def test_partial_category_compute_is_rejected(category, missing):
    # what_bug_this_catches: one absent category disabled _has_compute and dropped
    # every category's known seconds, falsely resembling a legacy unknown ledger.
    value = summary()
    for key in ("known_compute_seconds", "unknown_compute_attempts"):
        if missing in (key, "both"):
            value["by_category"][category].pop(key)
    with pytest.raises(ValueError):
        cost_report(value)


def test_only_unknown_compute_counts_are_not_legacy_absence():
    value = summary()
    for row in value["by_category"].values():
        row.pop("known_compute_seconds")
    with pytest.raises(ValueError):
        cost_report(value)


def test_fully_absent_legacy_compute_stays_unknown():
    result = cost_report(summary(with_compute=False))
    assert result["known_compute_seconds"] is None
    assert result["unknown_compute_attempts"] is None
