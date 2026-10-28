"""Public fake checkpoints cannot become selected/exported actual training."""
import hashlib
import json

import pytest

from m7.contracts import Span, make_record
from m7.training.checkpoints import export_checkpoint, verify_checkpoint_export
from m7.training.executor import execute_training
from m7.training.selection import DevRecord, select_checkpoint
from m7.training.selection_models import DevSelectionPolicy, SelectionRule
from m7.training.validation import digest

from .test_executor_failures import AT, Engine, accept_env, stage
from .test_mock_execution_lineage import behaviour


def completed_mock(root, *, dev_blocks=1):
    plan, permit = stage(root, 1)
    rows = []
    for i in range(dev_blocks):
        record = make_record(f"acct=A333 public-row-{i}", f"dev-{i}", split_id="dev")
        rows.append(DevRecord(record, (Span(start=5, end=9, label="ACCOUNT_ID"),),
                              f"public-block-{i}", "normal"))
    path = root / "staged/dev.json"
    path.write_text(json.dumps({
        "schema_version": "TrainingDataset/v1", "split": "dev",
        "records": [{"record": row.record.model_dump(mode="json"),
                     "gold": [span.model_dump(mode="json", exclude={"confidence"})
                              for span in row.gold]} for row in rows],
    }), encoding="utf-8")
    plan["artifacts"]["dev"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    # Keep the public dummy custody/license packet pins coherent with the new dev population.
    for key in ("license_packet", "custody_audit"):
        packet_path = root / plan["artifacts"][key]["path"]
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        if key == "license_packet":
            packet["artifacts"]["dev"] = plan["artifacts"]["dev"]["sha256"]
        else:
            packet["dev_sha256"] = plan["artifacts"]["dev"]["sha256"]
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        pin = hashlib.sha256(packet_path.read_bytes()).hexdigest()
        plan["artifacts"][key]["sha256"] = pin
        permit[key + "_sha256"] = pin
    permit["plan_sha256"] = digest(plan)
    run = execute_training(plan, permit, root=root, engine=Engine(behaviour("completed")),
                           clock=lambda: AT, environment_check=accept_env)
    assert run["receipts"][0]["execution_kind"] == "mock"
    return plan, permit, rows, run


@pytest.mark.parametrize("boundary", ["export", "verify_export"])
def test_completed_mock_cannot_enter_checkpoint_export_or_verification(tmp_path, boundary):
    # Regression: a completed injected-engine checkpoint must be refused before
    # authentication, base-config access, artifact inspection, copying or output.
    plan, permit, _, run = completed_mock(tmp_path)
    receipt = run["receipts"][0]
    calls = []
    before = {p.relative_to(tmp_path).as_posix(): p.read_bytes()
              for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="^actual_training_required$"):
        if boundary == "export":
            export_checkpoint(receipt, plan, permit, staging_root=tmp_path,
                              destination=tmp_path / "public-export", base_config=None,
                              verify_receipt=lambda *args: calls.append(args) or True)
        else:
            verify_checkpoint_export({}, receipt, plan, permit)
    assert calls == [] and not (tmp_path / "public-export").exists()
    assert before == {p.relative_to(tmp_path).as_posix(): p.read_bytes()
                      for p in tmp_path.rglob("*") if p.is_file()}


def test_completed_mock_cannot_enter_development_checkpoint_selection(tmp_path):
    # Reach the mock receipt boundary with the required20 public dev blocks,
    # valid staged pins and policy; refusal must precede checkpoint/evaluation trust.
    plan, permit, rows, run = completed_mock(tmp_path, dev_blocks=20)
    policy = DevSelectionPolicy(
        edition_id="ed-1", experiment_plan_sha256="1" * 64,
        training_plan_sha256=digest(plan), dev_sha256=plan["artifacts"]["dev"]["sha256"],
        rule=SelectionRule(thresholds=(0.5,), bootstrap_seed=1),
        registered_at="2026-01-01T00:00:00Z")
    calls = []
    with pytest.raises(ValueError, match="^actual_training_required$"):
        select_checkpoint(rows, [], policy=policy, training_plan=plan, training_permit=permit,
                          trial_receipts=run["receipts"], checkpoint_exports=[], training_run=run,
                          training_root=tmp_path,
                          verify_receipt=lambda kind, sha: calls.append(kind) or True,
                          clock=lambda: AT)
    assert calls == ["development_population", "dev_selection_policy"]
