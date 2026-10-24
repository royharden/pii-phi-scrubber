"""Development runner: fixed intended population, value-free failures, arm status.

Adapters are in-process stubs; no backend, provider or network is touched.
Expected counts are derived by hand from the two records below.
"""
import pytest

from m7.contracts import LogRecord, Prediction, Span, make_record
from m7.runner import ARMS, EvaluationRecord, run_offline

# r1 "acct=A123 ok": "acct=" 0..4, "A123" = [5,9) ACCOUNT_ID. Length 12.
# r2 "mail a@b.io": "mail " 0..4, "a@b.io" = [5,11) EMAIL. Length 11.
R1 = make_record("acct=A123 ok", "r1")
R2 = make_record("mail a@b.io", "r2")
G1 = (Span(start=5, end=9, label="ACCOUNT_ID"),)
G2 = (Span(start=5, end=11, label="EMAIL"),)
assert len(R1.log.message) == 12 and len(R2.log.message) == 11
RECORDS = [EvaluationRecord(R1, G1, "blk-a"), EvaluationRecord(R2, G2, "blk-b", "challenge")]
GOLD = {"r1": G1, "r2": G2}


def prediction(record, spans, *, arm, run_id="development"):
    return Prediction(run_id=run_id, record_id=record.record_id, content_sha256=record.content_sha256,
                      arm=arm, model_id="stub", attempt_id="att-" + record.record_id,
                      status="ok", spans=tuple(spans))


def oracle(arm):
    return lambda record: prediction(record, GOLD[record.record_id], arm=arm)


def arm_row(bundle, arm):
    return next(r for r in bundle["arms"] if r["arm"] == arm)


def test_absent_arms_not_measured_with_null_metrics():
    bundle = run_offline(RECORDS, {"regex": oracle("regex")})
    assert [r["arm"] for r in bundle["arms"]] == list(ARMS)
    for arm in ("frontier", "base", "finetuned"):
        row = arm_row(bundle, arm)
        assert row["measurement_status"] == "not_measured" and row["reason"] == "adapter_unavailable"
        assert row["metrics"] is None and row["unattempted_N"] == 2 and row["answered_N"] == 0
    assert bundle["paired_fine_minus_base"] is None


def test_perfect_arm_counts_and_insufficient_interval_units():
    row = arm_row(run_offline(RECORDS, {"regex": oracle("regex")}), "regex")
    assert row["measurement_status"] == "measured" and row["reason"] is None
    assert (row["attempted_N"], row["answered_N"], row["error_N"]) == (2, 2, 0)
    micro = row["metrics"]["micro"]
    assert (micro["tp"], micro["fp"], micro["fn"]) == (2, 0, 0)
    # Slices: r1 normal has the ACCOUNT TP, r2 challenge has the EMAIL TP.
    assert row["slices"]["normal"]["per_class"]["ACCOUNT_ID"]["tp"] == 1
    assert row["slices"]["challenge"]["per_class"]["EMAIL"]["tp"] == 1
    # Only 2 blocks (< 20) -> no nominal interval.
    assert row["intervals"]["micro"]["recall"]["interval"] is None
    assert row["intervals"]["micro"]["recall"]["null_reason"] == "insufficient_units"


def test_failing_adapter_keeps_record_in_denominator_as_miss():
    def flaky(record):
        if record.record_id == "r2":
            raise RuntimeError("provider said a@b.io")  # value-bearing message must not leak
        return prediction(record, G1, arm="frontier")

    bundle = run_offline(RECORDS, {"frontier": flaky})
    row = arm_row(bundle, "frontier")
    assert row["measurement_status"] == "measured_incomplete" and row["reason"] == "terminal_failures"
    assert (row["corpus_N"], row["attempted_N"], row["answered_N"], row["error_N"]) == (2, 2, 1, 1)
    m = row["metrics"]
    # r1 ACCOUNT TP; r2 failed -> EMAIL FN (not dropped). micro tp1 fp0 fn1, recall 1/2.
    assert (m["micro"]["tp"], m["micro"]["fp"], m["micro"]["fn"]) == (1, 0, 1)
    assert m["micro"]["recall"]["value"] == 0.5 and m["corpus_N"] == 2
    # Residual: r2's 6 EMAIL codepoints of 4 + 6 = 10 total.
    assert (m["residual_sensitive_codepoints"]["numerator"], m["residual_sensitive_codepoints"]["denominator"]) == (6, 10)
    # Successful-only is secondary and excludes r2: recall 1/1.
    assert row["successful_only"]["micro"]["recall"]["value"] == 1.0
    assert row["diagnostics"] == [{"record_id": "r2", "error_code": "attempt_failed"}]
    assert "a@b.io" not in repr(bundle)


