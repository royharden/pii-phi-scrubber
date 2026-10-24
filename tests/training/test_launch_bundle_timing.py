"""Launch bundle canonical digest/pins and timing resource schedule/survivor partition.

Definition-only paths: no host, worker, phase, ledger or held-out access.
Arithmetic expectations are hand-derived from N=2 records, w=10 micros/attempt.
"""
import json

import pytest
from pydantic import ValidationError

from m7.training.launch_bundle import WorkerLaunchBundle, build_worker_launch_bundle, parse_launch_bundle
from m7.training.timing_resources import TimingResourceAuthorization, TimingResourceReceipt, validate_timing_resources

from .campaign_world import CLOCK, build, h


def bundle_of(w):
    return build_worker_launch_bundle(w.spec, w.bootstraps, clock=lambda: CLOCK)


def reverse_keys(value):
    if isinstance(value, dict):
        return {k: reverse_keys(value[k]) for k in reversed(list(value))}
    if isinstance(value, list):
        return [reverse_keys(v) for v in value]
    return value


def test_bundle_digest_is_stable_under_key_order():
    b = bundle_of(build())
    raw = json.dumps(reverse_keys(b.model_dump(mode="json")), sort_keys=False).encode("utf-8")
    parsed = parse_launch_bundle(raw, clock=lambda: CLOCK)
    assert parsed.sha256 == b.sha256
    assert set(parsed.bootstraps) == {"regex", "frontier", "base", "finetuned"}


@pytest.mark.parametrize("path,value", [
    (("campaign_sha256",), "f" * 64),
    (("profile_sha256",), "f" * 64),
    (("bootstraps", "regex", "session_id"), "sess-other"),
    (("memberships", "base", "launch_sha256"), "f" * 64),
    (("campaign", "intended_records"), 3),
])
def test_any_pinned_field_change_changes_digest_and_is_refused(path, value):
    b = bundle_of(build())
    data = b.model_dump(mode="json")
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    mutated = WorkerLaunchBundle.model_validate_json(json.dumps(data))  # schema-valid, not yet joined
    assert mutated.sha256 != b.sha256
    with pytest.raises(ValueError):
        parse_launch_bundle(json.dumps(data).encode("utf-8"), clock=lambda: CLOCK)


def test_bundle_needs_all_four_worker_arms():
    w = build()
    three = {k: v for k, v in w.bootstraps.items() if k != "regex"}
    with pytest.raises(ValidationError):
        build_worker_launch_bundle(w.spec, three, clock=lambda: CLOCK)


def test_parse_rejects_unknown_schema_and_duplicate_keys():
    with pytest.raises(ValueError, match="unsupported_worker_handoff_schema"):
        parse_launch_bundle(b'{"schema_version":"Other/v1"}', clock=lambda: CLOCK)
    with pytest.raises(ValueError):
        parse_launch_bundle(b'{"schema_version":"WorkerLaunchBundle/v1","schema_version":"WorkerLaunchBundle/v1"}',
                            clock=lambda: CLOCK)


# --------------------------------------------------------------------- timing resources

def test_schedule_is_primary_plus_three_passes_hand_arithmetic():
    s = build().schedule
    assert set(s.arms) == {"base", "finetuned", "frontier"}  # regex has no paid calls
    assert (s.passes, s.intended_records, s.concurrency) == (3, 2, 1)
    for bound in s.arms.values():
        # N=2, w=10, r=0: 4N=8 calls/attempts; primary 2x10=20; timing 3x2x10=60; total 4x2x10=80.
        assert (bound.primary_logical_calls, bound.timing_logical_calls_per_pass, bound.total_logical_calls) == (2, 2, 8)
        assert bound.maximum_backend_attempts == 8
        assert (bound.primary_inference_bound_micros, bound.timing_inference_bound_micros) == (20, 60)
        assert (bound.primary_retry_bound_micros, bound.timing_retry_bound_micros, bound.total_cash_bound_micros) == (0, 0, 80)
    assert s.quote_status == "worst_case_reservation_bounds_not_observed_cost"


def test_one_retry_doubles_frontier_bounds():
    s = build(frontier_retries=1, frontier_cap=160).schedule
    f = s.arms["frontier"]
    # r=1: attempts 4N(1+r)=16; primary retry 2x10x1=20; timing retry 3x2x10x1=60; total 4x2x10x2=160.
    assert (f.maximum_backend_attempts, f.primary_retry_bound_micros, f.timing_retry_bound_micros,
            f.total_cash_bound_micros) == (16, 20, 60, 160)


