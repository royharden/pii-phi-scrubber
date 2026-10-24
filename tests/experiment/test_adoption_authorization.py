"""Locked adoption rule, evaluation authorization, released reader and activation gates.

Hand-built value-free inputs; expected decisions follow the plan's adoption rule:
every class floor on the total set, positive paired macro-F1 lower bound, no
increased residual leak, zero structure failures, full accounting, closed edition
and reconciled known cost. Passing yields only a candidate, never product acceptance.
"""
from datetime import datetime, timedelta, timezone

import pytest

from m7.experiment.activation import OperatorHost, policy_from_selection_lock
from m7.experiment.adoption import AdoptionPolicy, ClassFloor, adoption_report
from m7.experiment.authorization import EvaluationAuthorization, ReceiptAuthority
from m7.experiment.models import ArmPin, LockedEdition, PopulationMember, commitment
from m7.experiment.released import read_released_channels

LABELS = ("NAME", "EMAIL", "PHONE", "ACCOUNT_ID")
ARMS = ("regex", "frontier", "base", "finetuned")


def h(c):
    return c * 64


def policy():
    return AdoptionPolicy(per_class=tuple(ClassFloor(label=label, recall_minimum=0.95, precision_minimum=0.90,
                                                     recall_lower95_minimum=0.90) for label in LABELS),
                          development_justification_sha256=h("1"))


# ------------------------------------------------------------------ adoption rule

def pick(value, label, default):
    """A scalar applies to every class; a dict overrides named classes only."""
    return value.get(label, default) if isinstance(value, dict) else value


def arm_row(arm, *, recall=0.96, precision=0.95, lower=0.92, residual=0.01, n=10, status="measured"):
    per_class = {label: {"recall": {"value": pick(recall, label, 0.96)}, "precision": {"value": precision}}
                 for label in LABELS}
    intervals = {"per_class": {label: {"recall": {"interval": None if pick(lower, label, 0.92) is None
                                                  else [pick(lower, label, 0.92), 0.99]}}
                               for label in LABELS}}
    return {"arm": arm, "measurement_status": status, "attempted_N": n, "unattempted_N": 0,
            "answered_N": n, "error_N": 0,
            "metrics": {"per_class": per_class, "residual_sensitive_codepoints": {"value": residual},
                        "structure_failures": 0},
            "intervals": intervals}


def bundle(*, fine=None, base_residual=0.05, paired_lower=0.05, cost=None, state="closed", status="measured"):
    arms = [arm_row(a, status=status, residual=base_residual) for a in ("regex", "frontier", "base")]
    arms.append(fine or arm_row("finetuned", status=status))
    return {"arms": arms, "corpus_N": 10, "edition_state": state,
            "paired_fine_minus_base": {"interval": [paired_lower, 0.20]},
            "cost": cost if cost is not None else {"status": "known", "unknown_attempts": 0, "over_cap": False,
                                                   "scope_complete": True, "currency": "USD"}}


def test_candidate_meeting_every_gate_is_candidate_only_never_product_acceptance():
    r = adoption_report(bundle(), policy())
    # recall .96 >= .95, precision .95 >= .90, lower .92 >= .90 for all four classes.
    assert all(row["passed"] is True for row in r["per_class"])
    assert all(v is True for v in r["gates"].values())
    assert r["status"] == "candidate_only" and r["recommendation"] == "candidate_for_independent_review"
    assert r["product_acceptance"] is False


def test_exact_floor_values_pass_inclusive():
    r = adoption_report(bundle(fine=arm_row("finetuned", recall=0.95, precision=0.90, lower=0.90)), policy())
    assert all(row["passed"] is True for row in r["per_class"]) and r["status"] == "candidate_only"


def test_one_class_below_floor_is_no_deploy():
    # PHONE recall 0.94 < 0.95 while the other three pass: macro wins cannot excuse a weak class.
    r = adoption_report(bundle(fine=arm_row("finetuned", recall={"PHONE": 0.94})), policy())
    passed = {row["label"]: row["passed"] for row in r["per_class"]}
    assert passed == {"NAME": True, "EMAIL": True, "PHONE": False, "ACCOUNT_ID": True}
    assert r["gates"]["all_classes_meet_total_set_floors"] is False
    assert r["status"] == "no_deploy" and r["recommendation"] == "retain_benchmark_no_deployment"


