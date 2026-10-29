"""Public launch-join counterexamples; no real authorization or execution."""

import warnings

import pytest

from m7.experiment.authorization import EvaluationAuthorization, ReceiptAuthority
from m7.experiment.models import commitment
from m7.experiment.readiness import ExperimentReadiness, assess_readiness
from m7.training.launch_bundle import WorkerLaunchBundle

from .scenario import edition


MARKER = "public-only-launch-join-warning-marker"


def public_bound_declarations():
    # Structurally coherent fictional declarations, never authenticated authority.
    lock = edition()
    packet = EvaluationAuthorization(
        authorization_id="public-launch-diagnostics",
        edition_id=lock.edition_id,
        run_id=lock.run_id,
        plan_sha256=lock.plan_sha256,
        corpus_manifest_sha256=lock.corpus_manifest_sha256,
        population_sha256=commitment([row.model_dump(mode="json") for row in lock.population]),
        selection_lock_sha256=lock.selection_lock_sha256,
        custody_release_sha256=lock.custody_release_sha256,
        independent_audit_sha256=lock.independent_audit_sha256,
        adoption_policy_sha256=commitment(lock.adoption_policy.model_dump(mode="json")),
        timing_plan_sha256=lock.timing_plan_sha256,
        arm_pins=lock.arm_pins,
        issued_at="2020-01-01T00:00:00Z",
        expires_at=lock.expires_at,
        allowed_action="open_or_resume_locked_evaluation",
    )
    lock = lock.model_copy(
        update={"execution_authorization_sha256": commitment(packet.model_dump(mode="json"))}
    )
    ReceiptAuthority.validate_binding(packet, lock)
    return lock, packet


def malformed_launch(field, method):
    values = dict(
        campaign=None, campaign_sha256="a" * 64, profile_sha256="b" * 64, bootstraps={}, memberships={}
    )
    changes = {
        "campaign": {"campaign": [MARKER]},
        "bootstraps": {"bootstraps": {"regex": MARKER}},
        "memberships": {"memberships": {"regex": MARKER}},
        "campaign_sha256": {"campaign_sha256": [MARKER]},
    }[field]
    if method == "construct":
        return WorkerLaunchBundle.model_construct(**(values | changes))
    return WorkerLaunchBundle.model_construct(**values).model_copy(update=changes)


def assert_held(report):
    assert report.status == "NOT_READY"
    assert report.actual_model_execution is False
    assert report.execution_allowed is False
    assert report.product_acceptance is False
    assert report.held_decisions == ("H1", "H2", "H3", "H4", "H5", "H6")


@pytest.mark.parametrize("method", ("copy", "construct"))
@pytest.mark.parametrize("field", ("campaign", "bootstraps", "memberships", "campaign_sha256"))
def test_reachable_malformed_launch_join_has_no_source_bearing_diagnostics(field, method, capsys):
    # what_bug_this_catches: the readiness adapter can delegate to a downstream
    # serializer which emits rejected values even though the output is invalid.
    lock, packet = public_bound_declarations()
    bundle = malformed_launch(field, method)
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        report = assess_readiness(edition=lock, authorization=packet, launch_bundle=bundle)
    assert_held(report)
    states = {row.name: row.state for row in report.checks}
    assert states["preregistration"] == "shape_valid"
    assert states["campaign_binding"] == "invalid"
    assert MARKER not in report.model_dump_json()
    assert all(MARKER not in str(item.message) for item in emitted)
    captured = capsys.readouterr()
    assert MARKER not in captured.err + captured.out


def test_public_bound_declarations_remain_shape_only_without_launch():
    lock, _ = public_bound_declarations()
    report = assess_readiness(edition=lock)
    assert_held(report)
    assert next(row for row in report.checks if row.name == "preregistration").state == "shape_valid"
    assert next(row for row in report.checks if row.name == "campaign_binding").state == "missing"
    assert ExperimentReadiness.model_validate_json(report.model_dump_json()) == report


def test_malformed_launch_refusal_keeps_unrelated_warning_filters():
    lock, packet = public_bound_declarations()
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        filters_before = list(warnings.filters)
        warnings.warn("public unrelated launch warning before", UserWarning)
        report = assess_readiness(
            edition=lock, authorization=packet, launch_bundle=malformed_launch("campaign", "copy")
        )
        assert warnings.filters == filters_before
        warnings.warn("public unrelated launch warning after", UserWarning)
    assert_held(report)
    assert [str(item.message) for item in emitted] == [
        "public unrelated launch warning before",
        "public unrelated launch warning after",
    ]
