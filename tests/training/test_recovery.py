"""End-to-end recover_training_run over real execute_training outputs (tmp_path).

Plan: a crash consumes the slot and recovery must account the original attempt;
originals are preserved, unknown liability is kept, nothing is restarted or
reallocated. Runs use the R3 staging tree, a fake engine and the injected
environment check; crashes are simulated with SystemExit (not caught by the
executor) or by rewinding the ledger row as a crash between receipt write and
reconcile would leave it. Expected outcomes are hand-derived per scenario.
"""
from datetime import datetime, timezone
import json
import sqlite3

import pytest

from m7.training.executor import EngineResult, TrainingOOM, execute_training
from m7.training.recovery import RecoveryAuthorization, recover_training_run
from m7.training.validation import digest

from .test_executor_failures import AT, Engine, accept_env, stage

LATER = datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc)  # inside the recovery window


def execute(root, plan, permit, behaviour, **kwargs):
    engine = Engine(behaviour)
    return execute_training(plan, permit, root=root, engine=engine, clock=lambda: AT,
                            environment_check=accept_env, **kwargs), engine


def authorization(root, plan, permit, auth_id="rec-1"):
    header = json.loads((root / "runs/ed-1/run-started.json").read_text(encoding="utf-8"))
    return RecoveryAuthorization(
        authorization_id=auth_id, edition_id="ed-1", plan_sha256=digest(plan), permit_sha256=digest(permit),
        run_started_sha256=digest(header), stopped_worker_receipt_sha256="e" * 64,
        allowed_action="account_interrupted_no_restart", approved_by="int2",
        issued_at="2026-01-01T12:00:00Z", expires_at="2026-01-02T00:00:00Z")


def recover(root, plan, permit, auth_id="rec-1", verify=lambda kind, sha: True):
    return recover_training_run(plan, permit, root=root, authorization=authorization(root, plan, permit, auth_id),
                                verify_receipt=verify, clock=lambda: LATER)


def ledger_rows(root):
    con = sqlite3.connect(root / "accounting/auth-1.sqlite")
    try:
        return con.execute("SELECT state, actual, reserved FROM attempts ORDER BY id").fetchall()
    finally:
        con.close()


def crash(context):
    raise SystemExit()  # BaseException: escapes the executor like a killed worker


def oom(context):
    raise TrainingOOM()


def trains(context):
    out = context.output_dir / "checkpoint"
    out.mkdir()
    (out / "weights.safetensors").write_bytes(b"trained-" + context.trial["trial_id"].encode())
    return EngineResult(optimizer_steps=10, epochs=1.0)


def test_crash_mid_trial_keeps_orphaned_reservation_as_unknown_and_resume_is_refused(tmp_path):
    plan, permit = stage(tmp_path, 3)
    with pytest.raises(SystemExit):
        execute(tmp_path, plan, permit, crash)
    # After the crash: t1 started + reserved 100, no receipt, no run.json.
    assert ledger_rows(tmp_path) == [("reserved", None, 100)]
    report = recover(tmp_path, plan, permit)
    assert [r["outcome"] for r in report["outcomes"]] == ["interrupted_no_success_receipt", "unattempted", "unattempted"]
    assert report["incomplete_attempt_trial_ids"] == ["t1"] and report["unattempted_trial_ids"] == ["t2", "t3"]
    assert report["new_trials_started"] == 0
    acc = report["accounting"]
    # Orphan liability retained as unknown: 100 unresolved, 300 - 100 = 200 remaining, still 1 attempt.
    assert (acc["unresolved_liability_micros"], acc["remaining_micros"], acc["attempts_N"]) == (100, 200, 1)
    assert acc["states"]["unknown"] == 1
    # "Resume" by re-executing the same edition is refused; no second reservation or engine call.
    with pytest.raises(FileExistsError):
        execute(tmp_path, plan, permit, oom)
    assert ledger_rows(tmp_path) == [("unknown", None, 100)]


def _rewind_to_reserved(root):
    # State a crash between receipt.json write and ledger reconcile would leave.
    con = sqlite3.connect(root / "accounting/auth-1.sqlite")
    with con:
        con.execute("UPDATE attempts SET actual=NULL, state='reserved', usage_units=NULL, compute_seconds=NULL, "
                    "amount_source='estimated'")
    con.close()