def test_insufficient_interval_is_not_evaluated_and_never_deploys():
    r = adoption_report(bundle(fine=arm_row("finetuned", lower={"EMAIL": None})), policy())
    email = next(row for row in r["per_class"] if row["label"] == "EMAIL")
    assert email["passed"] is None and email["recall_lower95"] is None
    assert r["gates"]["all_classes_meet_total_set_floors"] is None
    assert r["status"] == "no_deploy" and r["improvement_supported"] is False


@pytest.mark.parametrize("cost", [
    {"status": "partially_known", "unknown_attempts": 0, "over_cap": False, "scope_complete": True, "currency": "USD"},
    {"status": "known", "unknown_attempts": 1, "over_cap": False, "scope_complete": True, "currency": "USD"},
    {"status": "known", "unknown_attempts": 0, "over_cap": True, "scope_complete": True, "currency": "USD"},
    {"status": "known", "unknown_attempts": 0, "over_cap": False, "scope_complete": False, "currency": "USD"},
    {},
])
def test_unknown_or_unreconciled_cost_fails_cost_gate(cost):
    r = adoption_report(bundle(cost=cost), policy())
    assert r["gates"]["cost_reconciled"] is False and r["status"] == "no_deploy"


def test_paired_lower_bound_must_be_strictly_positive():
    r = adoption_report(bundle(paired_lower=0.0), policy())
    assert r["gates"]["positive_paired_macro_f1"] is False and r["status"] == "no_deploy"


def test_increased_residual_leak_is_no_deploy():
    # fine 0.01 vs base 0.005: fine leaks more.
    r = adoption_report(bundle(base_residual=0.005), policy())
    assert r["gates"]["no_increased_residual_leak"] is False and r["status"] == "no_deploy"


def test_open_edition_is_no_deploy():
    r = adoption_report(bundle(state="open"), policy())
    assert r["gates"]["closed_edition"] is False and r["status"] == "no_deploy"


def test_all_unrun_arms_are_not_evaluated():
    r = adoption_report(bundle(status="not_measured"), policy())
    assert r["status"] == "not_evaluated" and r["product_acceptance"] is False


def test_policy_requires_all_four_ordered_classes():
    with pytest.raises(ValueError):
        AdoptionPolicy(per_class=tuple(ClassFloor(label=label, recall_minimum=0.95, precision_minimum=0.9,
                                                  recall_lower95_minimum=0.9) for label in reversed(LABELS)),
                       development_justification_sha256=h("1"))


# ------------------------------------------------------------------ authorization

T0 = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


def pins():
    return tuple(ArmPin(arm=a, model_id="m-" + a, artifact_sha256=h(str(i)), configuration_sha256=h(str(i + 4)))
                 for i, a in enumerate(ARMS))


def packet(**overrides):
    population = (PopulationMember(record_id="rec-1", content_sha256=h("1")),
                  PopulationMember(record_id="rec-2", content_sha256=h("2")))
    fields = dict(authorization_id="eauth-1", edition_id="ed-1", run_id="run-1", plan_sha256=h("a"),
                  corpus_manifest_sha256=h("b"),
                  population_sha256=commitment([m.model_dump(mode="json") for m in population]),
                  selection_lock_sha256=h("c"), custody_release_sha256=h("d"), independent_audit_sha256=h("e"),
                  adoption_policy_sha256=commitment(policy().model_dump(mode="json")), timing_plan_sha256=h("f"),
                  arm_pins=pins(), issued_at="2026-01-10T00:00:00Z", expires_at="2026-01-11T00:00:00Z",
                  allowed_action="open_or_resume_locked_evaluation")
    fields.update(overrides)
    return EvaluationAuthorization(**fields), population


def edition_for(auth, population, **overrides):
    fields = dict(edition_id="ed-1", run_id="run-1", plan_sha256=h("a"), corpus_manifest_sha256=h("b"),
                  custody_release_sha256=h("d"), independent_audit_sha256=h("e"), selection_lock_sha256=h("c"),
                  execution_authorization_sha256=commitment(auth.model_dump(mode="json")),
                  adoption_policy=policy(), timing_plan_sha256=h("f"), expires_at="2026-01-11T00:00:00Z",
                  population=population, arm_pins=pins())
    fields.update(overrides)
    return LockedEdition(**fields)