def test_prediction_identity_mismatch_is_terminal_failure():
    # Adapter claims the wrong arm -> rejected, not scored as the requested arm.
    bundle = run_offline(RECORDS, {"base": oracle("finetuned")})
    row = arm_row(bundle, "base")
    assert (row["answered_N"], row["error_N"]) == (0, 2)
    assert row["metrics"]["micro"]["fn"] == 2 and row["metrics"]["micro"]["tp"] == 0
    assert row["metrics"]["unavailable"]["numerator"] == 2


def test_prediction_for_other_record_is_identity_mismatch():
    # Adapter answers r1's identity for every record: r2's hash/id mismatch -> failure.
    def wrong(record):
        return prediction(R1, G1, arm="regex")

    row = arm_row(run_offline(RECORDS, {"regex": wrong}), "regex")
    assert row["answered_N"] == 1
    assert {"record_id": "r2", "error_code": "identity_mismatch"} in row["diagnostics"]


def test_adapter_receives_only_the_log_record():
    seen = []

    def spy(record):
        seen.append(record)
        return prediction(record, (), arm="regex")

    run_offline(RECORDS, {"regex": spy})
    assert [type(r) for r in seen] == [LogRecord, LogRecord]
    assert [r.record_id for r in seen] == ["r1", "r2"]


def test_publication_suppression_does_not_change_scores():
    leaky = {"regex": lambda record: prediction(record, (), arm="regex")}
    plain = arm_row(run_offline(RECORDS, leaky), "regex")
    gated = run_offline(RECORDS, leaky, publication_gate=lambda rec, gold, rendered: {"approved": False})
    row = arm_row(gated, "regex")
    assert row["publication_suppressed_N"] == 2
    assert row["metrics"] == plain["metrics"]
    # Pre-gate leak still counted: nothing predicted -> 10 of 10 sensitive codepoints remain.
    assert row["metrics"]["residual_sensitive_codepoints"]["numerator"] == 10


def test_paired_fine_minus_base_present_but_null_with_two_blocks():
    bundle = run_offline(RECORDS, {"base": lambda r: prediction(r, (), arm="base"), "finetuned": oracle("finetuned")})
    paired = bundle["paired_fine_minus_base"]
    assert paired["interval"] is None and paired["null_reason"] == "insufficient_units"
    assert paired["effective_blocks"] == 2
    assert bundle["paired_fine_minus_base_slices"]["normal"]["effective_blocks"] == 1


def test_population_and_provenance_validation():
    with pytest.raises(ValueError):
        run_offline(RECORDS, {"oracle": oracle("regex")})  # unknown arm
    with pytest.raises(ValueError):
        run_offline(RECORDS + [EvaluationRecord(R1, G1, "blk-c")], {})  # duplicate record id
    with pytest.raises(ValueError):
        run_offline([EvaluationRecord(R1, G1, "")], {})  # missing block
    with pytest.raises(ValueError):
        run_offline([EvaluationRecord(R1, G1, "blk-a", "seen")], {})  # undeclared slice
    with pytest.raises(ValueError):
        # Gold end 13 > len 12.
        run_offline([EvaluationRecord(R1, (Span(start=5, end=13, label="ACCOUNT_ID"),), "blk-a")], {})


def test_empty_corpus_marks_every_arm_unmeasured():
    bundle = run_offline([], {"regex": oracle("regex")})
    # Even the supplied arm cannot be "measured" over zero intended records.
    assert len(bundle["arms"]) == 4
    assert all(r["measurement_status"] == "not_measured" and r["reason"] == "empty_corpus"
               and r["metrics"] is None for r in bundle["arms"])
