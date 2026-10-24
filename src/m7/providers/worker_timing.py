"""Parent timing continuation. No execution on import; no default authority."""
from typing import Protocol
from m7.experiment.models import commitment
from m7.experiment.timing_contracts import TimingPhasePermit, TimingPhaseRequest, WarmBackendIdentity
from .contracts import AdapterFault, config_digest
from .worker_phase import member_rows
from .worker_wire import TimingCommand
from .worker_profile import worker_profile_digest


class WarmBackendAttestor(Protocol):
    """Actual trusted-host observation; no child-self-report-only implementation.

    Return an externally authenticated warm_backend_attestation receipt digest
    binding every claim field and original primary activity. The host owns its
    process/backend observation channel; this source never fabricates that proof.
    """
    def __call__(self, claim: dict, physical_calls: int) -> str: ...


class WarmSessionMixin:
    def _init_timing(self, authority, attestor):
        self._timing_authority, self._warm_attestor = authority, attestor
        self._timing_verifier = None
        self._warm_identity = None
        self._primary_order = []
        self._timing_request = self._timing_permit = None
        self._timing_active = False
        self._timing_ordinal = self._timing_cursor = 0
        self._timing_namespaces = set()
        self._timing_scope = None
        self._warm_last_calls = 0
        self._original_process = (self.process.pid, self.process.start_identity)

    def bind_timing_authority(self, authority) -> None:
        """Bind post-primary authority once; never changes preregistered plan.

        D7 constructs authority only after obtaining real surviving identities.
        No reset, request, authority consumption or native operation occurs here.
        """
        with self._lock:
            if (authority is None or self._timing_authority is not None
                    or self._timing_ordinal or self._closed
                    or self.bootstrap.timing_plan_sha256 is None
                    or any(not callable(getattr(authority, name, None))
                           for name in ('prepare', 'authorize', 'current', 'finish', 'verify_receipt'))):
                raise AdapterFault('permit_required')
            self._timing_authority = authority

    def _phase_exchange(self, kind, request=None, permit=None):
        self._seq += 1
        reply = self._exchange(TimingCommand(kind=kind, session_id=self.bootstrap.session_id,
            seq=self._seq, request=request, permit=permit))
        expected = {'timing_identity': 'timing_identity', 'timing_begin': 'timing_begun',
                    'timing_finish': 'timing_finished'}[kind]
        if reply.status != expected or reply.events:
            raise AdapterFault('unavailable')
        return reply

    def _timing_current(self):
        self._guard()
        if self._timing_verifier is None or self._timing_request is None or self._timing_permit is None:
            raise AdapterFault('permit_required')
        # Canonical D4 live bridge calls current(request,permit), including
        # revocation/native/expiry/resource checks, for this consumed receipt.
        for kind, digest in (('timing_custody_continuation', self._timing_permit.custody_receipt_sha256),
                             ('timing_resource_receipt', self._timing_permit.resource_receipt_sha256)):
            if self._timing_verifier(kind, digest) is not True:
                raise AdapterFault('permit_required')
        if self._timing_authority is not None:
            self._timing_authority.current(self._timing_request, self._timing_permit)

    def timing_identity(self) -> WarmBackendIdentity:
        with self._lock:
            try:
                self._guard()
                if (self.bootstrap.timing_plan_sha256 is None or self._warm_attestor is None
                        or self._population is None or list(self._population) != self._primary_order
                        or (self.process.pid, self.process.start_identity) != self._original_process):
                    raise AdapterFault('unavailable')
                if self._timing_active:
                    self._timing_current()
                state = self._phase_exchange('timing_identity').backend_state
                rows = member_rows(self._population)
                if (state is None or state.order_sha256 != commitment(rows)
                        or state.physical_calls < self._warm_last_calls
                        or state.order_sha256 != self.bootstrap.timing_order_sha256
                        or state.population_sha256 != commitment(sorted(rows, key=lambda r: r['record_id']))):
                    raise AdapterFault('invalid_output')
                self._warm_last_calls = state.physical_calls
                claim = dict(arm=self.arm, session_id=self.bootstrap.session_id,
                    process_id=self.process.pid, process_start_identity=self.process.start_identity,
                    backend_instance_id=state.backend_instance_id,
                    profile_sha256=worker_profile_digest(self.profile), launch_sha256=self._approved_launch_sha256,
                    bootstrap_sha256=config_digest(self.bootstrap), pin=self.bootstrap.pin.model_dump(mode='json'),
                    primary_population_sha256=state.population_sha256, primary_order_sha256=state.order_sha256)
                if self._warm_identity is None:
                    # Trusted host must observe and authenticate actual original
                    # process/backend lineage. A digest of child testimony is NOT proof.
                    digest = self._warm_attestor(claim, state.physical_calls)
                    self._warm_identity = WarmBackendIdentity(**claim, attestation_sha256=digest)
                expected = WarmBackendIdentity(**claim, attestation_sha256=self._warm_identity.attestation_sha256)
                if (expected != self._warm_identity or self.guard.verify_receipt(
                        'warm_backend_attestation', expected.attestation_sha256) is not True):
                    raise AdapterFault('permit_required')
                return expected
            except BaseException:
                self._abort()
                raise AdapterFault('unavailable') from None

    def begin_timing_phase(self, request: TimingPhaseRequest, permit: TimingPhasePermit, *,
                           verify_receipt=None) -> None:
        with self._lock:
            try:
                request = TimingPhaseRequest.model_validate_json(request.model_dump_json())
                permit = TimingPhasePermit.model_validate_json(permit.model_dump_json())
                scope = request.model_dump(mode='json', exclude={'ordinal', 'attempt_namespace'})
                if (self._timing_active or request.ordinal != self._timing_ordinal + 1
                        or self._timing_scope is not None and scope != self._timing_scope
                        or request.identity != self.timing_identity()
                        or request.plan_sha256 != self.bootstrap.timing_plan_sha256
                        or request.order_sha256 != self.bootstrap.timing_order_sha256
                        or request.population_sha256 != request.identity.primary_population_sha256
                        or request.attempt_namespace in self._timing_namespaces
                        or request.attempt_namespace != commitment({'primary': request.primary_accounting_sha256,
                            'plan': request.plan_sha256, 'identity': request.identity.model_dump(mode='json'),
                            'ordinal': request.ordinal})
                        or permit.request_sha256 != commitment(request.model_dump(mode='json'))):
                    raise AdapterFault('permit_required')
                for kind, digest in (('timing_custody_continuation', permit.custody_receipt_sha256),
                                     ('timing_resource_receipt', permit.resource_receipt_sha256)):
                    verifier = (verify_receipt if verify_receipt is not None else
                                getattr(self._timing_authority, 'verify_receipt', None))
                    # D4 authenticates its ORIGINAL custody-chain consumption;
                    # do not recursively replace the lifecycle/native verifier.
                    if not callable(verifier) or verifier(kind, digest) is not True:
                        raise AdapterFault('permit_required')
                self._timing_verifier = verifier
                self._timing_request, self._timing_permit = request, permit
                self._timing_current()  # Gate has durably consumed in D7 BEFORE this call.
                # Burn before messaging: uncertain reset is never resumable.
                self._timing_namespaces.add(request.attempt_namespace)
                self._timing_scope = scope
                self._timing_ordinal = request.ordinal
                self._phase_exchange('timing_begin', request, permit)
                self._cache, self._cached_events, self._budget_rejected = {}, {}, set()
                self.last_attempts = ()
                self._timing_cursor, self._timing_active = 0, True
                # _attempts/_pending/ledgers NEVER reset: unknown costs survive.
            except BaseException:
                self._abort()
                raise AdapterFault('unavailable') from None

    def _timing_before(self, record):
        if self._timing_active:
            self._timing_current()
            rows = list(self._population.items())
            if (self._timing_cursor >= len(rows)
                    or rows[self._timing_cursor] != (record.record_id, record.content_sha256)):
                raise AdapterFault('invalid_output')
        elif self._timing_ordinal:
            raise AdapterFault('permit_required')

    def _timing_terminal(self, record):
        if self._timing_active:
            self._timing_cursor += 1
        elif record.record_id not in self._primary_order:
            self._primary_order.append(record.record_id)

    def finish_timing_phase(self, request: TimingPhaseRequest) -> None:
        with self._lock:
            try:
                self._timing_current()
                if (not self._timing_active or request != self._timing_request
                        or self._timing_cursor != len(self._population)):
                    raise AdapterFault('invalid_output')
                self._phase_exchange('timing_finish', request)
                self._timing_active = False
            except BaseException:
                self._abort()
                raise AdapterFault('unavailable') from None
