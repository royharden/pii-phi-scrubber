"""Authenticated post-primary timing continuation. No activation on import.

The original custody journal is the sole durable consume authority. This module
never opens a corpus, releases labels, resets a worker, or calls a detector.
"""
from __future__ import annotations

from typing import Callable, Protocol, TYPE_CHECKING

from m7.experiment.models import LockedEdition
from m7.experiment.timing_contracts import (
    IsolatedTimingPlan, PrimaryAccountingReceipt, TimingPhasePermit,
    TimingPhaseRequest, WarmBackendIdentity,
)

from .lifecycle import CustodyLifecycle, _states, utc
from .provenance import commitment
from .timing_models import CustodyTimingAuthorization, TimingPhaseConsumed, TimingPhaseTerminal

if TYPE_CHECKING:
    from m7.training.timing_resources import TimingResourceReceipt


class TimingResourceGate(Protocol):
    def prepare(self, primary: PrimaryAccountingReceipt, plan: IsolatedTimingPlan) -> None: ...
    def qualify(self, request: TimingPhaseRequest) -> TimingResourceReceipt: ...
    def current(self, request: TimingPhaseRequest, receipt: TimingResourceReceipt) -> None: ...


class CustodyTimingAuthority:
    """D7 TimingContinuationAuthority implementation, with mandatory D5/D4 hosts.

    verify_process(identity) MUST invoke the current native postlaunch verifier
    on that exact PID/start identity/P/L/bootstrap and approved launch spec. A
    signature, prelaunch policy check, worker assertion or cached proof alone is
    insufficient. No default verifier or permissive native fallback exists.

    lifecycle.verifier('primary_accounting', digest) must authenticate immutable
    accounting from the ORIGINAL closed primary journal, its head, complete
    terminal population/quality and zero unresolved begins. An honestly settled
    negative/uncertain terminal outcome is allowed and remains in that receipt.
    It is not an independent experiment acceptance verdict.

    One authority instance owns its live permits. Reconstruction can inspect or
    record an explicit abort, but cannot resume messages or certify completion
    of a phase whose in-memory ownership was lost.
    """
    def __init__(self, lifecycle: CustodyLifecycle, edition: LockedEdition,
                 authorization: CustodyTimingAuthorization, *, resources: TimingResourceGate,
                 verify_process: Callable[[WarmBackendIdentity], bool]):
        self.lifecycle = lifecycle
        self.edition = LockedEdition.model_validate_json(edition.model_dump_json())
        self.authorization = CustodyTimingAuthorization.model_validate_json(authorization.model_dump_json())
        if not callable(verify_process) or resources is None:
            raise ValueError('timing_actual_process_and_resource_verifiers_required')
        self.resources, self.verify_process = resources, verify_process
        self._primary: PrimaryAccountingReceipt | None = None
        self._plan: IsolatedTimingPlan | None = None
        self._live: dict[str, tuple[TimingPhasePermit, TimingResourceReceipt]] = {}
        self._requests: dict[str, TimingPhaseRequest] = {}

    def _context(self, events):
        host, auth, edition = self.lifecycle, self.authorization, self.edition
        state = _states(events).get(edition.edition_id)
        if state is None or state.opened is None:
            raise ValueError('timing_original_open_required_no_fresh_open')
        release = host._match_edition(edition, state)
        host._current(auth.issued_at, auth.expires_at)
        if (auth.edition_id != edition.edition_id or auth.run_id != edition.run_id
                or auth.edition_sha256 != edition.sha256
                or auth.custody_release_sha256 != commitment(release)
                or auth.experiment_plan_sha256 != edition.plan_sha256
                or auth.corpus_manifest_sha256 != edition.corpus_manifest_sha256
                or auth.selection_lock_sha256 != edition.selection_lock_sha256
                or auth.population_sha256 != release.population_sha256
                or auth.arm_pins_sha256 != commitment(edition.arm_pins)
                or auth.worker_profile_sha256 != release.worker_policy_sha256
                or auth.isolation_capability_sha256 != release.isolation_capability_sha256
                or auth.filesystem_policy_sha256 != release.filesystem_policy_sha256
                or utc(auth.issued_at) < utc(state.opened.opened_at)
                or utc(auth.expires_at) > utc(edition.expires_at)):
            raise ValueError('timing_original_authority_binding_mismatch')
        host._verify('custody_timing_authorization', auth.sha256)
        host._verify('evaluation_authorization', edition.execution_authorization_sha256)
        if self._primary is not None:
            host._verify('primary_accounting', self._primary.sha256)
        prior = self._receipts(events)
        starts = [r for r in prior if isinstance(r, TimingPhaseConsumed)]
        if any(r.authorization_sha256 != auth.sha256 for r in starts):
            raise ValueError('timing_authorization_cannot_replace_original_consumption')
        return state

    def _receipts(self, events):
        return tuple(e.receipt for e in events if e.receipt.edition_id == self.edition.edition_id
                     and isinstance(e.receipt, (TimingPhaseConsumed, TimingPhaseTerminal)))

    def prepare(self, primary: PrimaryAccountingReceipt, plan: IsolatedTimingPlan) -> None:
        primary = PrimaryAccountingReceipt.model_validate_json(primary.model_dump_json())
        plan = IsolatedTimingPlan.model_validate_json(plan.model_dump_json())
        auth, edition = self.authorization, self.edition
        if (primary.sha256 != auth.primary_accounting_sha256
                or primary.edition_sha256 != edition.sha256
                or primary.population_sha256 != auth.population_sha256
                or primary.intended_cells != len(edition.population) * len(edition.arm_pins)
                or plan.sha256 != auth.timing_plan_sha256 or plan.sha256 != edition.timing_plan_sha256
                or plan.edition_id != edition.edition_id or plan.run_id != edition.run_id
                or plan.population_sha256 != auth.population_sha256
                or plan.order_sha256 != auth.order_sha256 or plan.arm_pins != edition.arm_pins
                or sorted(plan.record_order, key=lambda r: r.record_id) != list(edition.population)):
            raise ValueError('timing_closed_primary_or_preregistered_plan_mismatch')
        if self._primary is not None and (self._primary != primary or self._plan != plan):
            raise ValueError('timing_prepare_cannot_change_primary_or_plan')
        with self.lifecycle.journal.writer():
            events = self.lifecycle.journal.events()
            self._context(events)
            self.lifecycle._verify('primary_accounting', primary.sha256)
            prior = self._receipts(events)
            ended = {r.consumed_sha256 for r in prior if isinstance(r, TimingPhaseTerminal)}
            if any(commitment(r) not in ended for r in prior if isinstance(r, TimingPhaseConsumed)):
                raise ValueError('timing_uncertain_phase_requires_original_journal_investigation')
            self.resources.prepare(primary, plan)
            # Store only after all authentication/qualification has succeeded.
            self._primary, self._plan = primary, plan

    def _request(self, request: TimingPhaseRequest, events) -> TimingPhaseRequest:
        request = TimingPhaseRequest.model_validate_json(request.model_dump_json())
        self._context(events)
        if self._primary is None or self._plan is None:
            raise ValueError('timing_prepare_required')
        auth, identity, plan = self.authorization, request.identity, self._plan
        pins = {p.arm: p for p in auth.backends}
        pin = pins.get(identity.arm)
        arm_pin = next(p for p in self.edition.arm_pins if p.arm == identity.arm)
        if (request.edition_sha256 != self.edition.sha256
                or request.primary_accounting_sha256 != self._primary.sha256
                or request.plan_sha256 != plan.sha256
                or request.population_sha256 != plan.population_sha256
                or request.order_sha256 != plan.order_sha256
                or identity.primary_population_sha256 != plan.population_sha256
                or identity.primary_order_sha256 != plan.order_sha256
                or identity.pin != arm_pin or identity.pin.arm != identity.arm
                or identity.profile_sha256 != auth.worker_profile_sha256
                or pin is None or pin.identity_sha256 != commitment(identity)
                or pin.launch_sha256 != identity.launch_sha256):
            raise ValueError('timing_original_warm_identity_or_request_mismatch')
        namespace = commitment({'primary': self._primary.sha256, 'plan': plan.sha256,
            'identity': identity.model_dump(mode='json'), 'ordinal': request.ordinal})
        if request.attempt_namespace != namespace:
            raise ValueError('timing_parent_attempt_namespace_mismatch')
        self.lifecycle._verify('warm_backend_attestation', identity.attestation_sha256)
        if self.verify_process(identity) is not True:
            raise ValueError('timing_current_exact_native_process_proof_required')
        return request

    def authorize(self, request: TimingPhaseRequest) -> TimingPhasePermit:
        from m7.training.timing_resources import TimingResourceReceipt
        with self.lifecycle.journal.writer():
            events = self.lifecycle.journal.events()
            request = self._request(request, events)
            resource = self.resources.qualify(request)
            resource = TimingResourceReceipt.model_validate_json(resource.model_dump_json())
            self._resource(request, resource)
            self.resources.current(request, resource)
            identity, auth = request.identity, self.authorization
            receipt = TimingPhaseConsumed(edition_id=self.edition.edition_id, run_id=self.edition.run_id,
                edition_sha256=self.edition.sha256, custody_release_sha256=auth.custody_release_sha256,
                authorization_sha256=auth.sha256, primary_accounting_sha256=request.primary_accounting_sha256,
                timing_plan_sha256=request.plan_sha256, request_sha256=commitment(request),
                resource_receipt_sha256=resource.sha256, arm=identity.arm, ordinal=request.ordinal,
                attempt_namespace=request.attempt_namespace, backend_identity_sha256=commitment(identity),
                worker_profile_sha256=identity.profile_sha256, launch_sha256=identity.launch_sha256,
                consumed_at=self.lifecycle._now(), expires_at=min(
                    (auth.expires_at, resource.expires_at), key=utc))
            self.lifecycle._commit(receipt, events)
            permit = TimingPhasePermit(request_sha256=commitment(request),
                custody_receipt_sha256=commitment(receipt), resource_receipt_sha256=resource.sha256)
            self._live[commitment(request)] = (permit, resource)
            self._requests[commitment(request)] = request
            return permit

    def _resource(self, request, resource) -> None:
        if (resource.request_sha256 != commitment(request)
                or resource.authorization_sha256 != self.authorization.resource_authorization_sha256
                or resource.primary_accounting_sha256 != request.primary_accounting_sha256
                or resource.plan_sha256 != request.plan_sha256
                or resource.arm != request.identity.arm or resource.ordinal != request.ordinal
                or resource.attempt_namespace != request.attempt_namespace
                or self._plan is None or resource.maximum_logical_calls != len(self._plan.record_order)):
            raise ValueError('timing_resource_receipt_binding_mismatch')
        self.lifecycle._current(resource.qualified_at, resource.expires_at)

    def current(self, request: TimingPhaseRequest, permit: TimingPhasePermit) -> None:
        permit = TimingPhasePermit.model_validate_json(permit.model_dump_json())
        with self.lifecycle.journal.writer():
            events = self.lifecycle.journal.events()
            request = self._request(request, events)
            live = self._live.get(commitment(request))
            if live is None or live[0] != permit:
                raise ValueError('timing_live_original_permit_required_no_recovery_replay')
            starts = [r for r in self._receipts(events) if isinstance(r, TimingPhaseConsumed)
                      and commitment(r) == permit.custody_receipt_sha256]
            ended = {r.consumed_sha256 for r in self._receipts(events) if isinstance(r, TimingPhaseTerminal)}
            if (len(starts) != 1 or commitment(starts[0]) in ended
                    or starts[0].request_sha256 != commitment(request)
                    or starts[0].resource_receipt_sha256 != permit.resource_receipt_sha256):
                raise ValueError('timing_unfinished_original_consumption_required')
            self._resource(request, live[1])
            self.resources.current(request, live[1])

    def verify_receipt(self, kind: str, digest: str) -> bool:
        """D7/D6 bridge: authenticate our live permit, delegate other kinds.

        Wire this into the evaluator/parent verifier, not back into the lifecycle
        verifier itself (which is the independent trusted receipt source).
        """
        if kind != 'timing_custody_continuation':
            return self.lifecycle.verify_release_receipt(kind, digest)
        matches = [(key, live) for key, live in self._live.items()
                   if live[0].custody_receipt_sha256 == digest]
        if len(matches) != 1:
            return False
        key, live = matches[0]
        request = self._requests.get(key)
        if request is None:
            return False
        try:
            self.current(request, live[0])
        except Exception:
            return False
        return True

    def finish(self, request: TimingPhaseRequest, *, completed: bool) -> None:
        request = TimingPhaseRequest.model_validate_json(request.model_dump_json())
        if type(completed) is not bool:
            raise ValueError('timing_terminal_outcome_must_be_boolean')
        # Never let revocation/expiry prevent an honest abort from being recorded.
        # Completion requires fresh guards and live ownership; abort grants no work.
        live = self._live.get(commitment(request))
        if completed:
            if live is None:
                raise ValueError('timing_lost_ownership_requires_investigation_not_completion')
            self.current(request, live[0])
        with self.lifecycle.journal.writer():
            events = self.lifecycle.journal.events()
            _states(events)
            if completed:
                self._request(request, events)
            starts = [r for r in self._receipts(events) if isinstance(r, TimingPhaseConsumed)
                      and r.request_sha256 == commitment(request)]
            if len(starts) != 1 or starts[0].authorization_sha256 != self.authorization.sha256:
                raise ValueError('timing_original_consumption_required_for_terminal')
            self.lifecycle._commit(TimingPhaseTerminal(edition_id=self.edition.edition_id,
                run_id=self.edition.run_id, consumed_sha256=commitment(starts[0]),
                request_sha256=commitment(request), arm=request.identity.arm, ordinal=request.ordinal,
                outcome='completed' if completed else 'aborted', finished_at=self.lifecycle._now()), events)
            self._live.pop(commitment(request), None)
            self._requests.pop(commitment(request), None)
