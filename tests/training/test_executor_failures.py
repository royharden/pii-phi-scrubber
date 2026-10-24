"""execute_training with an injected fake engine and environment check.

Plan: failed/OOM work is recorded, cancellation retains receipts and reconciles
outstanding reservations rather than refunding, no backend message enters a
receipt. Only the installed-version probe is replaced (environment_check); every
artifact pin/license/custody/config check still runs on real files in tmp_path.
Hashes of the staged files are computed with the same canonical helpers only to
build valid inputs; no assertion compares against a value produced by the code
under test.
"""
from datetime import datetime, timezone
import json

import pytest

from m7.contracts import make_record
from m7.training.artifacts import file_sha256, tree_sha256
from m7.training.executor import EngineResult, TrainingCancelled, TrainingOOM, execute_training
from m7.training.validation import digest

AT = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
PER_TRIAL = 100
LABELS = ["NAME", "EMAIL", "PHONE", "ACCOUNT_ID"]


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _dataset(split, messages):
    return {"schema_version": "TrainingDataset/v1", "split": split,
            "records": [{"record": make_record(m, f"{split}-{i}", split_id=split).model_dump(mode="json"),
                         "gold": [{"start": 5, "end": 9, "label": "ACCOUNT_ID"}]}
                        for i, m in enumerate(messages)]}


def stage(root, trials=3):
    """Build a complete, internally consistent staging tree; return (plan, permit)."""
    (root / "staged/model").mkdir(parents=True)
    (root / "staged/model/model.safetensors").write_bytes(b"fake-weights")
    (root / "staged/tokenizer").mkdir(parents=True)
    (root / "staged/tokenizer/tokenizer.json").write_text("{}", encoding="utf-8")
    train = _write(root / "staged/train.json", _dataset("train", ["acct=A111 ok", "acct=A222 ok"]))
    dev = _write(root / "staged/dev.json", _dataset("dev", ["acct=A333 ok"]))
    descriptions = ["fictional person name", "email address", "phone number", "account identifier"]
    config = _write(root / "staged/config.json", {
        "schema_version": "TrainingConfig/v1", "labels": LABELS, "label_descriptions": descriptions,
        "max_message_codepoints": 1024, "max_model_tokens": 512, "decoder_sha256": "d" * 64,
        "label_descriptions_sha256": digest(descriptions)})
    environment = _write(root / "staged/environment.json", {
        "schema_version": "TrainingEnvironment/v1", "python": "0.0.0-pinned",
        "packages": {"gliner": "0", "torch": "0", "transformers": "0", "accelerate": "0", "safetensors": "0"},
        "resource_id": "res-1", "device": "cpu"})
    hashes = {"model": tree_sha256(root / "staged/model"), "tokenizer": tree_sha256(root / "staged/tokenizer"),
              "train": file_sha256(train), "dev": file_sha256(dev)}
    license_packet = _write(root / "staged/license.json", {
        "schema_version": "LicensePacket/v1", "approved": True, "approved_by": "roy",
        "training_allowed": True, "derivatives_allowed": True, "artifacts": dict(hashes)})
    custody = _write(root / "staged/custody.json", {
        "schema_version": "TrainingCustody/v1", "edition_id": "ed-1", "approved": True,
        "author_id": "custodian-a", "auditor_id": "auditor-b", "allowed_splits": ["train", "dev"],
        "train_sha256": hashes["train"], "dev_sha256": hashes["dev"], "test_access_allowed": False})
    files = {"train": train, "dev": dev, "config": config, "environment": environment,
             "license_packet": license_packet, "custody_audit": custody}
    artifacts = {"model": {"path": "staged/model", "sha256": hashes["model"], "kind": "tree"},
                 "tokenizer": {"path": "staged/tokenizer", "sha256": hashes["tokenizer"], "kind": "tree"}}
    for name, path in files.items():
        artifacts[name] = {"path": path.relative_to(root).as_posix(), "sha256": file_sha256(path), "kind": "file"}
    plan = {"schema_version": "TrainingPlan/v2", "edition_id": "ed-1", "artifacts": artifacts,
            "trials": [{"trial_id": f"t{n}", "seed": n, "learning_rate": 0.0001, "batch_size": 8}
                       for n in range(1, trials + 1)],
            "max_epochs": 3, "max_steps": 1000, "max_seconds_per_trial": 3600,
            "per_trial_worst_case_micros": PER_TRIAL,
            "selection_rule": "dev_macro_exact_f1_then_recall_then_lower_cost",
            "sealed_test_access": False, "resource_id": "res-1", "backend": "gliner_local"}
    permit = {"schema_version": "ExecutionPermit/v2", "authorization_id": "auth-1", "approved": True,
              "training_allowed": True, "plan_sha256": digest(plan), "edition_id": "ed-1",
              "license_packet_sha256": artifacts["license_packet"]["sha256"],
              "custody_audit_sha256": artifacts["custody_audit"]["sha256"], "resource_id": "res-1",
              "cap_micros": trials * PER_TRIAL, "currency": "USD", "issued_at": "2026-01-01T00:00:00Z",
              "expires_at": "2026-01-02T00:00:00Z", "approved_by": "roy"}
    return plan, permit


