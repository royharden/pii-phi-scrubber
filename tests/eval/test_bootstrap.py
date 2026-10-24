"""Block-bootstrap arithmetic on inputs whose interval is derivable by hand.

Plan: fixed-seed 2,000-replicate whole-block bootstrap, 95% percentile, >=20
independent blocks else interval=null/insufficient_units, <1,800 defined draws
else interval=null/insufficient_valid_draws.
"""
import pytest

from m7.contracts import Span
from m7.eval import Observation
from m7.eval.bootstrap import metric_intervals, paired_interval

# Same message layout as test_scoring: NAME [5,12), EMAIL [18,24), PHONE [29,37), ACCOUNT [43,47).
M = "name=Ann Lee mail=a@b.io tel=555-0100 acct=A123"
GOLD = (Span(start=5, end=12, label="NAME"), Span(start=18, end=24, label="EMAIL"),
        Span(start=29, end=37, label="PHONE"), Span(start=43, end=47, label="ACCOUNT_ID"))


def rows(n_blocks, predicted_for, gold=GOLD):
    """One record per block; predicted_for(i) gives block i's predicted spans."""
    return [Observation(f"r{i}", f"blk{i:02d}", "normal", len(M), gold, tuple(predicted_for(i)), True, True)
            for i in range(n_blocks)]


def macro_f1(m):
    return m["macro"]["f1"]["value"]


def test_constant_paired_difference_gives_degenerate_hand_interval():
    # fine: every class exact in every block -> macro F1 = (1+1+1+1)/4 = 1.0 in EVERY draw.
    # base: no spans -> per class tp0 fp0 fn>=1 -> F1 = 0/(0+0+fn) = 0, macro 0.0 in every draw.
    # Every resample differs by exactly 1.0, so both percentiles are 1.0.
    fine = rows(20, lambda i: GOLD)
    base = rows(20, lambda i: ())
    out = paired_interval(fine, base, macro_f1)
    assert out["interval"] == [1.0, 1.0]
    assert out["null_reason"] is None
    assert (out["effective_blocks"], out["valid_draws"], out["undefined_draws"]) == (20, 2000, 0)
    assert out["draws"] == 2000 and out["level"] == 0.95 and out["method"] == "paired_group_percentile"
    assert isinstance(out["draw_digest"], str) and len(out["draw_digest"]) == 64


def test_insufficient_blocks_is_explicit_null_without_draws():
    # 19 < 20 independent blocks -> no resampling at all.
    out = paired_interval(rows(19, lambda i: GOLD), rows(19, lambda i: ()), macro_f1)
    assert out["interval"] is None and out["null_reason"] == "insufficient_units"
    assert out["effective_blocks"] == 19 and out["executed_draws"] == 0
    ab = metric_intervals(rows(19, lambda i: GOLD))
    assert ab["micro"]["recall"]["interval"] is None
    assert ab["micro"]["recall"]["null_reason"] == "insufficient_units"


def test_many_records_in_few_blocks_still_insufficient():
    # 40 records but only 2 provenance blocks: units are blocks, not records/spans.
    data = [Observation(f"r{i}", f"blk{i % 2}", "normal", len(M), GOLD, GOLD, True, True) for i in range(40)]
    out = metric_intervals(data)
    assert out["micro"]["f1"]["effective_blocks"] == 2
    assert out["micro"]["f1"]["null_reason"] == "insufficient_units"


def test_always_undefined_metric_yields_insufficient_valid_draws():
    # Only EMAIL gold -> NAME/PHONE/ACCOUNT undefined -> macro F1 null in every draw (0 of 2000 valid).
    email_only = (GOLD[1],)
    left = rows(20, lambda i: email_only, gold=email_only)
    right = rows(20, lambda i: (), gold=email_only)
    out = paired_interval(left, right, macro_f1)
    assert out["interval"] is None and out["null_reason"] == "insufficient_valid_draws"
    assert (out["valid_draws"], out["undefined_draws"], out["executed_draws"]) == (0, 2000, 2000)


def test_absolute_intervals_constant_and_undefined_paths():
    perfect = metric_intervals(rows(20, lambda i: GOLD))
    assert perfect["micro"]["recall"]["interval"] == [1.0, 1.0]
    # No residual sensitive codepoints in any draw: 0/25k = 0.0.
    assert perfect["residual_sensitive_codepoints"]["interval"] == [0.0, 0.0]
    assert perfect["macro_f1"] == perfect["macro"]["f1"]
    empty = metric_intervals(rows(20, lambda i: ()))
    # tp0 fp0 every draw -> micro precision 0/0 always undefined, never filled with 0.
    assert empty["micro"]["precision"]["interval"] is None
    assert empty["micro"]["precision"]["null_reason"] == "insufficient_valid_draws"
    assert empty["micro"]["recall"]["interval"] == [0.0, 0.0]
    assert empty["residual_sensitive_codepoints"]["interval"] == [1.0, 1.0]


def test_mixed_blocks_interval_brackets_point_and_is_seed_deterministic():
    # 10 perfect + 10 fully missed blocks, one EMAIL each: micro recall of a draw = (#perfect drawn)/20,
    # point estimate 0.5. A 95% percentile interval must satisfy 0 <= lo < 0.5 < hi <= 1
    # (Binomial(20, .5): P(X <= 6) = P(recall <= 0.30) ~ 5.8%, symmetric above 0.70, so the
    # 2.5th/97.5th percentiles of 2,000 draws sit well away from 0.5).
    email = (GOLD[1],)
    data = rows(20, lambda i: email if i < 10 else (), gold=email)
    a = metric_intervals(data, seed=7)["micro"]["recall"]
    lo, hi = a["interval"]
    assert 0.0 <= lo < 0.5 < hi <= 1.0
    b = metric_intervals(data, seed=7)["micro"]["recall"]
    assert a == b
    c = metric_intervals(data, seed=8)["micro"]["recall"]
    assert c["draw_digest"] != a["draw_digest"]


def test_preregistered_limits_and_pairing_are_enforced():
    fine, base = rows(20, lambda i: GOLD), rows(20, lambda i: ())
    with pytest.raises(ValueError):
        paired_interval(fine, base, macro_f1, draws=500)
    with pytest.raises(ValueError):
        paired_interval(fine, base, macro_f1, minimum_blocks=5)
    with pytest.raises(ValueError):
        paired_interval(fine, base, macro_f1, minimum_valid=100)
    with pytest.raises(ValueError):
        paired_interval(fine, base[:-1], macro_f1)  # different populations
    moved = [Observation(r.record_id, "other", r.slice_name, r.length, r.gold, r.predicted, True, True)
             if r.record_id == "r0" else r for r in base]
    with pytest.raises(ValueError):
        paired_interval(fine, moved, macro_f1)  # same id, different provenance block
    with pytest.raises(ValueError):
        metric_intervals(fine, moved)
