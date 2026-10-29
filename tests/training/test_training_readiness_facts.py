"""W2 readiness projection controls; local fake bytes never establish training."""
import json

import pytest

from m7.training.readiness import TrainingArtifactFacts, inspect_training_readiness

from ..providers.local_mock_fixtures import local_config
from .test_executor_failures import AT, stage


@pytest.mark.parametrize("absence", ["plan", "permit", "approval"])
def test_missing_or_unapproved_declaration_precedes_all_artifact_effects(tmp_path, monkeypatch, absence):
    plan, permit = stage(tmp_path, 1)
    expected = {"plan": "missing_plan", "permit": "missing_permit", "approval": "invalid"}[absence]
    if absence == "plan":
        plan = None
    elif absence == "permit":
        permit = None
    else:
        permit["approved"] = False
    effects = []

    def forbidden(*args, **kwargs):
        effects.append(True)
        raise AssertionError("readiness touched an effect before declaration checks")

    monkeypatch.setattr("m7.training.readiness.inspect_artifacts", forbidden)
    monkeypatch.setattr("m7.training.readiness.no_links", forbidden)
    monkeypatch.setattr("m7.training.executor.execute_training", forbidden)
    facts = inspect_training_readiness(plan, permit, staging_root=tmp_path, at=AT)
    assert facts.input_status == expected and facts.artifact_status == "not_inspected"
    assert effects == [] and facts.execution_allowed_now is False
    assert facts.plan_sha256 is None and facts.permit_sha256 is None


@pytest.mark.parametrize("location,reason", [("unsupplied", "artifact_root_missing"),
                                            ("nonexistent", "local_artifact_missing")])
def test_missing_artifacts_are_explicit_and_no_directory_is_created(tmp_path, location, reason):
    plan, permit = stage(tmp_path, 1)
    missing = tmp_path / "PUBLIC-NOT-ACQUIRED"
    facts = inspect_training_readiness(plan, permit,
                                      staging_root=None if location == "unsupplied" else missing, at=AT)
    assert facts.input_status == "validated" and facts.artifact_status == "missing"
    assert reason in facts.diagnostics and facts.environment_status == "not_checked"
    assert not missing.exists() and not (tmp_path / "runs").exists()
    assert "PUBLIC-NOT-ACQUIRED" not in facts.model_dump_json()


def test_local_artifact_failure_is_a_fixed_value_free_fact(tmp_path):
    plan, permit = stage(tmp_path, 1)
    (tmp_path / "staged/model/model.safetensors").write_bytes(b"PUBLIC-TAMPERED-FAKE")
    facts = inspect_training_readiness(plan, permit, staging_root=tmp_path, at=AT)
    assert facts.artifact_status == "invalid" and facts.diagnostics == ("local_artifact_invalid",)
    assert facts.environment_status == "not_checked"
    assert "PUBLIC-TAMPERED-FAKE" not in facts.model_dump_json()
    assert not (tmp_path / "runs").exists() and not (tmp_path / "accounting").exists()


@pytest.mark.parametrize("environment", ["matched", "unavailable", "mismatch"])
def test_verified_mock_files_and_environment_facts_never_allow_training(tmp_path, monkeypatch, environment):
    plan, permit = stage(tmp_path, 1)
    calls = []

    def check(metadata):
        calls.append(metadata)
        if environment != "matched":
            raise ValueError("training_dependency_unavailable" if environment == "unavailable"
                             else "PUBLIC-ENVIRONMENT-SENTINEL")

    monkeypatch.setattr("m7.training.readiness.check_installed_environment", check)
    before = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")}
    facts = inspect_training_readiness(plan, permit, staging_root=tmp_path, at=AT)
    assert facts.input_status == "validated" and facts.artifact_status == "verified"
    assert facts.environment_status == environment and len(calls) == 1
    assert facts.training_status == "not_run" and facts.actual_training_observed is False
    assert facts.execution_allowed_now is False and facts.m7_02_accepted is False
    assert "PUBLIC-ENVIRONMENT-SENTINEL" not in facts.model_dump_json()
    assert {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")} == before


@pytest.mark.parametrize("compatible", [True, False])
def test_parity_is_only_a_declaration_and_never_probes_artifact_roots(tmp_path, monkeypatch, compatible):
    base = local_config(tmp_path / "public-pair").model_copy(
        update={"artifact_root": str(tmp_path / "PUBLIC-NOT-ACQUIRED")})
    fine = base.model_copy(update={"arm": "finetuned", "model_id": "public-mock-fine",
                                   "training_receipt_sha256": "4" * 64})
    if not compatible:
        fine = fine.model_copy(update={"tokenizer_sha256": "5" * 64})
    probes = []

    def forbidden(*args, **kwargs):
        probes.append(True)
        raise AssertionError("declaration-only parity touched staging")

    monkeypatch.setattr("m7.training.readiness.inspect_artifacts", forbidden)
    monkeypatch.setattr("m7.training.readiness.no_links", forbidden)
    facts = inspect_training_readiness(base=base, finetuned=fine)
    assert facts.parity_status == ("declared_compatible" if compatible else "invalid")
    assert facts.input_status == "missing_plan" and probes == []
    assert facts.execution_allowed_now is False


@pytest.mark.parametrize("field", ["actual_training_observed", "execution_allowed_now", "m7_02_accepted"])
def test_fact_wire_cannot_claim_actual_training_or_authority(field):
    wire = inspect_training_readiness().model_dump(mode="json")
    wire[field] = True
    with pytest.raises(ValueError):
        TrainingArtifactFacts.model_validate_json(json.dumps(wire))


def test_default_fact_wire_roundtrips_without_turning_missing_into_verified():
    facts = inspect_training_readiness()
    assert TrainingArtifactFacts.model_validate_json(facts.model_dump_json()) == facts
    assert facts.evidence_kind == "readiness" and facts.input_status == "missing_plan"
    assert facts.artifact_status == "not_inspected" and facts.environment_status == "not_checked"
    assert facts.diagnostics == ("training_plan_missing",)