def accept_env(environment):
    # Stub host check: the pinned environment is "installed". Never used for real runs.
    if environment["resource_id"] != "res-1":
        raise ValueError("environment_scope_mismatch")


class Engine:
    def __init__(self, behaviour):
        self.behaviour, self.calls = behaviour, 0

    def run(self, context):
        self.calls += 1
        return self.behaviour(context)


def run(tmp_path, behaviour, *, trials=3, cancel=None):
    plan, permit = stage(tmp_path, trials)
    engine = Engine(behaviour)
    result = execute_training(plan, permit, root=tmp_path, engine=engine, cancel=cancel,
                              clock=lambda: AT, environment_check=accept_env)
    return result, engine


def oom(context):
    raise TrainingOOM()


def test_every_trial_oom_keeps_three_full_reservations(tmp_path):
    result, engine = run(tmp_path, oom)
    # OOM is a failed trial, not a stop: all 3 planned trials attempted.
    assert engine.calls == 3 and result["status"] == "completed_with_outcomes"
    assert [r["status"] for r in result["receipts"]] == ["oom", "oom", "oom"]
    assert all(r["error_code"] == "out_of_memory" and r["actual_micros"] is None
               and r["cost_status"] == "unknown" and r["reserved_micros"] == 100
               and r["checkpoint_sha256"] is None for r in result["receipts"])
    acc = result["accounting"]
    # 3 x 100 unresolved, nothing known, cap 300 fully committed; oom -> ledger state "failed".
    assert (acc["unresolved_liability_micros"], acc["known_provider_cash_micros"], acc["remaining_micros"]) == (300, 0, 0)
    assert acc["states"]["failed"] == 3 and acc["amount_sources"]["estimated"] == 3
    # executor passes each receipt duration as the compute-time proxy (no unknowns).
    assert acc["by_category"]["training"]["unknown_compute_attempts"] == 0
    assert result["unattempted_trial_ids"] == []
    assert (tmp_path / "runs/ed-1/t1/receipt.json").is_file()


def test_runtime_out_of_memory_message_maps_to_oom(tmp_path):
    def cuda(context):
        raise RuntimeError("CUDA out of memory. Tried to allocate 2 GiB")
    result, _ = run(tmp_path, cuda, trials=1)
    assert result["receipts"][0]["status"] == "oom"


def test_engine_failure_message_never_enters_receipt(tmp_path):
    def leaky(context):
        raise RuntimeError("tokenizer choked on a@b.io")
    result, _ = run(tmp_path, leaky, trials=1)
    assert result["receipts"][0]["status"] == "failed"
    assert result["receipts"][0]["error_code"] == "engine_failure"
    assert "a@b.io" not in json.dumps(result)
    assert "a@b.io" not in (tmp_path / "runs/ed-1/t1/receipt.json").read_text(encoding="utf-8")


def test_engine_cancel_stops_run_and_retains_liability(tmp_path):
    def cancelled(context):
        raise TrainingCancelled()
    result, engine = run(tmp_path, cancelled)
    # First trial cancelled -> loop stops; t2, t3 never attempted or reserved.
    assert engine.calls == 1 and result["status"] == "cancelled"
    assert [r["status"] for r in result["receipts"]] == ["cancelled"]
    assert result["unattempted_trial_ids"] == ["t2", "t3"]
    acc = result["accounting"]
    # Only t1 was reserved: 100 retained (not refunded), 300 - 100 = 200 remaining.
    assert (acc["unresolved_liability_micros"], acc["remaining_micros"], acc["attempts_N"]) == (100, 200, 1)
    assert acc["states"]["cancelled"] == 1


