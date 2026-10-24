"""Trial cap, custody and failure-receipt liability (plan: Model and baseline selection).

Plan: at most three fine-tuning trials, max three epochs and 1,000 optimizer steps,
sealed test never accessible to training, failed/OOM/cancelled work recorded with
its reservation retained. Validation grants no execution. Inputs are hand-built;
`digest`/`training_attempt_id` are used only to construct lineage inputs, never to
compute an expected result.
"""
from datetime import datetime, timezone

import pytest

from m7.ledger import BudgetExceeded, ReservationLedger
from m7.training.executor import execute_training
from m7.training.validation import (
    digest, training_attempt_id, validate_training_outcome, validate_training_plan,
)

AT = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
PER_TRIAL = 100


def h(c):
    return c * 64


def artifacts():
    names = ("model", "tokenizer", "train", "dev", "config", "environment", "license_packet", "custody_audit")
    out = {}
    for i, name in enumerate(names):
        out[name] = {"path": f"staged/{name}" + ("" if name in ("model", "tokenizer") else ".json"),
                     "sha256": h("0123456789abcdef"[i]),
                     "kind": "tree" if name in ("model", "tokenizer") else "file"}
    return out


def trial(n, seed=None):
    return {"trial_id": f"t{n}", "seed": n if seed is None else seed, "learning_rate": 0.0001, "batch_size": 8}


def plan(**overrides):
    p = {"schema_version": "TrainingPlan/v2", "edition_id": "ed-1", "artifacts": artifacts(),
         "trials": [trial(1), trial(2), trial(3)], "max_epochs": 3, "max_steps": 1000,
         "max_seconds_per_trial": 3600, "per_trial_worst_case_micros": PER_TRIAL,
         "selection_rule": "dev_macro_exact_f1_then_recall_then_lower_cost",
         "sealed_test_access": False, "resource_id": "res-1", "backend": "gliner_local"}
    p.update(overrides)
    return p


def permit(p, **overrides):
    q = {"schema_version": "ExecutionPermit/v2", "authorization_id": "auth-1", "approved": True,
         "training_allowed": True, "plan_sha256": digest(p), "edition_id": p["edition_id"],
         "license_packet_sha256": p["artifacts"]["license_packet"]["sha256"],
         "custody_audit_sha256": p["artifacts"]["custody_audit"]["sha256"],
         "resource_id": p["resource_id"], "cap_micros": 3 * PER_TRIAL, "currency": "USD",
         "issued_at": "2026-01-01T00:00:00Z", "expires_at": "2026-01-02T00:00:00Z", "approved_by": "roy"}
    q.update(overrides)
    return q


def test_three_trials_validate_without_granting_execution():
    p = plan()
    out = validate_training_plan(p, permit(p), at=AT)
    assert out["status"] == "plan_validated_not_executed"
    assert out["execution_allowed_now"] is False


@pytest.mark.parametrize("trials", [[], [trial(1), trial(2), trial(3), trial(4)]])
def test_trial_cap_zero_or_four_refused(trials):
    p = plan(trials=trials)
    with pytest.raises(ValueError, match="trial_cap_exceeded"):
        validate_training_plan(p, permit(p), at=AT)


def test_duplicate_trial_id_refused():
    p = plan(trials=[trial(1), trial(1, seed=9)])
    with pytest.raises(ValueError, match="duplicate_trial"):
        validate_training_plan(p, permit(p), at=AT)


@pytest.mark.parametrize("key,value", [("max_epochs", 4), ("max_steps", 1001), ("max_epochs", 0)])
def test_epoch_and_step_caps(key, value):
    p = plan(**{key: value})
    with pytest.raises(ValueError, match="invalid_integer_bound"):
        validate_training_plan(p, permit(p), at=AT)


def test_sealed_test_access_and_split_alias_refused():
    p = plan(sealed_test_access=True)
    with pytest.raises(ValueError, match="invalid_selection_custody"):
        validate_training_plan(p, permit(p), at=AT)
    a = artifacts()
    a["dev"]["path"] = a["train"]["path"]  # dev aliased to train
    p = plan(artifacts=a)
    with pytest.raises(ValueError, match="split_alias"):
        validate_training_plan(p, permit(p), at=AT)


def test_cap_must_cover_every_trial_worst_case():
    # 3 trials x 100 = 300 micros; 299 cannot cover the third reservation.
    p = plan()
    with pytest.raises(ValueError, match="invalid_integer_bound"):
        validate_training_plan(p, permit(p, cap_micros=299), at=AT)
    validate_training_plan(p, permit(p, cap_micros=300), at=AT)


def test_permit_window_is_half_open_and_bound_to_plan():
    p = plan()
    q = permit(p)
    validate_training_plan(p, q, at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc))  # issued_at: inside
    with pytest.raises(ValueError, match="permit_not_current"):
        validate_training_plan(p, q, at=datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc))  # expires_at: outside
    changed = plan(max_steps=999)  # plan edited after the permit was issued
    with pytest.raises(ValueError, match="permit_plan_mismatch"):
        validate_training_plan(changed, q, at=AT)


