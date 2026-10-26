"""Frozen synthetic malformed-producer regressions for D11-RV2-WARNING-02."""

import warnings

import pytest

from m7.experiment.readiness import assess_readiness
from m7.providers.readiness import ProviderArmFact, ProviderFacts, assess_provider_facts
from m7.training.readiness import TrainingArtifactFacts, inspect_training_readiness


MARKER = "public-only-nested-producer-marker"


def malformed_provider(case, method):
    report = assess_provider_facts(run_id="public-producer-diagnostics")
    changes = {
        "arms_list": {"arms": [MARKER]},
        "arms_tuple": {"arms": (MARKER, *report.arms[1:])},
        "nested_digest": {
            "arms": (report.arms[0].model_copy(update={"configuration_sha256": [MARKER]}), *report.arms[1:])
        },
        "nested_status": {
            "arms": (
                ProviderArmFact.model_construct(arm="base", status=[MARKER], reason="missing_declarations"),
                *report.arms[1:],
            )
        },
    }[case]
    if method == "copy":
        return report.model_copy(update=changes)
    values = {name: getattr(report, name) for name in type(report).model_fields}
    return ProviderFacts.model_construct(**(values | changes))


def malformed_training(case, method):
    report = inspect_training_readiness()
    changes = {
        "diagnostics_list": {"diagnostics": [MARKER]},
        "diagnostics_nested": {"diagnostics": ({"source": MARKER},)},
        "input_status_list": {"input_status": [MARKER]},
        "digest_list": {"plan_sha256": [MARKER]},
    }[case]
    if method == "copy":
        return report.model_copy(update=changes)
    values = {name: getattr(report, name) for name in type(report).model_fields}
    return TrainingArtifactFacts.model_construct(**(values | changes))


def assert_safe_invalid(report, producer, emitted):
    assert report.status == "NOT_READY"
    assert report.held_decisions == ("H1", "H2", "H3", "H4", "H5", "H6")
    assert report.actual_model_execution is False
    assert report.execution_allowed is False
    assert report.product_acceptance is False
    affected = ("providers",) if producer == "provider" else ("training", "artifacts")
    assert all(next(row for row in report.checks if row.name == name).state == "invalid" for name in affected)
    assert MARKER not in report.model_dump_json()
    assert all(MARKER not in str(item.message) for item in emitted)


@pytest.mark.parametrize("method", ("copy", "construct"))
@pytest.mark.parametrize("case", ("arms_list", "arms_tuple", "nested_digest", "nested_status"))
def test_malformed_provider_nested_values_do_not_escape_through_diagnostics(case, method):
    # what_bug_this_catches: refusal after a warning still discloses rejected inputs.
    forged = malformed_provider(case, method)
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        report = assess_readiness(provider_facts=forged)
    assert_safe_invalid(report, "provider", emitted)


@pytest.mark.parametrize("method", ("copy", "construct"))
@pytest.mark.parametrize(
    "case", ("diagnostics_list", "diagnostics_nested", "input_status_list", "digest_list")
)
def test_malformed_training_nested_values_do_not_escape_through_diagnostics(case, method):
    # what_bug_this_catches: the parallel training adapter shares the warning boundary.
    forged = malformed_training(case, method)
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        report = assess_readiness(training_facts=forged)
    assert_safe_invalid(report, "training", emitted)


@pytest.mark.parametrize("producer", ("provider", "training"))
def test_plain_noncanonical_producer_dict_is_invalid(producer):
    values = (
        {"provider_facts": {"source": MARKER}}
        if producer == "provider"
        else {"training_facts": {"source": MARKER}}
    )
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        report = assess_readiness(**values)
    assert_safe_invalid(report, producer, emitted)


def test_rejecting_malformed_producers_keeps_unrelated_warning_filters():
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        filters_before = list(warnings.filters)
        warnings.warn("public unrelated warning before", UserWarning)
        report = assess_readiness(provider_facts=malformed_provider("arms_tuple", "copy"))
        assert warnings.filters == filters_before
        warnings.warn("public unrelated warning after", UserWarning)
    assert_safe_invalid(report, "provider", emitted)
    messages = [str(item.message) for item in emitted]
    assert messages == ["public unrelated warning before", "public unrelated warning after"]
