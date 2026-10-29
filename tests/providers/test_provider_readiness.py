"""W2 readiness facts are pure declarations, never permission or model evidence."""
import json

import pytest

from m7.providers.contracts import ExecutionPermit, config_digest
from m7.providers.readiness import ProviderFacts, assess_provider_facts

from ..detectors.test_attempts_registry import attempt_policy
from .local_mock_fixtures import RUN, local_config, permit_for


def declarations(tmp_path):
    config = local_config(tmp_path / "public-artifacts")
    policy = attempt_policy()
    permit = permit_for(config).model_copy(update={"attempt_policy_sha256": config_digest(policy)})
    return {"base": config}, {"base": permit}, {"base": policy}


def row(facts, arm="base"):
    return next(value for value in facts.arms if value.arm == arm)


def test_empty_assessment_is_missing_and_no_effects(monkeypatch):
    effects = []

    def forbidden(*args, **kwargs):
        effects.append(True)
        raise AssertionError("readiness must not activate anything")

    monkeypatch.setattr("m7.providers.contracts.verify_artifacts", forbidden)
    monkeypatch.setattr("m7.providers.local.GlinerBackend", forbidden)
    monkeypatch.setattr("m7.providers.worker_factory.FixedWorkerFactory.__call__", forbidden)
    facts = assess_provider_facts(run_id=RUN)
    assert [value.arm for value in facts.arms] == ["base", "finetuned", "frontier"]
    assert all(value.status == "missing" and value.reason == "missing_declarations" for value in facts.arms)
    assert facts.execution_allowed is False and facts.actual_model_execution is False and effects == []


def test_shape_valid_with_missing_staging_does_not_probe_or_authorize(tmp_path, monkeypatch):
    configs, permits, policies = declarations(tmp_path)
    config = configs["base"].model_copy(update={"artifact_root": str(tmp_path / "not-acquired")})
    configs["base"] = config
    permits["base"] = permit_for(config).model_copy(update={"attempt_policy_sha256": config_digest(policies["base"])})
    effects = []

    def forbidden(*args, **kwargs):
        effects.append(True)
        raise AssertionError("declarations cannot inspect staged model bytes")

    monkeypatch.setattr("m7.providers.contracts.verify_artifacts", forbidden)
    monkeypatch.setattr("m7.providers.local.GlinerBackend", forbidden)
    facts = assess_provider_facts(configs, permits, policies, run_id=RUN)
    assert row(facts).status == "shape_valid" and row(facts).reason == "declarations_only"
    assert row(facts).artifact_sha256 == config.weights_sha256
    assert facts.execution_allowed is False and facts.actual_model_execution is False and effects == []
    assert not (tmp_path / "not-acquired").exists()


@pytest.mark.parametrize("missing", ["config", "permit", "policy"])
def test_partial_declaration_is_invalid_not_ready_or_silently_absent(tmp_path, missing):
    configs, permits, policies = declarations(tmp_path)
    {"config": configs, "permit": permits, "policy": policies}[missing].clear()
    facts = assess_provider_facts(configs, permits, policies, run_id=RUN)
    assert row(facts).status == "invalid" and row(facts).reason == "permit_required"
    assert row(facts).configuration_sha256 is None and row(facts).artifact_sha256 is None


@pytest.mark.parametrize("drift", ["expired_permit", "policy_not_bound"])
def test_current_bound_declaration_is_required(tmp_path, drift):
    configs, permits, policies = declarations(tmp_path)
    if drift == "expired_permit":
        permits["base"] = permits["base"].model_copy(update={"expires_at": "2020-01-02T00:00:00Z"})
    else:
        policies["base"] = policies["base"].model_copy(update={"max_records": 9})
    facts = assess_provider_facts(configs, permits, policies, run_id=RUN)
    assert row(facts).status == "invalid" and row(facts).reason == "permit_required"


def test_fine_parity_failure_is_value_free_invalid_fact(tmp_path):
    configs, permits, policies = declarations(tmp_path)
    fine = configs["base"].model_copy(update={"arm": "finetuned", "model_id": "public-mock-fine",
                                               "training_receipt_sha256": "4" * 64,
                                               "tokenizer_sha256": "5" * 64})
    configs["finetuned"] = fine
    policies["finetuned"] = policies["base"]
    permits["finetuned"] = permit_for(fine).model_copy(
        update={"attempt_policy_sha256": config_digest(policies["finetuned"])})
    facts = assess_provider_facts(configs, permits, policies, run_id=RUN)
    assert row(facts).status == "shape_valid"
    assert row(facts, "finetuned").status == "invalid"
    assert row(facts, "finetuned").reason == "permit_required"
    assert facts.execution_allowed is False


@pytest.mark.parametrize("fault", ["invalid_run", "unknown_arm"])
def test_malformed_top_level_declarations_use_fixed_error(fault):
    with pytest.raises(ValueError, match="^invalid_provider_declarations$"):
        assess_provider_facts({"unknown": "PUBLIC-SENTINEL"} if fault == "unknown_arm" else None,
                              run_id="PUBLIC SENTINEL" if fault == "invalid_run" else RUN)


def test_internal_exception_never_becomes_readiness_text(tmp_path, monkeypatch):
    configs, permits, policies = declarations(tmp_path)

    def broken(*args, **kwargs):
        raise RuntimeError("PUBLIC-EXCEPTION-SENTINEL")

    monkeypatch.setattr(ExecutionPermit, "check", broken)
    facts = assess_provider_facts(configs, permits, policies, run_id=RUN)
    assert row(facts).status == "invalid" and row(facts).reason == "invalid_output"
    assert "PUBLIC-EXCEPTION-SENTINEL" not in facts.model_dump_json()


@pytest.mark.parametrize("field", ["actual_model_execution", "execution_allowed", "product_acceptance"])
def test_wire_cannot_promote_declarations_to_execution_or_acceptance(field):
    wire = assess_provider_facts(run_id=RUN).model_dump(mode="json")
    wire[field] = True
    with pytest.raises(ValueError):
        ProviderFacts.model_validate_json(json.dumps(wire))


def test_wire_roundtrip_excludes_paths_versions_and_model_names(tmp_path):
    configs, permits, policies = declarations(tmp_path)
    facts = assess_provider_facts(configs, permits, policies, run_id=RUN)
    wire = facts.model_dump_json()
    assert ProviderFacts.model_validate_json(wire) == facts
    assert str(tmp_path) not in wire and "public-mock-base" not in wire and "mock-version" not in wire
    assert facts.evidence_kind == "readiness"
