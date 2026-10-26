"""Independent real producer-wire joins with public declaration-only metadata."""

import warnings

import pytest

from m7.experiment.readiness import ComponentFact, ExperimentReadiness, assess_readiness
from m7.providers.readiness import ProviderArmFact, ProviderFacts, assess_provider_facts
from m7.training.readiness import TrainingArtifactFacts, inspect_training_readiness


def check(report, name):
    return next(row for row in report.checks if row.name == name)


def assert_held(report):
    assert report.status == "NOT_READY"
    assert report.actual_model_execution is False
    assert report.execution_allowed is False
    assert report.product_acceptance is False
    assert report.held_decisions == ("H1", "H2", "H3", "H4", "H5", "H6")


def declared_providers():
    return ProviderFacts(
        arms=tuple(
            ProviderArmFact(
                arm=arm,
                status="shape_valid",
                reason="declarations_only",
                configuration_sha256="a" * 64,
                artifact_sha256="b" * 64,
            )
            for arm in ("base", "finetuned", "frontier")
        )
    )


def declared_training():
    # Deliberately structural assertions, never an actual receipt or model run.
    return TrainingArtifactFacts(
        input_status="validated",
        artifact_status="verified",
        environment_status="matched",
        parity_status="declared_compatible",
        plan_sha256="c" * 64,
        permit_sha256="d" * 64,
        base_configuration_sha256="e" * 64,
        finetuned_configuration_sha256="f" * 64,
    )


def test_actual_default_producer_functions_join_without_promoting_missing_evidence():
    providers = assess_provider_facts(run_id="public-w2-join")
    training = inspect_training_readiness()
    result = assess_readiness(provider_facts=providers, training_facts=training)
    assert_held(result)
    assert check(result, "providers").state == "missing"
    assert check(result, "training").state == "missing"
    assert check(result, "artifacts").state == "held"
    assert result.cost.economic_total_micros is None
    assert ExperimentReadiness.model_validate_json(result.model_dump_json()) == result


def test_complete_canonical_declarations_are_shape_only_and_never_actual():
    result = assess_readiness(provider_facts=declared_providers(), training_facts=declared_training())
    assert_held(result)
    for name in ("providers", "training", "artifacts"):
        row = check(result, name)
        assert (row.state, row.reason) == ("shape_valid", "shape_only_not_authenticated")
        assert row.evidence_sha256 is not None
    assert check(result, "campaign_binding").state == "missing"
    assert result.accounting == ()


@pytest.mark.parametrize("field", ("actual_model_execution", "execution_allowed"))
def test_forged_provider_execution_claims_become_invalid(field):
    forged = declared_providers().model_copy(update={field: True})
    result = assess_readiness(provider_facts=forged)
    assert_held(result)
    assert check(result, "providers").state == "invalid"


@pytest.mark.parametrize("field", ("actual_training_observed", "execution_allowed_now", "m7_02_accepted"))
def test_forged_training_execution_or_acceptance_claims_become_invalid(field):
    forged = declared_training().model_copy(update={field: True})
    result = assess_readiness(training_facts=forged)
    assert_held(result)
    assert check(result, "artifacts").state == "invalid"
    assert check(result, "training").state == "invalid"


@pytest.mark.parametrize("producer", ("providers", "training"))
def test_generic_facts_cannot_override_canonical_producer_evidence(producer):
    arguments = (
        {"provider_facts": declared_providers()}
        if producer == "providers"
        else {"training_facts": declared_training()}
    )
    with pytest.raises(ValueError, match="duplicate_readiness_component"):
        assess_readiness(
            component_facts=(
                ComponentFact(component=producer, state="shape_valid", evidence_sha256="a" * 64),
            ),
            **arguments,
        )


def test_malformed_provider_model_is_refused_without_source_bearing_warning():
    # what_bug_this_catches: the producer adapter must not leak rejected values
    # through serializer warnings before replacing them with a fixed invalid state.
    marker = "public-only-provider-join-marker"
    forged = declared_providers().model_copy(update={"arms": [marker]})
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        result = assess_readiness(provider_facts=forged)
    assert_held(result)
    assert check(result, "providers").state == "invalid"
    assert marker not in result.model_dump_json()
    assert all(marker not in str(item.message) for item in emitted)
