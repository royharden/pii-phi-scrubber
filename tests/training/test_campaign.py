"""Campaign spec, shared profile P vs per-arm launch L, active roots, CLI validate-only.

Structural paths only (check_files=False): no file, host, worker or model is touched.
"""
import json
import sys

import pytest
from pydantic import ValidationError

from m7.providers.worker_profile import (
    WorkerLaunchPolicy, WorkerProfile, launch_member_digest, validate_worker_membership, worker_profile_digest,
)
from m7.training.campaign import campaign_arm_pins, validate_campaign
from m7.training.campaign_cli import campaign_main
from m7.training.campaign_models import CampaignAllocation, CampaignBudget

from .campaign_world import CLOCK, N, build, h, respec


def test_consistent_campaign_is_structurally_valid_but_never_activated():
    w = build()
    out = validate_campaign(w.spec, clock=lambda: CLOCK)
    assert out["status"] == "structure_valid_not_authenticated"
    assert out["activation_allowed"] is False and out["runtime_executed"] is False


def test_campaign_requires_exactly_four_launch_arms_and_matching_profile():
    w = build()
    three = {k: v for k, v in w.launches.items() if k != "regex"}
    with pytest.raises(ValidationError):
        respec(w, launch_policies={k: v.model_dump(mode="json") for k, v in three.items()})
    # Profile listing only three members while four launches exist.
    profile3 = WorkerProfile(profile_id="profile-1",
                             members={k: v for k, v in w.profile.members.items() if k != "regex"})
    with pytest.raises(ValidationError):
        respec(w, worker_profile=profile3)


def test_arm_pins_cover_four_arms_in_fixed_order():
    pins = campaign_arm_pins(build().spec)
    assert [p.arm for p in pins] == ["regex", "frontier", "base", "finetuned"]


def test_full_denominator_requires_primary_plus_three_passes_of_calls():
    # Allocation must cover intended_records x 4 = 8 logical calls; 7 is one short.
    w = build()
    allocations = {k: v.model_dump(mode="json") for k, v in w.budget.allocations.items()}
    allocations["base"]["max_logical_calls"] = 4 * N - 1
    budget = w.budget.model_dump(mode="json")
    budget["allocations"] = allocations
    with pytest.raises(ValueError, match="campaign_resource_or_attempt_budget_mismatch"):
        validate_campaign(respec(w, budget=budget), clock=lambda: CLOCK)


def test_budget_needs_three_separate_paid_allocations_within_combined_cap():
    w = build()
    allocations = dict(w.budget.allocations)
    with pytest.raises(ValidationError):  # regex has no paid allocation; frontier missing
        CampaignBudget(currency="USD", total_authorized_cash_micros=500, prior_known_training_cash_micros=0,
                       prior_unknown_training_liability_micros=100, training_run_closeout_sha256=h("9"),
                       allocations={k: v for k, v in allocations.items() if k != "frontier"})
    shared = {k: CampaignAllocation(authorization_id="same", cash_cap_micros=100, max_logical_calls=8) for k in allocations}
    with pytest.raises(ValidationError):
        CampaignBudget(currency="USD", total_authorized_cash_micros=500, prior_known_training_cash_micros=0,
                       prior_unknown_training_liability_micros=100, training_run_closeout_sha256=h("9"),
                       allocations=shared)
    # 100 prior unknown liability + 3 x 100 = 400 > 399.
    with pytest.raises(ValidationError):
        CampaignBudget(currency="USD", total_authorized_cash_micros=399, prior_known_training_cash_micros=0,
                       prior_unknown_training_liability_micros=100, training_run_closeout_sha256=h("9"),
                       allocations=allocations)


def test_shared_profile_p_and_per_arm_launch_l_are_distinct_and_acyclic():
    w = build()
    p = worker_profile_digest(w.profile)
    launch_digests = {arm: validate_worker_membership(w.profile, policy).launch_sha256
                      for arm, policy in w.launches.items()}
    # Four distinct L values, none equal to the shared P.
    assert len(set(launch_digests.values())) == 4 and p not in launch_digests.values()
    for arm, policy in w.launches.items():
        assert policy.profile_sha256 == p                      # L includes P ...
        assert w.profile.members[arm] == launch_member_digest(policy)  # ... member digest excludes P
        # Member digest ignores ONLY profile_sha256: swapping P leaves it unchanged.
        other = policy.model_copy(update={"profile_sha256": h("f")})
        assert launch_member_digest(other) == launch_member_digest(policy)
    # Any other launch field changes the member digest -> membership refused.
    moved = WorkerLaunchPolicy(**{**w.launches["base"].model_dump(), "executable_sha256": h("e")})
    with pytest.raises(ValueError, match="worker_profile_membership_mismatch"):
        validate_worker_membership(w.profile, moved)


