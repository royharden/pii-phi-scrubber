"""Preregistered timing cost bounds and post-primary resource handoff.

No worker reset, custody open, ledger mutation, model/native call or measurement.
D7 owns timing contracts; D4 owns durable phase admission; D6 owns live sessions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Annotated, Callable, Literal, TYPE_CHECKING

from pydantic import Field, model_validator

from m7.contracts import Arm, Boundary, Digest, Identifier
from m7.providers.contracts import AttemptPolicy, config_digest
from .campaign import CampaignHost, campaign_arm_pins
from .campaign_models import CampaignBudget, Cash
from .executor import _write_json
from .launch_bundle import ARMS, WorkerLaunchBundle, prepare_launch_bundle, validate_launch_bundle
from .selection import authenticate, Verifier
from .validation import digest, now_utc, utc

if TYPE_CHECKING:
    from m7.experiment.timing_contracts import IsolatedTimingPlan, PrimaryAccountingReceipt, TimingPhaseRequest

PAID_ARMS = ("base", "finetuned", "frontier")
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class TimingArmBound(Boundary):
    authorization_id: Identifier
    policy_sha256: Digest
    rate_receipt_sha256: Digest
    allocation_cap_micros: Cash
    worst_case_attempt_micros: Cash
    max_retries: Annotated[int, Field(ge=0, le=1)]
    primary_logical_calls: Annotated[int, Field(ge=1, le=1000000)]
    timing_logical_calls_per_pass: Annotated[int, Field(ge=1, le=1000000)]
    total_logical_calls: Annotated[int, Field(ge=4, le=1000000)]
    maximum_backend_attempts: Annotated[int, Field(ge=4, le=2000000)]
    primary_inference_bound_micros: Cash
    primary_retry_bound_micros: Cash
    timing_inference_bound_micros: Cash
    timing_retry_bound_micros: Cash
    total_cash_bound_micros: Cash


class TimingResourceSchedule(Boundary):
    """Leaf schedule: no edition/campaign/profile/full launch or primary digest."""
    schema_version: Literal["TimingResourceSchedule/v1"] = "TimingResourceSchedule/v1"
    plan_sha256: Digest
    population_sha256: Digest
    order_sha256: Digest
    intended_records: Annotated[int, Field(ge=1, le=1000000)]
    passes: Literal[3] = 3
    concurrency: Literal[1] = 1
    warmup_policy: Literal["retain_primary_process_and_backend_no_extra_warmup"] = "retain_primary_process_and_backend_no_extra_warmup"
    currency: Currency
    prior_training_closeout_sha256: Digest
    prior_known_training_cash_micros: Cash
    prior_unknown_training_liability_micros: Cash
    total_campaign_authorized_cash_micros: Cash
    arms: dict[str, TimingArmBound]
    ledger_categories: tuple[Literal["inference"], Literal["retry"]] = ("inference", "retry")
    quote_status: Literal["worst_case_reservation_bounds_not_observed_cost"] = "worst_case_reservation_bounds_not_observed_cost"

    @model_validator(mode="after")
    def complete(self):
        if set(self.arms) != set(PAID_ARMS):
            raise ValueError("timing_all_paid_arm_bounds_required")
        if (self.prior_known_training_cash_micros + self.prior_unknown_training_liability_micros +
                sum(a.allocation_cap_micros for a in self.arms.values()) > self.total_campaign_authorized_cash_micros):
            raise ValueError("timing_combined_cash_cap_exceeded")
        for bound in self.arms.values():
            n, w, r = self.intended_records, bound.worst_case_attempt_micros, bound.max_retries
            if (bound.primary_logical_calls != n or bound.timing_logical_calls_per_pass != n or
                    bound.total_logical_calls != 4 * n or bound.maximum_backend_attempts != 4 * n * (1 + r) or
                    bound.primary_inference_bound_micros != n * w or bound.primary_retry_bound_micros != n * w * r or
                    bound.timing_inference_bound_micros != 3 * n * w or bound.timing_retry_bound_micros != 3 * n * w * r or
                    bound.total_cash_bound_micros != 4 * n * w * (1 + r) or
                    bound.total_cash_bound_micros > bound.allocation_cap_micros):
                raise ValueError("timing_reservation_arithmetic_mismatch")
        return self

    @property
    def sha256(self) -> str:
        return digest(self.model_dump(mode="json"))


class TimingResourceAuthorization(Boundary):
    """Externally signed/verified AFTER immutable primary accounting closes."""
    schema_version: Literal["TimingResourceAuthorization/v1"] = "TimingResourceAuthorization/v1"
    authorization_id: Identifier
    approved_by: Identifier
    approved: Literal[True]
    action: Literal["qualify_three_fixed_timing_pass_resources"]
    schedule_sha256: Digest
    bundle_sha256: Digest
    campaign_sha256: Digest
    edition_sha256: Digest
    primary_accounting_sha256: Digest
    plan_sha256: Digest
    profile_sha256: Digest
    launch_sha256_by_arm: dict[Arm, Digest]
    warm_identity_sha256_by_arm: dict[Arm, Digest]
    unavailable_arms: dict[Arm, Literal["primary_backend_unavailable", "original_process_unavailable", "warm_identity_unverified"]]
    currency: Currency
    cash_authorization_sha256: Digest
    issued_at: str
    expires_at: str

    @model_validator(mode="after")
    def complete(self):
        eligible, unavailable = set(self.warm_identity_sha256_by_arm), set(self.unavailable_arms)
        if (set(self.launch_sha256_by_arm) != set(ARMS) or eligible & unavailable or
                eligible | unavailable != set(ARMS) or
                len(set(self.warm_identity_sha256_by_arm.values())) != len(eligible) or
                utc(self.expires_at) <= utc(self.issued_at)):
            raise ValueError("incomplete_timing_resource_authorization")
        return self

    @property
    def sha256(self) -> str:
        return digest(self.model_dump(mode="json"))


class CashBalance(Boundary):
    authorization_id: Identifier
    cap_micros: Cash
    known_cash_micros: Cash
    unresolved_liability_micros: Cash
    remaining_micros: Cash
    cost_report_sha256: Digest
    measurement_status: Literal["known", "partially_known", "not_measured"]

    @model_validator(mode="after")
    def conservative(self):
        if self.remaining_micros != max(0, self.cap_micros - self.known_cash_micros - self.unresolved_liability_micros):
            raise ValueError("timing_cash_remaining_mismatch")
        if self.known_cash_micros + self.unresolved_liability_micros > self.cap_micros:
            raise ValueError("timing_cash_authorization_overrun")
        return self


class TimingCashSnapshot(Boundary):
    schema_version: Literal["TimingCashSnapshot/v1"] = "TimingCashSnapshot/v1"
    snapshot_id: Identifier
    schedule_sha256: Digest
    primary_accounting_sha256: Digest
    training_run_closeout_sha256: Digest
    currency: Currency
    training: CashBalance
    arms: dict[str, CashBalance]
    captured_at: str
    expires_at: str

    @model_validator(mode="after")
    def distinct(self):
        ids = [self.training.authorization_id] + [a.authorization_id for a in self.arms.values()]
        if set(self.arms) != set(PAID_ARMS) or len(set(ids)) != 4 or utc(self.expires_at) <= utc(self.captured_at):
            raise ValueError("incomplete_or_aliased_timing_cash_snapshot")
        return self

    @property
    def sha256(self) -> str:
        return digest(self.model_dump(mode="json"))


class TimingResourceReceipt(Boundary):
    schema_version: Literal["TimingResourceReceipt/v1"] = "TimingResourceReceipt/v1"
    request_sha256: Digest
    authorization_sha256: Digest
    schedule_sha256: Digest
    cash_snapshot_sha256: Digest
    primary_accounting_sha256: Digest
    plan_sha256: Digest
    arm: Arm
    ordinal: Annotated[int, Field(ge=1, le=3)]
    attempt_namespace: Digest
    maximum_logical_calls: Annotated[int, Field(ge=1)]
    maximum_backend_attempts: Annotated[int, Field(ge=1)]
    worst_case_phase_cash_micros: Cash
    cash_authorization_id: Identifier | None
    currency: Currency
    qualified_at: str
    expires_at: str
    status: Literal["resources_qualified_not_a_custody_or_reset_permit"] = "resources_qualified_not_a_custody_or_reset_permit"
    measured_cost_micros: None = None

    @property
    def sha256(self) -> str:
        return digest(self.model_dump(mode="json"))


def _plan(plan):
    from m7.experiment.timing_contracts import IsolatedTimingPlan
    if not isinstance(plan, IsolatedTimingPlan):
        raise ValueError("d7_isolated_timing_plan_required")
    return IsolatedTimingPlan.model_validate_json(plan.model_dump_json())


def build_timing_resource_schedule(plan: IsolatedTimingPlan, *, policies: dict[str, AttemptPolicy],
                                   budget: CampaignBudget) -> TimingResourceSchedule:
    """Pure pre-primary quote, computed before CampaignSpec/profile/launch hashing."""
    plan = _plan(plan)
    if set(policies) != set(PAID_ARMS):
        raise ValueError("timing_paid_arm_policies_required")
    n, arms = len(plan.record_order), {}
    for arm in PAID_ARMS:
        policy, allocation = policies[arm], budget.allocations[arm]
        w, r = policy.worst_case_micros, policy.max_transient_retries
        if (policy.authorization_id != allocation.authorization_id or
                policy.authorization_cap_micros != allocation.cash_cap_micros or
                min(policy.max_records, allocation.max_logical_calls) < 4 * n):
            raise ValueError("primary_plus_three_pass_capacity_missing")
        arms[arm] = TimingArmBound(authorization_id=allocation.authorization_id,
            policy_sha256=config_digest(policy), rate_receipt_sha256=policy.rate_receipt_sha256,
            allocation_cap_micros=allocation.cash_cap_micros, worst_case_attempt_micros=w, max_retries=r,
            primary_logical_calls=n, timing_logical_calls_per_pass=n, total_logical_calls=4 * n,
            maximum_backend_attempts=4 * n * (1 + r), primary_inference_bound_micros=n * w,
            primary_retry_bound_micros=n * w * r, timing_inference_bound_micros=3 * n * w,
            timing_retry_bound_micros=3 * n * w * r, total_cash_bound_micros=4 * n * w * (1 + r))
    return TimingResourceSchedule(plan_sha256=plan.sha256, population_sha256=plan.population_sha256,
        order_sha256=plan.order_sha256, intended_records=n, currency=budget.currency,
        prior_training_closeout_sha256=budget.training_run_closeout_sha256,
        prior_known_training_cash_micros=budget.prior_known_training_cash_micros,
        prior_unknown_training_liability_micros=budget.prior_unknown_training_liability_micros,
        total_campaign_authorized_cash_micros=budget.total_authorized_cash_micros, arms=arms)


def normalize_timing_cash_snapshot(*, snapshot_id: str, schedule: TimingResourceSchedule,
                                   primary_accounting_sha256: str, training_summary: dict,
                                   arm_summaries: dict[str, dict], captured_at: str, expires_at: str) -> TimingCashSnapshot:
    """Use D7 canonical category/state arithmetic. No ledger/DB access here."""
    from m7.experiment.costing import cost_report
    if set(arm_summaries) != set(PAID_ARMS):
        raise ValueError("all_timing_cash_authorizations_required")
    def balance(summary, training=False):
        report = cost_report(summary)
        if report["currency"] != schedule.currency or report["over_cap"]:
            raise ValueError("timing_cash_currency_or_cap_mismatch")
        prohibited = ("inference", "retry") if training else ("training", "failed_trial")
        if any(report["by_category"][category]["attempts_N"] for category in prohibited):
            raise ValueError("timing_cash_category_scope_collision")
        return CashBalance(authorization_id=summary["authorization_id"], cap_micros=report["cap_micros"],
            known_cash_micros=report["known_provider_cash_micros"], unresolved_liability_micros=report["unresolved_liability_micros"],
            remaining_micros=report["remaining_micros"], cost_report_sha256=digest(report), measurement_status=report["status"])
    return TimingCashSnapshot(snapshot_id=snapshot_id, schedule_sha256=schedule.sha256,
        primary_accounting_sha256=primary_accounting_sha256,
        training_run_closeout_sha256=schedule.prior_training_closeout_sha256, currency=schedule.currency,
        training=balance(training_summary, True), arms={arm: balance(arm_summaries[arm]) for arm in PAID_ARMS},
        captured_at=captured_at, expires_at=expires_at)


def validate_timing_resources(bundle: WorkerLaunchBundle, plan: IsolatedTimingPlan,
                              schedule: TimingResourceSchedule) -> dict:
    """Definition-only validation; no snapshot/native/receipt queries or measurements."""
    plan = _plan(plan)
    validate_launch_bundle(bundle)
    spec = bundle.campaign
    expected = build_timing_resource_schedule(plan, policies=spec.policies, budget=spec.budget)
    if (schedule != expected or plan.sha256 != spec.timing_plan_sha256 or
            getattr(spec, "timing_resource_schedule_sha256", None) != schedule.sha256 or
            plan.edition_id != spec.edition_id or plan.run_id != spec.run_id or
            plan.population_sha256 != spec.population_sha256 or len(plan.record_order) != spec.intended_records or
            plan.arm_pins != campaign_arm_pins(spec) or
            any(bootstrap.timing_plan_sha256 != plan.sha256 or
                bootstrap.timing_order_sha256 != plan.order_sha256
                for bootstrap in bundle.bootstraps.values())):
        raise ValueError("timing_plan_or_resource_schedule_not_preregistered_campaign")
    return {"status": "timing_resources_structural_only", "schedule_sha256": schedule.sha256,
            "plan_sha256": plan.sha256, "passes": 3, "activation_allowed": False, "measured_cost_micros": None}


class TimingResourceAuthority:
    """Resource qualification only. D4 must durably consume phases; D6 resets.

    Snapshot provider is a trusted parent callback; no backend, ledger or native
    implementation is instantiated here. Rechecks never free unknown liability.
    """
    def __init__(self, bundle: WorkerLaunchBundle, schedule: TimingResourceSchedule,
                 authorization: TimingResourceAuthorization, *, verify_receipt: Verifier,
                 snapshot_provider: Callable[[], TimingCashSnapshot], clock: Callable[[], datetime] = now_utc):
        self.bundle, self.schedule, self.authorization = bundle, schedule, authorization
        self.verify_receipt, self.snapshot_provider, self.clock = verify_receipt, snapshot_provider, clock
        self._primary = self._plan = None
        self._namespaces: dict[tuple[str, int], str] = {}
        self._survivors: dict[str, tuple[int, str, str]] = {}

    def _authorization(self):
        auth, spec = self.authorization, self.bundle.campaign
        if not utc(auth.issued_at) <= self.clock() < utc(auth.expires_at) <= utc(spec.expires_at):
            raise ValueError("timing_resource_authorization_expired")
        authenticate(self.verify_receipt, "timing_resource_authorization", auth.sha256)
        authenticate(self.verify_receipt, "timing_resource_schedule", self.schedule.sha256)

    def prepare(self, primary: PrimaryAccountingReceipt, plan: IsolatedTimingPlan) -> None:
        from m7.experiment.timing_contracts import PrimaryAccountingReceipt
        primary = PrimaryAccountingReceipt.model_validate_json(primary.model_dump_json())
        plan = _plan(plan)
        validate_timing_resources(self.bundle, plan, self.schedule)
        auth = self.authorization
        if (self._primary is not None and self._primary.sha256 != primary.sha256 or
                auth.bundle_sha256 != self.bundle.sha256 or auth.campaign_sha256 != self.bundle.campaign_sha256 or
                auth.schedule_sha256 != self.schedule.sha256 or auth.primary_accounting_sha256 != primary.sha256 or
                auth.edition_sha256 != primary.edition_sha256 or auth.plan_sha256 != plan.sha256 or
                auth.profile_sha256 != self.bundle.profile_sha256 or auth.currency != self.schedule.currency or
                auth.cash_authorization_sha256 != self.bundle.campaign.resources.cost_authorization_sha256 or
                auth.launch_sha256_by_arm != {a: m.launch_sha256 for a, m in self.bundle.memberships.items()} or
                primary.population_sha256 != plan.population_sha256 or primary.intended_cells != 4 * len(plan.record_order)):
            raise ValueError("timing_resource_post_primary_binding_mismatch")
        self._authorization()
        authenticate(self.verify_receipt, "primary_accounting", primary.sha256)
        authenticate(self.verify_receipt, "timing_plan", plan.sha256)
        self._primary, self._plan = primary, plan
        self._snapshot()

    def _snapshot(self) -> TimingCashSnapshot:
        snapshot = self.snapshot_provider()
        snapshot = TimingCashSnapshot.model_validate_json(snapshot.model_dump_json())
        if (self._primary is None or snapshot.schedule_sha256 != self.schedule.sha256 or
                snapshot.primary_accounting_sha256 != self._primary.sha256 or
                snapshot.training_run_closeout_sha256 != self.schedule.prior_training_closeout_sha256 or
                snapshot.currency != self.schedule.currency or
                not utc(snapshot.captured_at) <= self.clock() < utc(snapshot.expires_at)):
            raise ValueError("timing_cash_snapshot_scope_or_freshness_mismatch")
        authenticate(self.verify_receipt, "timing_cash_snapshot", snapshot.sha256)
        training = snapshot.training.known_cash_micros + snapshot.training.unresolved_liability_micros
        declared = self.schedule.prior_known_training_cash_micros + self.schedule.prior_unknown_training_liability_micros
        if training > declared:
            raise ValueError("timing_training_liability_requires_new_authority")
        total = training
        for arm in PAID_ARMS:
            actual, bound = snapshot.arms[arm], self.schedule.arms[arm]
            if actual.authorization_id != bound.authorization_id or actual.cap_micros != bound.allocation_cap_micros:
                raise ValueError("timing_cash_allocation_mismatch")
            total += actual.known_cash_micros + actual.unresolved_liability_micros
        if total > self.schedule.total_campaign_authorized_cash_micros:
            raise ValueError("timing_combined_cash_exhausted")
        return snapshot

    def _request(self, request: TimingPhaseRequest):
        from m7.experiment.timing_contracts import TimingPhaseRequest
        request = TimingPhaseRequest.model_validate_json(request.model_dump_json())
        if self._primary is None or self._plan is None:
            raise ValueError("timing_resources_not_prepared")
        identity, arm = request.identity, request.identity.arm
        if arm not in self.authorization.warm_identity_sha256_by_arm:
            raise ValueError("timing_arm_not_warm_authorized")
        member, bootstrap = self.bundle.memberships[arm], self.bundle.bootstraps[arm]
        pins = {p.arm: p for p in self._plan.arm_pins}
        if (request.edition_sha256 != self._primary.edition_sha256 or
                request.primary_accounting_sha256 != self._primary.sha256 or request.plan_sha256 != self._plan.sha256 or
                request.population_sha256 != self._plan.population_sha256 or request.order_sha256 != self._plan.order_sha256 or
                identity.profile_sha256 != member.profile_sha256 or identity.launch_sha256 != member.launch_sha256 or
                identity.bootstrap_sha256 != member.bootstrap_sha256 or identity.session_id != bootstrap.session_id or
                identity.pin != pins[arm] or identity.primary_population_sha256 != self._plan.population_sha256 or
                identity.primary_order_sha256 != self._plan.order_sha256 or
                digest(identity.model_dump(mode="json")) != self.authorization.warm_identity_sha256_by_arm[arm]):
            raise ValueError("timing_resource_request_identity_changed")
        process = (identity.process_id, identity.process_start_identity, identity.backend_instance_id)
        if any(other != arm and (value[:2] == process[:2] or value[2] == process[2])
               for other, value in self._survivors.items()):
            raise ValueError("timing_survivor_process_or_backend_aliased")
        if arm in self._survivors and self._survivors[arm] != process:
            raise ValueError("timing_original_survivor_replaced")
        key = (arm, request.ordinal)
        if (key in self._namespaces and self._namespaces[key] != request.attempt_namespace or
                any(value == request.attempt_namespace and old != key for old, value in self._namespaces.items())):
            raise ValueError("timing_attempt_namespace_reuse_or_repair")
        authenticate(self.verify_receipt, "warm_backend_attestation", identity.attestation_sha256)
        self._authorization()
        self._survivors[arm] = process
        return request

    def qualify(self, request: TimingPhaseRequest) -> TimingResourceReceipt:
        request = self._request(request)
        snapshot = self._snapshot()
        arm, n = request.identity.arm, self.schedule.intended_records
        bound = self.schedule.arms.get(arm)
        retries, worst = (bound.max_retries, bound.worst_case_attempt_micros) if bound else (0, 0)
        if bound and snapshot.arms[arm].remaining_micros < (4 - request.ordinal) * n * worst * (1 + retries):
            raise ValueError("remaining_timing_passes_not_funded")
        self._namespaces[(arm, request.ordinal)] = request.attempt_namespace
        return TimingResourceReceipt(request_sha256=digest(request.model_dump(mode="json")),
            authorization_sha256=self.authorization.sha256, schedule_sha256=self.schedule.sha256,
            cash_snapshot_sha256=snapshot.sha256, primary_accounting_sha256=self._primary.sha256,
            plan_sha256=self._plan.sha256, arm=arm, ordinal=request.ordinal, attempt_namespace=request.attempt_namespace,
            maximum_logical_calls=n, maximum_backend_attempts=n * (1 + retries),
            worst_case_phase_cash_micros=n * worst * (1 + retries),
            cash_authorization_id=bound.authorization_id if bound else None,
            currency=self.schedule.currency,
            qualified_at=self.clock().isoformat(), expires_at=self.authorization.expires_at)

    def current(self, request: TimingPhaseRequest, receipt: TimingResourceReceipt) -> None:
        request = self._request(request)
        bound, n = self.schedule.arms.get(request.identity.arm), self.schedule.intended_records
        retries, worst = (bound.max_retries, bound.worst_case_attempt_micros) if bound else (0, 0)
        if (receipt.request_sha256 != digest(request.model_dump(mode="json")) or
                receipt.authorization_sha256 != self.authorization.sha256 or receipt.schedule_sha256 != self.schedule.sha256 or
                receipt.primary_accounting_sha256 != self._primary.sha256 or receipt.plan_sha256 != self._plan.sha256 or
                receipt.arm != request.identity.arm or receipt.ordinal != request.ordinal or
                receipt.attempt_namespace != request.attempt_namespace or receipt.currency != self.schedule.currency or
                receipt.maximum_logical_calls != n or receipt.maximum_backend_attempts != n * (1 + retries) or
                receipt.worst_case_phase_cash_micros != n * worst * (1 + retries) or
                receipt.cash_authorization_id != (bound.authorization_id if bound else None) or
                not utc(receipt.qualified_at) <= self.clock() < utc(receipt.expires_at)):
            raise ValueError("timing_resource_receipt_mismatch_or_expired")
        authenticate(self.verify_receipt, "timing_resource_receipt", receipt.sha256)
        # Do not require the ENTIRE phase bound again after each paid record.
        # Original qualification funds remaining passes; D6 reserves each call.
        self._snapshot()


class TimingResourcesHandoff(Boundary):
    """Canonical D7 plan/primary dictionaries are revalidated by their owner types.

    Lazy owner imports avoid a training/experiment package import cycle.
    """
    schema_version: Literal["TimingResourcesHandoff/v1"] = "TimingResourcesHandoff/v1"
    bundle: WorkerLaunchBundle
    plan: dict
    primary: dict
    schedule: TimingResourceSchedule
    authorization: TimingResourceAuthorization

    @property
    def sha256(self) -> str:
        return digest(self.model_dump(mode="json"))


class TimingHandoffPreparation(Boundary):
    schema_version: Literal["TimingHandoffPreparation/v1"] = "TimingHandoffPreparation/v1"
    handoff_sha256: Digest
    bundle_sha256: Digest
    schedule_sha256: Digest
    authorization_sha256: Digest
    primary_accounting_sha256: Digest
    plan_sha256: Digest
    prepared_at: str
    expires_at: str
    status: Literal["resource_handoff_qualified_no_phase_or_reopen"] = "resource_handoff_qualified_no_phase_or_reopen"
    measured_cost_micros: None = None


@dataclass(frozen=True)
class PreparedTimingResources:
    handoff: TimingResourcesHandoff
    authority: TimingResourceAuthority
    receipt: TimingHandoffPreparation


def validate_timing_handoff(handoff: TimingResourcesHandoff) -> dict:
    from m7.experiment.timing_contracts import IsolatedTimingPlan, PrimaryAccountingReceipt
    handoff = TimingResourcesHandoff.model_validate_json(handoff.model_dump_json())
    plan = IsolatedTimingPlan.model_validate_json(json.dumps(handoff.plan, allow_nan=False))
    primary = PrimaryAccountingReceipt.model_validate_json(json.dumps(handoff.primary, allow_nan=False))
    result = validate_timing_resources(handoff.bundle, plan, handoff.schedule)
    auth = handoff.authorization
    if (auth.schedule_sha256 != handoff.schedule.sha256 or auth.bundle_sha256 != handoff.bundle.sha256 or
            auth.campaign_sha256 != handoff.bundle.campaign_sha256 or auth.primary_accounting_sha256 != primary.sha256 or
            auth.edition_sha256 != primary.edition_sha256 or auth.plan_sha256 != plan.sha256 or
            auth.profile_sha256 != handoff.bundle.profile_sha256 or auth.currency != handoff.schedule.currency or
            auth.cash_authorization_sha256 != handoff.bundle.campaign.resources.cost_authorization_sha256 or
            auth.launch_sha256_by_arm != {a: m.launch_sha256 for a, m in handoff.bundle.memberships.items()} or
            primary.population_sha256 != plan.population_sha256 or primary.intended_cells != 4 * len(plan.record_order)):
        raise ValueError("timing_handoff_post_primary_bindings_invalid")
    return {**result, "handoff_sha256": handoff.sha256,
            "status": "timing_handoff_structural_only_not_authorized", "phase_started": False, "heldout_reopened": False}


def prepare_timing_handoff(handoff: TimingResourcesHandoff, *, host: CampaignHost,
                           snapshot_provider: Callable[[], TimingCashSnapshot],
                           clock: Callable[[], datetime] = now_utc) -> PreparedTimingResources:
    """Explicit future host qualification, never calls a session/phase or D4 open."""
    from m7.experiment.timing_contracts import IsolatedTimingPlan, PrimaryAccountingReceipt
    handoff = TimingResourcesHandoff.model_validate_json(handoff.model_dump_json())
    validate_timing_handoff(handoff)
    if host is None or snapshot_provider is None:
        raise ValueError("timing_real_host_and_cash_snapshot_required")
    authenticate(host.verify_receipt, "timing_resources_handoff", handoff.sha256)
    # Prelaunch prepared-policy requalification is not running-process proof.
    prepare_launch_bundle(handoff.bundle, host=host, clock=clock)
    plan = IsolatedTimingPlan.model_validate_json(json.dumps(handoff.plan, allow_nan=False))
    primary = PrimaryAccountingReceipt.model_validate_json(json.dumps(handoff.primary, allow_nan=False))
    authority = TimingResourceAuthority(handoff.bundle, handoff.schedule, handoff.authorization,
        verify_receipt=host.verify_receipt, snapshot_provider=snapshot_provider, clock=clock)
    authority.prepare(primary, plan)
    receipt = TimingHandoffPreparation(handoff_sha256=handoff.sha256, bundle_sha256=handoff.bundle.sha256,
        schedule_sha256=handoff.schedule.sha256, authorization_sha256=handoff.authorization.sha256,
        primary_accounting_sha256=primary.sha256, plan_sha256=plan.sha256,
        prepared_at=clock().isoformat(), expires_at=handoff.authorization.expires_at)
    return PreparedTimingResources(handoff, authority, receipt)


MAX_TIMING_HANDOFF_BYTES = 20_000_000


def load_timing_handoff(path: Path) -> TimingResourcesHandoff:
    from m7.data.filesystem import checked_path, strict_json
    path = checked_path(path)
    if not path.is_file() or path.stat().st_size > MAX_TIMING_HANDOFF_BYTES:
        raise ValueError("timing_handoff_size_limit")
    with path.open("rb") as stream:
        raw = stream.read(MAX_TIMING_HANDOFF_BYTES + 1)
    if len(raw) > MAX_TIMING_HANDOFF_BYTES:
        raise ValueError("timing_handoff_size_limit")
    value = strict_json(raw)
    if type(value) is not dict:
        raise ValueError("timing_handoff_object_required")
    if value.get("schema_version") == "PreparedTimingResourcesExport/v1":
        from .validation import shape
        shape(value, {"schema_version", "handoff", "handoff_sha256", "preparation", "preparation_sha256"})
        handoff = TimingResourcesHandoff.model_validate_json(json.dumps(value["handoff"], allow_nan=False))
        prep = TimingHandoffPreparation.model_validate_json(json.dumps(value["preparation"], allow_nan=False))
        if (value["handoff_sha256"] != handoff.sha256 or value["preparation_sha256"] != digest(prep.model_dump(mode="json")) or
                prep.handoff_sha256 != handoff.sha256 or prep.bundle_sha256 != handoff.bundle.sha256 or
                prep.schedule_sha256 != handoff.schedule.sha256 or prep.authorization_sha256 != handoff.authorization.sha256 or
                prep.primary_accounting_sha256 != handoff.authorization.primary_accounting_sha256 or
                prep.plan_sha256 != handoff.authorization.plan_sha256 or
                not utc(handoff.authorization.issued_at) <= utc(prep.prepared_at) < utc(prep.expires_at) or
                utc(prep.expires_at) != utc(handoff.authorization.expires_at)):
            raise ValueError("prepared_timing_handoff_digest_mismatch")
    else:
        handoff = TimingResourcesHandoff.model_validate_json(json.dumps(value, allow_nan=False))
    validate_timing_handoff(handoff)
    return handoff  # Historical qualification is never current execution authority.


def export_timing_handoff(prepared: PreparedTimingResources, directory: Path, *, host: CampaignHost,
                          snapshot_provider: Callable[[], TimingCashSnapshot]) -> dict:
    if prepared.handoff.sha256 != prepared.receipt.handoff_sha256:
        raise ValueError("prepared_timing_handoff_mutated")
    current = prepare_timing_handoff(prepared.handoff, host=host, snapshot_provider=snapshot_provider)
    value = {"schema_version": "PreparedTimingResourcesExport/v1",
        "handoff": current.handoff.model_dump(mode="json"), "handoff_sha256": current.handoff.sha256,
        "preparation": current.receipt.model_dump(mode="json"),
        "preparation_sha256": digest(current.receipt.model_dump(mode="json"))}
    if len(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()) + 1 > MAX_TIMING_HANDOFF_BYTES:
        raise ValueError("timing_handoff_size_limit")
    from m7.data.filesystem import checked_path
    directory = checked_path(directory)
    for cfg in (current.handoff.bundle.campaign.selected.base, current.handoff.bundle.campaign.selected.finetuned):
        if directory.is_relative_to(checked_path(cfg.artifact_root)):
            raise ValueError("timing_handoff_must_be_outside_worker_assets")
    _write_json(directory / (current.handoff.bundle.campaign.campaign_id + ".timing.json"), value)
    return {"status": "immutable_timing_resource_handoff_written_no_execution",
            "handoff_sha256": current.handoff.sha256, "phase_started": False, "heldout_reopened": False}
