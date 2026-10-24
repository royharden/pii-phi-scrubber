"""Child-only phase state. No authority, paths, loading or process operations."""
from uuid import uuid4

from m7.detectors.attempts import AttemptController
from m7.detectors.registry import DetectorAdapter, RegexAdapter
from m7.experiment.models import commitment
from .contracts import AdapterFault, config_digest
from .worker_wire import BackendState


def member_rows(population):
    return [{"record_id": key, "content_sha256": value} for key, value in population.items()]


class WorkerPhases:
    def __init__(self, bootstrap, adapter):
        self.bootstrap, self.adapter = bootstrap, adapter
        self.original_backend = adapter.backend if isinstance(adapter, DetectorAdapter) else adapter
        self.primary = {}
        self.request = None
        self.ordinal = 0
        self.cursor = 0
        self.identity = None
        self.regex_id = "regex-" + uuid4().hex
        self.regex_calls = 0
        self.scope = None

    def state(self, population):
        if (self.bootstrap.timing_plan_sha256 is None or self.primary != population
                or list(self.primary) != list(population)):
            raise AdapterFault("unavailable")
        if isinstance(self.adapter, DetectorAdapter):
            if self.adapter.backend is not self.original_backend:
                raise AdapterFault("unavailable")
            backend_id, calls = self.adapter.backend.warm_state()
        elif isinstance(self.adapter, RegexAdapter):
            backend_id, calls = self.regex_id, self.regex_calls
        else:
            raise AdapterFault("unavailable")
        rows = member_rows(self.primary)
        state = BackendState(backend_instance_id=backend_id, physical_calls=calls,
            population_sha256=commitment(sorted(rows, key=lambda r: r['record_id'])),
            order_sha256=commitment(rows))
        if state.order_sha256 != self.bootstrap.timing_order_sha256:
            raise AdapterFault("permit_required")
        if self.identity is not None and self.identity != backend_id:
            raise AdapterFault("unavailable")
        self.identity = backend_id
        return state

    def begin(self, request, permit, population):
        state = self.state(population)
        identity = request.identity
        scope = request.model_dump(mode='json', exclude={'ordinal', 'attempt_namespace'})
        expected_ns = commitment({'primary': request.primary_accounting_sha256,
            'plan': request.plan_sha256, 'identity': identity.model_dump(mode='json'),
            'ordinal': request.ordinal})
        if (self.request is not None or request.ordinal != self.ordinal + 1
                or self.scope is not None and scope != self.scope
                or request.plan_sha256 != self.bootstrap.timing_plan_sha256
                or request.order_sha256 != state.order_sha256
                or request.population_sha256 != state.population_sha256
                or identity.session_id != self.bootstrap.session_id
                or identity.backend_instance_id != state.backend_instance_id
                or identity.arm != self.bootstrap.pin.arm
                or identity.bootstrap_sha256 != config_digest(self.bootstrap)
                or identity.pin.model_dump() != self.bootstrap.pin.model_dump()
                or identity.primary_order_sha256 != state.order_sha256
                or identity.primary_population_sha256 != state.population_sha256
                or permit.request_sha256 != commitment(request.model_dump(mode='json'))
                or request.attempt_namespace != expected_ns):
            raise AdapterFault("permit_required")
        if isinstance(self.adapter, DetectorAdapter):
            old = self.adapter.controller
            if old is None:
                raise AdapterFault("unavailable")
            # Retain backend and original ledger; reset logical caches only.
            self.adapter.controller = AttemptController(run_id=old.run_id, arm=old.arm,
                model_id=old.model_id, policy=old.policy, ledger=old.ledger,
                cancelled=old.cancelled, receipt_resolver=old.receipt_resolver,
                diagnostic_sink=old.diagnostic_sink, attempt_namespace=request.attempt_namespace)
        self.request, self.cursor = request, 0
        self.scope = scope
        self.ordinal = request.ordinal

    def before_record(self, record, population):
        if self.ordinal and self.request is None:
            raise AdapterFault("permit_required")
        if self.request is not None:
            self.state(population)
            rows = list(population.items())
            if self.cursor >= len(rows) or rows[self.cursor] != (record.record_id, record.content_sha256):
                raise AdapterFault("invalid_output")

    def terminal(self, record):
        if isinstance(self.adapter, RegexAdapter):
            self.regex_calls += 1
        if self.request is None:
            if record.record_id not in self.primary:
                self.primary[record.record_id] = record.content_sha256
        else:
            self.cursor += 1

    def finish(self, request, population):
        self.state(population)
        if request != self.request or self.cursor != len(population):
            raise AdapterFault("invalid_output")
        self.request = None
