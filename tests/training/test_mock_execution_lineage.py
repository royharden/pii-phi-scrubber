"""W2 evidence_kind=mock: injected training must never masquerade as actual work."""
import json

import pytest

from m7.training.executor import EngineResult, TrainingCancelled, TrainingOOM, execute_training
from m7.training.validation import validate_training_receipt

from .test_executor_failures import AT, Engine, accept_env, stage
from .test_recovery import recover


def behaviour(status):
    def run(context):
        if status == "completed":
            checkpoint = context.output_dir / "checkpoint"
            checkpoint.mkdir()
            (checkpoint / "weights.safetensors").write_bytes(b"PUBLIC-MOCK-NOT-A-TRAINED-CHECKPOINT")
            return EngineResult(optimizer_steps=1, epochs=1.0)
        if status == "oom":
            raise TrainingOOM()
        if status == "cancelled":
            raise TrainingCancelled()
        raise RuntimeError("PUBLIC-MOCK-ENGINE-ERROR")
    return run


@pytest.mark.parametrize("status", ["completed", "failed", "oom", "cancelled"])
def test_injected_engine_outcomes_stay_mock_and_cannot_satisfy_actual_reader(tmp_path, status):
    # Bug caught: execute_training previously hardcoded actual_training even for
    # an injected fake engine/environment, laundering a mock checkpoint as real.
    plan, permit = stage(tmp_path, 1)
    engine = Engine(behaviour(status))
    result = execute_training(plan, permit, root=tmp_path, engine=engine,
                              clock=lambda: AT, environment_check=accept_env)
    receipt = result["receipts"][0]
    assert engine.calls == 1 and receipt["status"] == status
    assert receipt["execution_kind"] == "mock" and receipt["m7_02_accepted"] is False
    assert result["runtime_acceptance"] is False
    assert "PUBLIC-MOCK-ENGINE-ERROR" not in json.dumps(result)
    persisted = json.loads((tmp_path / "runs/ed-1/t1/receipt.json").read_text(encoding="utf-8"))
    assert persisted["execution_kind"] == "mock"
    if status == "completed":
        with pytest.raises(ValueError):
            validate_training_receipt(receipt, plan, permit)


def test_mock_recovery_preserves_kind_original_receipt_and_unknown_liability(tmp_path):
    plan, permit = stage(tmp_path, 1)
    engine = Engine(behaviour("oom"))
    execute_training(plan, permit, root=tmp_path, engine=engine,
                     clock=lambda: AT, environment_check=accept_env)
    original_path = tmp_path / "runs/ed-1/t1/receipt.json"
    original = original_path.read_bytes()
    report = recover(tmp_path, plan, permit)
    assert report["outcomes"][0]["outcome"] == "original_oom"
    assert report["accounting"]["unresolved_liability_micros"] == 100
    assert original_path.read_bytes() == original and engine.calls == 1
    assert json.loads(original)["execution_kind"] == "mock"