def test_execute_training_refuses_before_any_filesystem_or_engine(tmp_path):
    called = []

    class Engine:
        def run(self, context):
            called.append(context)

    missing_root = tmp_path / "does-not-exist"
    p = plan(trials=[trial(1), trial(2), trial(3), trial(4)])
    with pytest.raises(ValueError, match="trial_cap_exceeded"):
        execute_training(p, permit(p), root=missing_root, engine=Engine(), clock=lambda: AT)
    v1 = {"schema_version": "TrainingPlan/v1"}
    with pytest.raises(ValueError, match="execution_requires_v2_plan"):
        execute_training(v1, {}, root=missing_root, engine=Engine(), clock=lambda: AT)
    assert called == [] and not missing_root.exists()


def failure_receipt(p, q, status, error_code, **overrides):
    t = p["trials"][0]
    r = {"schema_version": "TrainingReceipt/v2", "execution_kind": "actual_training",
         "edition_id": p["edition_id"], "plan_sha256": digest(p), "permit_sha256": digest(q),
         "authorization_id": q["authorization_id"],
         "artifact_hashes": {k: v["sha256"] for k, v in p["artifacts"].items()},
         "trial_id": t["trial_id"], "trial_sha256": digest(t), "seed": t["seed"],
         "status": status, "error_code": error_code, "optimizer_steps": None, "epochs": None,
         "checkpoint_sha256": None, "checkpoint_relative_path": None,
         "ledger_attempt_id": training_attempt_id(digest(p), t["trial_id"]),
         "reserved_micros": PER_TRIAL, "actual_micros": None, "billing_receipt_id": None,
         "cost_status": "unknown", "started_at": "2026-01-01T06:00:00Z",
         "finished_at": "2026-01-01T06:05:00Z", "duration_seconds": 300.0,
         "independent_audit": "pending", "m7_02_accepted": False}
    r.update(overrides)
    return r


@pytest.mark.parametrize("status,code", [("failed", "engine_failure"), ("oom", "out_of_memory"),
                                         ("cancelled", "cancelled")])
def test_failure_receipts_are_valid_failures_never_acceptance(status, code):
    p = plan()
    q = permit(p)
    out = validate_training_outcome(failure_receipt(p, q, status, code), p, q)
    assert out == {"status": "structurally_valid_failure", "independent_audit": "pending",
                   "m7_02_accepted": False}


def test_failure_receipt_with_wrong_code_refused():
    p = plan()
    q = permit(p)
    with pytest.raises(ValueError, match="failed_training_receipt_binding_mismatch"):
        validate_training_outcome(failure_receipt(p, q, "oom", "engine_failure"), p, q)


@pytest.mark.parametrize("overrides", [{"reserved_micros": 0}, {"reserved_micros": 50},
                                       {"cost_status": "known"}, {"m7_02_accepted": True}])
def test_failure_receipt_cannot_drop_liability_or_claim_acceptance(overrides):
    # reserved 0/50 would release part of the 100-micro worst case; "known" cost claims a resolved amount.
    p = plan()
    q = permit(p)
    with pytest.raises(ValueError, match="failed_training_receipt_binding_mismatch"):
        validate_training_outcome(failure_receipt(p, q, "oom", "out_of_memory", **overrides), p, q)


@pytest.mark.parametrize("overrides", [{"checkpoint_sha256": h("f")}, {"optimizer_steps": 10},
                                       {"actual_micros": 0, "billing_receipt_id": "bill-1"}])
def test_failure_receipt_cannot_claim_completed_work(overrides):
    p = plan()
    q = permit(p)
    with pytest.raises(ValueError, match="failed_attempt_cannot_claim_completed_work"):
        validate_training_outcome(failure_receipt(p, q, "failed", "engine_failure", **overrides), p, q)


def test_failed_oom_cancelled_reconciliations_retain_full_liability(tmp_path):
    # Ledger-level only: uses the same reconcile arguments executor.py:227 passes for
    # non-completed trials (actual None, receipt None, usage None; oom -> "failed").
    # An execute_training-level OOM/cancel test needs an environment-check seam
    # (artifacts.py:123-131 requires installed gliner/torch); deferred.
    led = ReservationLedger(tmp_path / "train.sqlite3", cap_micros=3 * PER_TRIAL, authorization_id="auth-1")
    led.initialize()
    for n, state in ((1, "failed"), (2, "failed"), (3, "cancelled")):
        led.reserve(f"train-{n}", PER_TRIAL, category="training")
        led.reconcile(f"train-{n}", actual_micros=None, state=state)
    s = led.summary()
    # 3 x 100 retained as unresolved; nothing known; remaining 300 - 300 = 0.
    assert (s["unresolved_liability_micros"], s["known_provider_cash_micros"], s["remaining_micros"]) == (300, 0, 0)
    assert s["by_category"]["training"]["unknown_attempts"] == 3
    with pytest.raises(BudgetExceeded):
        led.reserve("train-4", 1, category="training")