def test_campaign_rejects_launch_digest_used_as_shared_profile():
    # Equating an L with the shared P must fail, never be "repaired".
    w = build()
    some_l = validate_worker_membership(w.profile, w.launches["base"]).launch_sha256
    resources = w.resources.model_copy(update={"worker_policy_sha256": some_l})
    with pytest.raises(ValueError, match="campaign_shared_worker_profile_mismatch"):
        validate_campaign(respec(w, resources=resources), clock=lambda: CLOCK)


def test_launch_from_other_profile_is_refused():
    w = build()
    launches = {k: v.model_dump(mode="json") for k, v in w.launches.items()}
    launches["frontier"]["profile_sha256"] = h("f")
    with pytest.raises(ValueError, match="worker_profile_membership_mismatch"):
        validate_campaign(respec(w, launch_policies=launches), clock=lambda: CLOCK)


def _relaunch(w, arm, **fields):
    """Rebuild one arm's member/profile/launch consistently with changed fields."""
    member = w.members[arm].model_copy(update=fields)
    members = {**w.profile.members, arm: launch_member_digest(member)}
    profile = WorkerProfile(profile_id="profile-1", members=members)
    p = worker_profile_digest(profile)
    launches = {}
    for a, m in w.members.items():
        m = member if a == arm else m
        launches[a] = WorkerLaunchPolicy(**m.model_dump(), profile_sha256=p).model_dump(mode="json")
    resources = w.resources.model_copy(update={"worker_policy_sha256": p})
    return respec(w, worker_profile=profile, launch_policies=launches, resources=resources)


def test_only_the_active_arm_root_may_be_launched():
    # Finetuned worker pointed at the BASE artifact root (consistent hashes otherwise).
    w = build()
    spec = _relaunch(w, "finetuned", artifact_root=w.base.artifact_root)
    with pytest.raises(ValueError, match="campaign_launch_artifact_root_mismatch"):
        validate_campaign(spec, clock=lambda: CLOCK)


def test_relative_worker_paths_refused():
    w = build()
    spec = _relaunch(w, "regex", working_directory="work/regex")
    with pytest.raises(ValueError, match="campaign_worker_absolute_path_required"):
        validate_campaign(spec, clock=lambda: CLOCK)


def test_expired_campaign_refused():
    w = build()
    with pytest.raises(ValueError, match="campaign_or_lock_expired"):
        validate_campaign(w.spec, clock=lambda: CLOCK.replace(month=2))


def test_credentialed_frontier_endpoint_refused():
    w = build()
    frontier = w.frontier.model_copy(update={"endpoint": "https://user:secret@api.example.test/v1"})
    # The endpoint check runs before the per-arm permit/config-digest checks, so the
    # (now stale) frontier permit digest is never reached.
    with pytest.raises(ValueError, match="credential_free_approved_https_endpoint_required"):
        validate_campaign(respec(w, frontier=frontier), clock=lambda: CLOCK)


HOST_MODULES = ("m7.data.native_windows_api", "m7.data.native_windows", "m7.providers.native_launcher",
                "m7.providers.native_launch_api", "m7.data.access")


def test_validate_only_cli_needs_no_host_and_activate_without_host_is_unavailable(tmp_path):
    w = build()
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(w.spec.model_dump(mode="json")), encoding="utf-8")
    before = {m for m in HOST_MODULES if m in sys.modules}
    # The CLI uses the real clock, which is past the fixture's 2026-01-20 expiry, so
    # validate-only stops at the expiry check after full schema parsing, with no host.
    with pytest.raises(ValueError, match="campaign_or_lock_expired"):
        campaign_main(["--spec", str(path), "--validate-only"])
    # The full structural path (every check, at the fixture clock) imports no host module either.
    validate_campaign(w.spec, clock=lambda: CLOCK)
    assert {m for m in HOST_MODULES if m in sys.modules} == before
    out = campaign_main(["--spec", str(path), "--activate"])
    assert out == {"status": "unavailable", "reason": "authenticated_campaign_host_required",
                   "activation_allowed": False, "runtime_executed": False}
    with pytest.raises(ValueError, match="validation_cannot_write_handoff"):
        campaign_main(["--spec", str(path), "--validate-only", "--out", str(tmp_path)])