def test_authorization_window_is_half_open():
    auth, pop = packet()
    edition = edition_for(auth, pop)
    ReceiptAuthority.validate_binding(auth, edition, now=datetime(2026, 1, 10, 0, 0, tzinfo=timezone.utc))  # issued_at: in
    ReceiptAuthority.validate_binding(auth, edition, now=datetime(2026, 1, 10, 23, 59, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="evaluation_authorization_expired"):
        ReceiptAuthority.validate_binding(auth, edition, now=datetime(2026, 1, 11, 0, 0, tzinfo=timezone.utc))  # expires_at: out
    with pytest.raises(ValueError, match="evaluation_authorization_expired"):
        ReceiptAuthority.validate_binding(auth, edition, now=datetime(2026, 1, 9, 23, 59, tzinfo=timezone.utc))


def test_authorization_must_bind_the_exact_edition():
    auth, pop = packet()
    # Edition committed to a different authorization packet digest.
    other = edition_for(auth, pop, execution_authorization_sha256=h("9"))
    with pytest.raises(ValueError, match="evaluation_authorization_binding_mismatch"):
        ReceiptAuthority.validate_binding(auth, other, now=T0)
    # Edition pinning a different finetuned model (digest still matches this packet).
    moved = pins()[:3] + (pins()[3].model_copy(update={"model_id": "m-other"}),)
    with pytest.raises(ValueError, match="evaluation_authorization_binding_mismatch"):
        ReceiptAuthority.validate_binding(auth, edition_for(auth, pop, arm_pins=moved), now=T0)
    with pytest.raises(ValueError, match="timezone_required"):
        ReceiptAuthority.validate_binding(auth, edition_for(auth, pop), now=datetime(2026, 1, 10, 12, 0))
    # Authorization expiring before the edition cannot cover it.
    short, pop = packet(expires_at="2026-01-10T18:00:00Z")
    with pytest.raises(ValueError, match="evaluation_authorization_binding_mismatch"):
        ReceiptAuthority.validate_binding(short, edition_for(short, pop), now=T0)


def test_revoked_receipt_refuses_open_or_resume():
    # Real clock is far past the fixture window, so build a current packet around "now".
    now = datetime.now(timezone.utc)
    issued, expires = (now - timedelta(hours=1)).isoformat(), (now + timedelta(hours=1)).isoformat()
    auth, pop = packet(issued_at=issued, expires_at=expires)
    edition = edition_for(auth, pop, expires_at=expires)
    calls = []

    def revoked_audit(kind, digest):
        calls.append(kind)
        return kind != "independent_audit"
    with pytest.raises(ValueError, match="receipt_not_authenticated_or_revoked"):
        ReceiptAuthority(auth, verify_receipt=revoked_audit)(edition, resume=True)
    assert calls == ["evaluation_authorization", "custody_release", "independent_audit"]
    # Truthy non-True is not authentication.
    with pytest.raises(ValueError, match="receipt_not_authenticated_or_revoked"):
        ReceiptAuthority(auth, verify_receipt=lambda kind, digest: 1)(edition, resume=False)


# ------------------------------------------------------------------ released reader and activation

@pytest.mark.parametrize("refused", ["released_inference_export", "released_gold_export"])
def test_released_reader_refuses_revoked_or_superseded_export_before_any_read(refused, tmp_path):
    # A revoked or superseded release is no longer authenticated by the trusted store.
    auth, pop = packet()
    with pytest.raises(ValueError, match="released_export_receipt_not_authenticated"):
        read_released_channels(edition_for(auth, pop), filesystem=None, inference_directory=tmp_path,
                               gold_directory=tmp_path, inference_export_sha256=h("1"), gold_export_sha256=h("2"),
                               verify_receipt=lambda kind, digest: kind != refused)


def test_operator_host_cannot_be_built_without_verifier_or_isolation_guard():
    with pytest.raises(TypeError):
        OperatorHost(registry_factory=lambda: {}, cost_summary=lambda: {}, custody_filesystem=object(),
                     isolation_guard=object())  # verify_receipt missing
    with pytest.raises(TypeError):
        OperatorHost(verify_receipt=lambda k, s: True, registry_factory=lambda: {}, cost_summary=lambda: {},
                     custody_filesystem=object())  # isolation_guard missing


def test_activation_policy_requires_real_lock_types_and_calls_no_verifier():
    calls = []
    auth, pop = packet()
    with pytest.raises(ValueError, match="d5_lock_and_targets_required"):
        policy_from_selection_lock(edition_for(auth, pop), {"sha256": h("c")}, {},
                                   verify_receipt=lambda kind, digest: calls.append(kind) or True)
    assert calls == []