def test_receipt_with_reserved_row_is_reconciled_once_and_recovery_is_idempotent(tmp_path):
    plan, permit = stage(tmp_path, 1)
    execute(tmp_path, plan, permit, oom)
    _rewind_to_reserved(tmp_path)
    first = recover(tmp_path, plan, permit, "rec-1")
    assert [r["outcome"] for r in first["outcomes"]] == ["original_oom"]
    # oom -> ledger "failed", amount unknown, full 100 kept; compute proxy from receipt duration.
    assert ledger_rows(tmp_path) == [("failed", None, 100)]
    assert first["accounting"]["by_category"]["training"]["unknown_compute_attempts"] == 0
    second = recover(tmp_path, plan, permit, "rec-2")
    assert ledger_rows(tmp_path) == [("failed", None, 100)]
    assert second["accounting"] == first["accounting"]
    assert second["incomplete_attempt_trial_ids"] == [] and second["outcomes"][0]["outcome"] == "original_oom"
    # The same recovery authorization cannot be recorded twice.
    with pytest.raises(FileExistsError):
        recover(tmp_path, plan, permit, "rec-1")


def test_altered_checkpoint_is_refused(tmp_path):
    plan, permit = stage(tmp_path, 1)
    execute(tmp_path, plan, permit, trains)
    (tmp_path / "runs/ed-1/t1/checkpoint/weights.safetensors").write_bytes(b"swapped")
    with pytest.raises(ValueError, match="recovery_checkpoint_hash_mismatch"):
        recover(tmp_path, plan, permit)
    assert not (tmp_path / "runs/ed-1/recovery/rec-1").exists()


def test_altered_but_valid_receipt_is_refused_against_run_closeout(tmp_path):
    plan, permit = stage(tmp_path, 1)
    execute(tmp_path, plan, permit, oom)
    path = tmp_path / "runs/ed-1/t1/receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["duration_seconds"] = 999.0  # still structurally valid
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="recovery_receipt_altered"):
        recover(tmp_path, plan, permit)


def test_unreadable_receipt_is_preserved_as_unusable_with_liability_kept(tmp_path):
    plan, permit = stage(tmp_path, 1)
    execute(tmp_path, plan, permit, oom)
    (tmp_path / "runs/ed-1/t1/receipt.json").write_text("{not json", encoding="utf-8")
    report = recover(tmp_path, plan, permit)
    assert report["outcomes"][0]["outcome"] == "original_receipt_unusable"
    assert report["incomplete_attempt_trial_ids"] == ["t1"]
    # Row was already "failed" with unknown amount: recovery's unknown request is a no-op.
    assert ledger_rows(tmp_path) == [("failed", None, 100)]


def test_recovery_never_starts_or_reopens_trials(tmp_path):
    plan, permit = stage(tmp_path, 3)
    _, engine = execute(tmp_path, plan, permit, trains)
    report = recover(tmp_path, plan, permit)
    assert [r["outcome"] for r in report["outcomes"]] == ["original_completed"] * 3
    assert report["new_trials_started"] == 0
    assert all(r["checkpoint_promoted"] is False and r["new_attempt_allowed"] is False for r in report["outcomes"])
    assert engine.calls == 3 and report["accounting"]["attempts_N"] == 3
    assert ledger_rows(tmp_path) == [("succeeded", None, 100)] * 3
    assert sorted(p.name for p in (tmp_path / "runs/ed-1").iterdir() if p.name.startswith("t")) == ["t1", "t2", "t3"]
    # A plan with a 4th trial cannot be recovered under this run's authorization/header
    # (its digest differs from the authorized and started plan).
    plan4 = json.loads(json.dumps(plan))
    plan4["trials"].append({"trial_id": "t4", "seed": 4, "learning_rate": 0.0001, "batch_size": 8})
    with pytest.raises(ValueError, match="recovery_authorization_binding_mismatch"):
        recover_training_run(plan4, permit, root=tmp_path,
                             authorization=authorization(tmp_path, plan, permit, "rec-4"),
                             verify_receipt=lambda kind, sha: True, clock=lambda: LATER)


def test_missing_store_is_not_created(tmp_path):
    plan, permit = stage(tmp_path, 3)
    result, _ = execute(tmp_path, plan, permit, oom, cancel=lambda: True)
    assert result["receipts"] == []
    store = tmp_path / "accounting/auth-1.sqlite"
    store.unlink()  # created by this test's own run
    report = recover(tmp_path, plan, permit)
    assert report["accounting"] is None
    assert [r["outcome"] for r in report["outcomes"]] == ["unattempted"] * 3
    assert not store.exists()


def test_unproven_worker_stop_fails_closed(tmp_path):
    plan, permit = stage(tmp_path, 1)
    with pytest.raises(SystemExit):
        execute(tmp_path, plan, permit, crash)
    with pytest.raises(ValueError, match="receipt_not_authenticated_or_revoked"):
        recover(tmp_path, plan, permit, verify=lambda kind, sha: kind != "training_worker_stopped")
    assert ledger_rows(tmp_path) == [("reserved", None, 100)]