def test_cancel_before_first_reservation_reserves_nothing(tmp_path):
    result, engine = run(tmp_path, oom, cancel=lambda: True)
    assert engine.calls == 0 and result["status"] == "cancelled"
    assert result["receipts"] == [] and result["unattempted_trial_ids"] == ["t1", "t2", "t3"]
    assert result["accounting"]["attempts_N"] == 0


def test_heartbeat_cancel_during_trial_is_cancelled(tmp_path):
    flag = {"stop": False}

    def stops(context):
        flag["stop"] = True
        context.heartbeat()  # engine polls heartbeat each step -> raises TrainingCancelled
        return EngineResult(optimizer_steps=1, epochs=1.0)
    # cancel() is consulted before reserving (False) and in heartbeat (True after the flag flips).
    result, _ = run(tmp_path, stops, trials=1, cancel=lambda: flag["stop"])
    assert result["receipts"][0]["status"] == "cancelled"
    assert result["accounting"]["unresolved_liability_micros"] == 100


def test_completed_trial_without_billing_keeps_estimated_liability(tmp_path):
    def trains(context):
        out = context.output_dir / "checkpoint"
        out.mkdir()
        (out / "weights.safetensors").write_bytes(b"trained")
        return EngineResult(optimizer_steps=10, epochs=1.0)
    result, _ = run(tmp_path, trains, trials=1)
    r = result["receipts"][0]
    assert r["status"] == "completed" and r["checkpoint_relative_path"] == "runs/ed-1/t1/checkpoint"
    assert r["actual_micros"] is None and r["cost_status"] == "unknown"
    acc = result["accounting"]
    # INT R2 ruling A: succeeded + estimated keeps the full 100 reserved liability.
    assert acc["states"]["succeeded"] == 1 and acc["unresolved_liability_micros"] == 100
    assert acc["amount_sources"] == {"estimated": 1, "actual": 0}
    assert acc["by_category"]["training"]["known_usage_units"] == 10


def test_engine_exceeding_step_cap_is_failure_not_success(tmp_path):
    def overrun(context):
        out = context.output_dir / "checkpoint"
        out.mkdir()
        (out / "weights.safetensors").write_bytes(b"trained")
        return EngineResult(optimizer_steps=1001, epochs=1.0)  # > max_steps 1000
    result, _ = run(tmp_path, overrun, trials=1)
    assert result["receipts"][0]["status"] == "failed"
    assert result["receipts"][0]["checkpoint_sha256"] is None


def test_injected_environment_refusal_stops_before_any_run_slot(tmp_path):
    plan, permit = stage(tmp_path, 1)

    def refuse(environment):
        raise ValueError("package_environment_mismatch")
    engine = Engine(oom)
    with pytest.raises(ValueError, match="package_environment_mismatch"):
        execute_training(plan, permit, root=tmp_path, engine=engine, clock=lambda: AT, environment_check=refuse)
    assert engine.calls == 0 and not (tmp_path / "runs").exists()


def test_default_runs_real_environment_check(tmp_path):
    # Pinned python "0.0.0-pinned" can never match the running interpreter, so the
    # default (no injection) real probe must refuse before creating a run slot.
    plan, permit = stage(tmp_path, 1)
    engine = Engine(oom)
    with pytest.raises(ValueError, match="python_environment_mismatch"):
        execute_training(plan, permit, root=tmp_path, engine=engine, clock=lambda: AT)
    assert engine.calls == 0 and not (tmp_path / "runs").exists()


def test_seam_does_not_bypass_artifact_pins(tmp_path):
    plan, permit = stage(tmp_path, 1)
    (tmp_path / "staged/dev.json").write_text("{}", encoding="utf-8")  # tamper after pinning
    with pytest.raises(ValueError, match="local_artifact_hash_mismatch"):
        execute_training(plan, permit, root=tmp_path, engine=Engine(oom), clock=lambda: AT,
                         environment_check=accept_env)