def test_schedule_exceeding_allocation_cap_is_refused():
    # Same retry but cap 100 < required 160 worst case.
    with pytest.raises(ValidationError, match="timing_reservation_arithmetic_mismatch"):
        build(frontier_retries=1, frontier_cap=100)


def test_timing_resources_validate_definitions_only():
    w = build()
    out = validate_timing_resources(bundle_of(w), w.plan, w.schedule, clock=lambda: CLOCK)
    assert out["passes"] == 3 and out["activation_allowed"] is False and out["measured_cost_micros"] is None


def test_locked_schedule_cannot_be_mutated_or_substituted():
    w = build()
    with pytest.raises(ValidationError):
        w.schedule.intended_records = 3  # frozen definition
    # A substituted (unvalidated) copy differs from the regenerated preregistered schedule.
    substituted = w.schedule.model_copy(update={"total_campaign_authorized_cash_micros": 999})
    with pytest.raises(ValueError, match="timing_plan_or_resource_schedule_not_preregistered_campaign"):
        validate_timing_resources(bundle_of(w), w.plan, substituted, clock=lambda: CLOCK)


def authorization(**overrides):
    fields = dict(authorization_id="tauth-1", approved_by="int2", approved=True,
                  action="qualify_three_fixed_timing_pass_resources", schedule_sha256=h("1"), bundle_sha256=h("2"),
                  campaign_sha256=h("3"), edition_sha256=h("4"), primary_accounting_sha256=h("5"), plan_sha256=h("6"),
                  profile_sha256=h("7"),
                  launch_sha256_by_arm={"regex": h("a"), "frontier": h("b"), "base": h("c"), "finetuned": h("d")},
                  warm_identity_sha256_by_arm={"regex": h("e"), "frontier": h("f"), "base": h("8")},
                  unavailable_arms={"finetuned": "primary_backend_unavailable"},
                  currency="USD", cash_authorization_sha256=h("9"),
                  issued_at="2026-01-10T00:00:00Z", expires_at="2026-01-11T00:00:00Z")
    fields.update(overrides)
    return TimingResourceAuthorization(**fields)


def test_survivors_plus_explicit_unavailable_partition_all_four_arms():
    a = authorization()
    assert set(a.warm_identity_sha256_by_arm) | set(a.unavailable_arms) == {"regex", "frontier", "base", "finetuned"}
    # No survivors at all is still an honest, complete partition (no fake identities).
    authorization(warm_identity_sha256_by_arm={},
                  unavailable_arms={arm: "original_process_unavailable" for arm in ("regex", "frontier", "base", "finetuned")})


@pytest.mark.parametrize("overrides", [
    # finetuned both warm and unavailable
    {"warm_identity_sha256_by_arm": {"regex": h("e"), "frontier": h("f"), "base": h("8"), "finetuned": h("0")}},
    # base silently dropped from both sides (population would shrink)
    {"warm_identity_sha256_by_arm": {"regex": h("e"), "frontier": h("f")}},
    # two arms claim the same warm identity (aliased process/backend)
    {"warm_identity_sha256_by_arm": {"regex": h("e"), "frontier": h("e"), "base": h("8")}},
    # launch pins for only three arms
    {"launch_sha256_by_arm": {"regex": h("a"), "frontier": h("b"), "base": h("c")}},
])
def test_incomplete_or_aliased_survivor_partition_refused(overrides):
    with pytest.raises(ValidationError):
        authorization(**overrides)


def test_resource_receipt_cannot_carry_a_measured_or_zero_cost():
    fields = dict(request_sha256=h("1"), authorization_sha256=h("2"), schedule_sha256=h("3"),
                  cash_snapshot_sha256=h("4"), primary_accounting_sha256=h("5"), plan_sha256=h("6"),
                  arm="base", ordinal=1, attempt_namespace=h("7"), maximum_logical_calls=2,
                  maximum_backend_attempts=2, worst_case_phase_cash_micros=20, cash_authorization_id="alloc-base",
                  currency="USD", qualified_at="2026-01-10T00:00:00Z", expires_at="2026-01-11T00:00:00Z")
    assert TimingResourceReceipt(**fields).measured_cost_micros is None
    with pytest.raises(ValidationError):
        TimingResourceReceipt(**fields, measured_cost_micros=0)
    with pytest.raises(ValidationError):
        TimingResourceReceipt(**{**fields, "ordinal": 4})  # only three timing passes
