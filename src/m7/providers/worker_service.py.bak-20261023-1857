"""Record-only stdio service source. Calling serve_worker is explicit execution.

No path, bundle, gold, credentials, module name or ledger location is accepted by
the command wire. Local artifact paths are in the preapproved bootstrap only.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import json
from time import monotonic
from typing import BinaryIO

from m7.contracts import LogRecord, Prediction
from m7.detectors.attempts import Ledger
from m7.detectors.registry import build_registry
from m7.ledger import BudgetExceeded
from .worker_wire import (
    AttemptEvent, BrokerReply, Command, ControlCommand, InitCommand, MAX_BOOTSTRAP_BYTES,
    MAX_RECORD_BYTES, MAX_REPLY_BYTES, ReconcileRequest, RecordCommand, ReserveRequest,
    SealCommand, WorkerBootstrap, WorkerReply, decode_line, encode_line,
)


def population_digest(population: Mapping[str, str]) -> str:
    return hashlib.sha256(json.dumps(sorted(population.items()), separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


class _Discard:
    """Drop Python/library prints rather than contaminate protocol or persist text."""
    encoding = "utf-8"

    @property
    def buffer(self):
        return self

    def write(self, value):
        return len(value)

    def flush(self):
        return None

    def isatty(self):
        return False


class RemoteLedger:
    """No SQLite/path access in child. Parent decides atomic authorization/cash."""

    def __init__(self, bootstrap: WorkerBootstrap, arm: str, source: BinaryIO, output: BinaryIO):
        self.bootstrap, self.arm = bootstrap, arm
        self.source, self.output = source, output
        policy = bootstrap.policies[arm]
        self.authorization_id, self.cap = policy.authorization_id, policy.authorization_cap_micros
        self.seq, self.rpc_seq = 0, 0

    def _rpc(self, request) -> BrokerReply:
        self.output.write(encode_line(request, limit=MAX_REPLY_BYTES))
        self.output.flush()
        raw = self.source.readline(MAX_RECORD_BYTES + 1)
        reply = decode_line(raw, BrokerReply, limit=MAX_RECORD_BYTES)
        if (reply.session_id != self.bootstrap.session_id or reply.seq != self.seq
                or reply.rpc_seq != self.rpc_seq):
            raise ValueError("broker_identity_mismatch")
        return reply

    def reserve(self, attempt_id: str, worst_case_micros: int, *, category: str) -> None:
        self.rpc_seq += 1
        reply = self._rpc(ReserveRequest(session_id=self.bootstrap.session_id, seq=self.seq,
            rpc_seq=self.rpc_seq, attempt_id=attempt_id, arm=self.arm,
            worst_case_micros=worst_case_micros, category=category))
        if reply.status == "budget_rejected":
            raise BudgetExceeded("authorization_cap")
        if reply.status != "ok":
            raise ValueError("broker_reservation_unavailable")

    def reconcile(self, attempt_id: str, *, actual_micros: int | None, state: str,
                  usage_units: int | None = None, receipt_id: str | None = None) -> None:
        self.rpc_seq += 1
        reply = self._rpc(ReconcileRequest(session_id=self.bootstrap.session_id, seq=self.seq,
            rpc_seq=self.rpc_seq, attempt_id=attempt_id, arm=self.arm, actual_micros=actual_micros,
            state=state, usage_units=usage_units, receipt_id=receipt_id))
        if reply.status != "ok":
            # In particular, unsupported child cash claims stay unknown in parent.
            raise ValueError("broker_reconciliation_unavailable")


RegistryFactory = Callable[[WorkerBootstrap, Mapping[str, Ledger], Callable[[dict], None],
                            Callable[[], bool]], Mapping[str, object]]


def local_registry(bootstrap: WorkerBootstrap, ledgers, sink, cancelled):
    """Built-in local/regex worker. Frontier requires a separately approved factory.

    Dependency injection is source-owned, never a module/import path from the wire.
    A frontier factory must supply approved counter/transport without custody reads.
    """
    if bootstrap.pin.arm == "frontier":
        raise ValueError("approved_frontier_worker_factory_required")
    return build_registry(bootstrap.configs, bootstrap.permits, run_id=bootstrap.run_id,
        policies=bootstrap.policies, ledgers=ledgers, diagnostic_sink=sink,
        cancelled=cancelled, include_regex=bootstrap.pin.arm == "regex", allow_execution=True)


def serve_worker(source: BinaryIO, output: BinaryIO, *, registry_factory: RegistryFactory = local_registry) -> int:
    """Synchronous bounded worker loop; parent timeout/lifetime enforces termination.

    Only the verified parent may feed stdin. This function does not certify native
    isolation; activation belongs to launch_worker and the platform capability.
    """
    with redirect_stdout(_Discard()), redirect_stderr(_Discard()):
        return _serve(source, output, registry_factory)


def _serve(source: BinaryIO, output: BinaryIO, factory: RegistryFactory) -> int:
    bootstrap = None
    seq = 0
    try:
        init = decode_line(source.readline(MAX_BOOTSTRAP_BYTES + 1), Command, limit=MAX_BOOTSTRAP_BYTES)
        if not isinstance(init, InitCommand) or init.session_id != init.bootstrap.session_id:
            return 2
        bootstrap = init.bootstrap
        started = monotonic()
        events = []
        cancelled = False

        def sink(event):
            item = AttemptEvent.model_validate(event)
            if len(events) >= 4:
                raise ValueError("attempt_event_limit")
            events.append(item)

        ledgers = {arm: RemoteLedger(bootstrap, arm, source, output) for arm in bootstrap.policies}
        registry = factory(bootstrap, ledgers, sink, lambda: cancelled)
        adapter = registry.get(bootstrap.pin.arm)
        if (adapter is None or not callable(adapter) or not callable(getattr(adapter, "preflight", None))
                or adapter.model_id != bootstrap.pin.model_id or adapter.arm != bootstrap.pin.arm
                or adapter.configuration_sha256 != bootstrap.pin.configuration_sha256
                or adapter.artifact_sha256 != bootstrap.pin.artifact_sha256):
            raise ValueError("worker_adapter_pin_mismatch")
        output.write(encode_line(WorkerReply(session_id=bootstrap.session_id, seq=0, status="ready"),
                                 limit=MAX_REPLY_BYTES))
        output.flush()
        population = {}
        sealed = None
        while monotonic() - started < bootstrap.limits.lifetime_seconds:
            raw = source.readline(MAX_RECORD_BYTES + 1)
            if not raw:
                return 0
            command = decode_line(raw, Command, limit=MAX_RECORD_BYTES)
            if (isinstance(command, InitCommand) or command.session_id != bootstrap.session_id
                    or command.seq != seq + 1):
                raise ValueError("worker_sequence_mismatch")
            seq = command.seq
            events.clear()
            for ledger in ledgers.values():
                ledger.seq, ledger.rpc_seq = seq, 0
            if isinstance(command, ControlCommand):
                cancelled = True
                status = "cancelled" if command.kind == "cancel" else "closed"
                reply = WorkerReply(session_id=bootstrap.session_id, seq=seq, status=status)
                output.write(encode_line(reply, limit=MAX_REPLY_BYTES))
                output.flush()
                return 0
            if isinstance(command, SealCommand):
                digest = population_digest(population)
                if command.count != len(population) or command.population_sha256 != digest:
                    raise ValueError("worker_population_mismatch")
                if sealed is not None and sealed != digest:
                    raise ValueError("worker_population_already_sealed")
                sealed = digest
                reply = WorkerReply(session_id=bootstrap.session_id, seq=seq, status="sealed")
            elif isinstance(command, RecordCommand):
                record = command.record
                if record.split_id != "inference":
                    raise ValueError("opaque_inference_record_required")
                if command.kind == "preflight":
                    if sealed is not None or record.record_id in population:
                        raise ValueError("worker_population_locked")
                    if len(population) >= bootstrap.limits.max_records:
                        raise ValueError("worker_record_cap")
                    adapter.preflight((record,))
                    population[record.record_id] = record.content_sha256
                    reply = WorkerReply(session_id=bootstrap.session_id, seq=seq, status="preflight_ok")
                else:
                    if sealed is None or population.get(record.record_id) != record.content_sha256:
                        raise ValueError("worker_preflight_required")
                    try:
                        prediction = adapter(record)
                    except BudgetExceeded:
                        reply = WorkerReply(session_id=bootstrap.session_id, seq=seq,
                                            status="budget_rejected", events=tuple(events))
                    else:
                        if not isinstance(prediction, Prediction):
                            raise ValueError("prediction_wire_required")
                        reply = WorkerReply(session_id=bootstrap.session_id, seq=seq, status="prediction",
                                            prediction=prediction, events=tuple(events))
                    del record
            else:
                raise ValueError("invalid_worker_command")
            output.write(encode_line(reply, limit=MAX_REPLY_BYTES))
            output.flush()
        return 2
    except BaseException:
        # Never render exception, request, model output, traceback or config values.
        if bootstrap is not None:
            try:
                output.write(encode_line(WorkerReply(session_id=bootstrap.session_id, seq=seq,
                    status="error", error_code="worker_failure"), limit=MAX_REPLY_BYTES))
                output.flush()
            except BaseException:
                pass
        return 2
