"""Parent-side isolated record session; no process/DB/model work on import.

The host keeps custody/gold and ledgers. Child wire receives no custody or ledger
path. Actual native isolation and exact launched-process attestation are mandatory.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
from functools import wraps
from pathlib import Path
from threading import Event, RLock
from time import monotonic
from typing import ParamSpec, Protocol, TypeVar
from uuid import uuid4

from m7.contracts import LogRecord, Prediction, failure, validate_prediction
from m7.data.access import IsolationGuard
from m7.detectors.attempts import Ledger
from m7.ledger import BudgetExceeded
from .contracts import AdapterFault, CashReceipt, FrontierConfig, LocalModelConfig, config_digest
from .parity import validate_pair
from .worker_profile import WorkerProfile, validate_worker_membership
from .worker_service import population_digest
from .worker_transport import (
    IsolatedLauncher, OwnedWorker, WorkerLaunchPolicy, WorkerProcessVerifier, launch_spec,
)
from .worker_wire import (
    AttemptEvent, BrokerReply, ControlCommand, InitCommand, MAX_BOOTSTRAP_BYTES, MAX_RECORD_BYTES,
    MAX_REPLY_BYTES, ReconcileRequest, RecordCommand, ReserveRequest, Response, SealCommand,
    WorkerBootstrap, WorkerReply, decode_line, encode_line,
)

_P = ParamSpec("_P")
_R = TypeVar("_R")


class _InitialBudgetDenied(BudgetExceeded):
    """Internal marker set only from the parent's actual first reserve decision."""


def _safe_activation(function: Callable[_P, _R]) -> Callable[_P, _R]:
    @wraps(function)
    def guarded(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return function(*args, **kwargs)
        except AdapterFault:
            raise
        except BaseException:
            raise AdapterFault("unavailable") from None
    return guarded


class WorkerSessionProtocol(Protocol):
    arm: str
    model_id: str
    artifact_sha256: str
    configuration_sha256: str
    last_attempts: tuple[AttemptEvent, ...]
    cleanup_status: str

    def preflight(self, records: tuple[LogRecord, ...]) -> None: ...
    def predict(self, record: LogRecord) -> Prediction: ...
    def cancel(self) -> None: ...
    def close(self) -> None: ...


def _file_pin(path: Path, digest: str) -> None:
    if not path.is_absolute() or not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
        raise AdapterFault("permit_required")
    for parent in (path, *path.parents):
        if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
            raise AdapterFault("permit_required")
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(block)
    if hasher.hexdigest() != digest:
        raise AdapterFault("permit_required")


class WorkerSession:
    """One arm, one sealed input population and one logical-call cache per session.

    Not a timing-pass API: cached results must never be represented as fresh timing
    samples. D7 owns fresh-controller timing with an approved warmed backend.
    """

    def __init__(self, bootstrap, policy, profile, process, guard, process_verifier, ledgers, *,
                 reconcile_verifier=None, diagnostic_sink=None):
        self.bootstrap, self.policy, self.process = bootstrap, policy, process
        self.profile = profile
        self._approved_launch_sha256 = validate_worker_membership(profile, policy).launch_sha256
        self.guard, self.process_verifier = guard, process_verifier
        self.ledgers = ledgers
        self.reconcile_verifier, self.diagnostic_sink = reconcile_verifier, diagnostic_sink
        self.arm, self.model_id = bootstrap.pin.arm, bootstrap.pin.model_id
        self.artifact_sha256 = bootstrap.pin.artifact_sha256
        self.configuration_sha256 = bootstrap.pin.configuration_sha256
        self.run_id = bootstrap.run_id
        self.last_attempts = ()
        self.cleanup_status = "not_requested"
        self._born, self._seq = monotonic(), 0
        self._lock, self._pending_lock = RLock(), RLock()
        self._cancelled = Event()
        self._closed = False
        self._pending = {}
        self._attempts = {}
        self._population = None
        self._cache = {}
        self._cached_events = {}
        self._budget_rejected = set()
        self._request_attempts = set()
        self._reserve_requests = 0
        self._first_budget_denied = False
        self._rpc_seq = 0

    def _guard(self):
        membership = validate_worker_membership(self.profile, self.policy)
        if (membership.launch_sha256 != self._approved_launch_sha256 or self.policy.arm != self.arm
                or config_digest(self.bootstrap) != self.policy.bootstrap_sha256):
            raise AdapterFault("permit_required")
        verified = self.guard.require_current(self.policy.edition_id, self.policy.corpus_manifest_sha256,
            filesystem_policy_sha256=self.policy.filesystem_policy_sha256,
            worker_policy_sha256=membership.profile_sha256)
        if (self.guard.verify_receipt("worker_profile_approval", membership.profile_sha256) is not True
                or self.guard.verify_receipt("worker_launch_approval", membership.launch_sha256) is not True
                or self.guard.verify_receipt("worker_application_manifest", self.policy.application_manifest_sha256) is not True
                or self.guard.verify_receipt("worker_runtime_environment", self.policy.runtime_environment_sha256) is not True
                or self.process_verifier.verify(self.process.pid, self.process.start_identity,
                    launch_spec(self.policy), verified, self.policy) is not True):
            raise AdapterFault("permit_required")
        if (self._closed or self._cancelled.is_set()
                or monotonic() - self._born >= self.bootstrap.limits.lifetime_seconds):
            raise AdapterFault("cancelled" if self._cancelled.is_set() else "unavailable")

    def _abort(self):
        self._closed = True
        try:
            self.process.terminate()  # Only the launcher-owned native job tree.
            self.cleanup_status = "termination_requested"
            self.process.wait(self.policy.close_timeout_seconds)
            self.cleanup_status = "closed"
        except BaseException:
            self.cleanup_status = "cleanup_unverified"
        self._settle_pending()

    def _settle_pending(self):
        with self._pending_lock:
            pending, self._pending = self._pending, {}
        for attempt_id, ledger in pending.items():
            try:
                ledger.reconcile(attempt_id, actual_micros=None,
                    state="cancelled" if self._cancelled.is_set() else "unknown")
            except BaseException:
                pass  # Original reservation retains full unresolved liability.

    def _broker(self, request) -> BrokerReply:
        if (request.arm != self.arm or self.arm not in self.bootstrap.policies
                or request.rpc_seq != self._rpc_seq + 1):
            raise AdapterFault("invalid_output")
        self._rpc_seq = request.rpc_seq
        policy, ledger = self.bootstrap.policies[self.arm], self.ledgers[self.arm]
        status = "failed"
        if isinstance(request, ReserveRequest):
            self._reserve_requests += 1
            ordinal = self._reserve_requests
            if (request.attempt_id in self._attempts or ordinal > 1 + policy.max_transient_retries
                    or request.worst_case_micros != policy.worst_case_micros
                    or request.category != ("inference" if ordinal == 1 else "retry")):
                raise AdapterFault("invalid_output")
            try:
                ledger.reserve(request.attempt_id, request.worst_case_micros, category=request.category)
            except BudgetExceeded:
                if ordinal == 1:
                    self._first_budget_denied = True
                status = "budget_rejected"
            except BaseException:
                # A committed-then-interrupted reserve may exist. Keep its ID for
                # conservative cleanup, never authorize a physical call on failure.
                with self._pending_lock:
                    self._pending[request.attempt_id] = ledger
                status = "failed"
            else:
                with self._pending_lock:
                    self._pending[request.attempt_id] = ledger
                self._attempts[request.attempt_id] = {"actual": None, "reserved": policy.worst_case_micros,
                                                     "ordinal": ordinal}
                self._request_attempts.add(request.attempt_id)
                status = "ok"
        else:
            if request.attempt_id not in self._request_attempts or request.attempt_id not in self._pending:
                raise AdapterFault("invalid_output")
            actual, receipt_id = None, None
            # Never trust child-reported cash to release the parent's liability.
            if self.reconcile_verifier is not None:
                try:
                    receipt = self.reconcile_verifier(request)
                    if isinstance(receipt, CashReceipt) and receipt.attempt_id == request.attempt_id:
                        actual, receipt_id = receipt.actual_micros, receipt.receipt_id
                except BaseException:
                    pass
            try:
                ledger.reconcile(request.attempt_id, actual_micros=actual, state=request.state,
                                 usage_units=request.usage_units, receipt_id=receipt_id)
            except BaseException:
                status = "failed"
            else:
                with self._pending_lock:
                    self._pending.pop(request.attempt_id, None)
                self._attempts[request.attempt_id]["actual"] = actual
                status = "reconciled_unknown" if request.actual_micros is not None and actual is None else "ok"
        return BrokerReply(session_id=self.bootstrap.session_id, seq=self._seq,
                           rpc_seq=request.rpc_seq, status=status)

    def _exchange(self, command, *, limit=MAX_RECORD_BYTES, startup=False) -> WorkerReply:
        self._guard()
        self._request_attempts, self._rpc_seq = set(), 0
        self._reserve_requests, self._first_budget_denied = 0, False
        deadline = min(self._born + self.bootstrap.limits.lifetime_seconds,
                       monotonic() + (self.policy.startup_timeout_seconds if startup
                                      else self.bootstrap.limits.request_timeout_seconds))
        self.process.send(encode_line(command, limit=limit), deadline - monotonic())
        for _ in range(17):  # At most 16 bounded broker messages then one final reply.
            message = decode_line(self.process.receive(MAX_REPLY_BYTES, deadline - monotonic()),
                                  Response, limit=MAX_REPLY_BYTES)
            if message.session_id != self.bootstrap.session_id or message.seq != self._seq:
                raise AdapterFault("invalid_output")
            if isinstance(message, WorkerReply):
                return message
            if not isinstance(command, RecordCommand) or command.kind != "predict":
                raise AdapterFault("invalid_output")
            self._guard()
            reply = self._broker(message)
            self.process.send(encode_line(reply, limit=MAX_RECORD_BYTES), deadline - monotonic())
        raise AdapterFault("invalid_output")

    def preflight(self, records: tuple[LogRecord, ...]) -> None:
        with self._lock:
            try:
                self._guard()
                population = {row.record_id: row.content_sha256 for row in records}
                if (not records or len(records) > self.bootstrap.limits.max_records
                        or len(population) != len(records) or any(row.split_id != "inference" for row in records)):
                    raise AdapterFault("invalid_output")
                if self._population is not None:
                    if self._population != population:
                        raise AdapterFault("invalid_output")
                    return
                for record in records:
                    self._seq += 1
                    reply = self._exchange(RecordCommand(kind="preflight", session_id=self.bootstrap.session_id,
                                                         seq=self._seq, record=record))
                    if reply.status != "preflight_ok" or reply.events:
                        raise AdapterFault("unavailable")
                self._seq += 1
                reply = self._exchange(SealCommand(session_id=self.bootstrap.session_id, seq=self._seq,
                    count=len(records), population_sha256=population_digest(population)))
                if reply.status != "sealed" or reply.events:
                    raise AdapterFault("invalid_output")
                self._population = population
            except BaseException:
                self._abort()
                raise AdapterFault("unavailable") from None

    def _events(self, reply: WorkerReply, record: LogRecord):
        checked = []
        for event in reply.events:
            if (event.run_id != self.run_id or event.arm != self.arm or event.model_id != self.model_id
                    or event.record_id != record.record_id or event.content_sha256 != record.content_sha256):
                raise AdapterFault("invalid_output")
            # Cash is the parent's authenticated broker result, not child testimony.
            known = self._attempts.get(event.attempt.attempt_id) if event.attempt.attempt_id in self._request_attempts else None
            payload = event.model_dump(mode="json")
            if known is not None:
                payload["attempt"]["actual_micros"] = known["actual"]
                payload["attempt"]["liability_status"] = "known" if known["actual"] is not None else "unknown"
            elif event.attempt.reservation_micros is not None:
                raise AdapterFault("invalid_output")
            normalized = AttemptEvent.model_validate_json(json.dumps(payload, allow_nan=False))
            checked.append(normalized)
            self.last_attempts = tuple(checked)
            if self.diagnostic_sink is not None:
                self.diagnostic_sink(normalized.model_dump(mode="json"))
        self.last_attempts = tuple(checked)

    def _record_uncertain(self, record: LogRecord, started: float):
        reported = {event.attempt.attempt_id for event in self.last_attempts}
        rows = list(self.last_attempts)
        for attempt_id in sorted(self._request_attempts, key=lambda item: self._attempts[item]["ordinal"]):
            if attempt_id in reported:
                continue
            known = self._attempts[attempt_id]
            event = AttemptEvent.model_validate({"run_id": self.run_id, "arm": self.arm,
                "model_id": self.model_id, "record_id": record.record_id,
                "content_sha256": record.content_sha256,
                "attempt": {"attempt_id": attempt_id, "ordinal": known["ordinal"],
                    "status": "cancelled" if self._cancelled.is_set() else "failed",
                    "error_code": "cancelled" if self._cancelled.is_set() else "backend_failure",
                    "duration_ms": max(0.0, (monotonic() - started) * 1000),
                    "input_tokens": None, "output_tokens": None,
                    "reservation_micros": known["reserved"], "actual_micros": known["actual"],
                    "liability_status": "known" if known["actual"] is not None else "unknown",
                    "retry_reason": None, "physical_may_have_started": True}})
            rows.append(event)
            if self.diagnostic_sink is not None:
                try:
                    self.diagnostic_sink(event.model_dump(mode="json"))
                except BaseException:
                    pass
        self.last_attempts = tuple(rows)

    def predict(self, record: LogRecord) -> Prediction:
        with self._lock:
            self.last_attempts = ()
            started = monotonic()
            self._request_attempts = set()
            try:
                self._guard()
                if self._population is None or self._population.get(record.record_id) != record.content_sha256:
                    raise AdapterFault("invalid_output")
                if record.record_id in self._cache:
                    self.last_attempts = self._cached_events[record.record_id]
                    return self._cache[record.record_id]
                if record.record_id in self._budget_rejected:
                    self.last_attempts = self._cached_events[record.record_id]
                    raise _InitialBudgetDenied("authorization_cap")
                self._seq += 1
                reply = self._exchange(RecordCommand(kind="predict", session_id=self.bootstrap.session_id,
                                                     seq=self._seq, record=record))
                self._events(reply, record)
                if reply.status == "budget_rejected" and self._first_budget_denied and not self._request_attempts:
                    self._budget_rejected.add(record.record_id)
                    self._cached_events[record.record_id] = self.last_attempts
                    raise _InitialBudgetDenied("authorization_cap")  # Zero approved physical call.
                if reply.status != "prediction" or reply.prediction is None:
                    raise AdapterFault("backend_failure")
                candidate = reply.prediction
                if (candidate.run_id != self.run_id or candidate.arm != self.arm or candidate.model_id != self.model_id
                        or candidate.record_id != record.record_id or candidate.content_sha256 != record.content_sha256
                        or self.arm != "regex" and candidate.status == "ok" and not self._request_attempts):
                    raise AdapterFault("invalid_output")
                result = validate_prediction(record, candidate)
            except _InitialBudgetDenied:
                raise BudgetExceeded("authorization_cap") from None
            except KeyboardInterrupt:
                self._cancelled.set()
                self._abort()
                self._record_uncertain(record, started)
                result = failure(record, run_id=self.run_id, arm=self.arm, model_id=self.model_id,
                    attempt_id="worker-" + uuid4().hex, status="cancelled", error_code="cancelled")
            except BaseException:
                self._abort()
                self._record_uncertain(record, started)
                result = failure(record, run_id=self.run_id, arm=self.arm, model_id=self.model_id,
                    attempt_id="worker-" + uuid4().hex,
                    status="cancelled" if self._cancelled.is_set() else "failed",
                    error_code="cancelled" if self._cancelled.is_set() else "backend_failure")
            self._cache[record.record_id] = result
            self._cached_events[record.record_id] = self.last_attempts
            return result

    __call__ = predict

    def cancel(self) -> None:
        self._cancelled.set()
        self._abort()  # No concurrent pipe write or wait for a blocked predictor.

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._seq += 1
                reply = self._exchange(ControlCommand(kind="close", session_id=self.bootstrap.session_id, seq=self._seq))
                if reply.status != "closed":
                    raise AdapterFault("invalid_output")
                self.process.wait(self.policy.close_timeout_seconds)
                self._closed = True
                self.cleanup_status = "closed"
                self._settle_pending()
            except BaseException:
                self._abort()


def validate_worker_spec(bootstrap: WorkerBootstrap, policy: WorkerLaunchPolicy, *, profile: WorkerProfile) -> dict:
    """Side-effect-free definition/pin/permit check; never certifies enforcement."""
    bootstrap = WorkerBootstrap.model_validate_json(bootstrap.model_dump_json())
    policy = WorkerLaunchPolicy.model_validate_json(policy.model_dump_json())
    membership = validate_worker_membership(profile, policy)
    launch_spec(policy)  # Lexical local path/environment constraints only.
    encode_line(InitCommand(session_id=bootstrap.session_id, bootstrap=bootstrap),
                limit=MAX_BOOTSTRAP_BYTES)  # Reject oversize before any native launch.
    if (bootstrap.pin.arm != policy.arm or config_digest(bootstrap) != policy.bootstrap_sha256
            or bootstrap.limits.lifetime_seconds != policy.lifetime_seconds):
        raise AdapterFault("permit_required")
    for arm, config in bootstrap.configs.items():
        if (arm == bootstrap.pin.arm and isinstance(config, LocalModelConfig)
                and config.artifact_root != policy.artifact_root):
            raise AdapterFault("permit_required")
        bootstrap.permits[arm].check(run_id=bootstrap.run_id, model_id=config.model_id,
            scope="frontier_inference" if arm == "frontier" else "local_inference",
            config_sha256=config_digest(config),
            attempt_policy_sha256=config_digest(bootstrap.policies[arm]))
        if isinstance(config, FrontierConfig):
            bootstrap.policies[arm].require_frontier_bound(config)
    if "finetuned" in bootstrap.configs:
        validate_pair(bootstrap.configs["base"], bootstrap.configs["finetuned"])
    if bootstrap.pin.arm != "regex":
        active = bootstrap.configs[bootstrap.pin.arm]
        artifact = active.model_revision_sha256 if isinstance(active, FrontierConfig) else active.weights_sha256
        if (active.model_id != bootstrap.pin.model_id or artifact != bootstrap.pin.artifact_sha256
                or config_digest(active) != bootstrap.pin.configuration_sha256):
            raise AdapterFault("permit_required")
    return {"status": "worker_definition_validated_only", "session_id": bootstrap.session_id,
            "worker_policy_sha256": membership.profile_sha256,
            "launch_policy_sha256": membership.launch_sha256, "spawned": False,
            "isolation_verified": False, "artifact_files_checked": False}


@_safe_activation
def launch_worker(bootstrap: WorkerBootstrap, policy: WorkerLaunchPolicy, *,
                  profile: WorkerProfile,
                  isolation_guard: IsolationGuard, launcher: IsolatedLauncher,
                  process_verifier: WorkerProcessVerifier, ledgers: Mapping[str, Ledger],
                  allow_execution: bool = False,
                  reconcile_verifier: Callable[[ReconcileRequest], CashReceipt | None] | None = None,
                  diagnostic_sink: Callable[[dict], None] | None = None) -> WorkerSession:
    """Explicit future activation only; no default native launcher or verifier.

    Validate/construct models without calling this function during construction.
    Authentication checks must attest actual enforcement, never just a child PID.
    """
    if not allow_execution or isolation_guard is None or launcher is None or process_verifier is None:
        raise AdapterFault("permit_required")
    bootstrap = WorkerBootstrap.model_validate_json(bootstrap.model_dump_json())
    policy = WorkerLaunchPolicy.model_validate_json(policy.model_dump_json())
    profile = WorkerProfile.model_validate_json(profile.model_dump_json())
    validate_worker_spec(bootstrap, policy, profile=profile)
    membership = validate_worker_membership(profile, policy)
    for arm, quota in bootstrap.policies.items():
        ledger = ledgers.get(arm)
        if (ledger is None or ledger.authorization_id != quota.authorization_id
                or ledger.cap != quota.authorization_cap_micros):
            raise AdapterFault("permit_required")
    verified = isolation_guard.require_current(policy.edition_id, policy.corpus_manifest_sha256,
        filesystem_policy_sha256=policy.filesystem_policy_sha256, worker_policy_sha256=membership.profile_sha256)
    if (isolation_guard.verify_receipt("worker_profile_approval", membership.profile_sha256) is not True
            or isolation_guard.verify_receipt("worker_launch_approval", membership.launch_sha256) is not True
            or isolation_guard.verify_receipt("worker_application_manifest", policy.application_manifest_sha256) is not True
            or isolation_guard.verify_receipt("worker_runtime_environment", policy.runtime_environment_sha256) is not True):
        raise AdapterFault("permit_required")
    _file_pin(Path(policy.executable), policy.executable_sha256)
    _file_pin(Path(policy.entrypoint), policy.entrypoint_sha256)
    spec = launch_spec(policy)
    process = launcher.launch(spec, verified, timeout=policy.startup_timeout_seconds)
    session = None
    try:
        session = WorkerSession(bootstrap, policy, profile, process, isolation_guard, process_verifier, ledgers,
                               reconcile_verifier=reconcile_verifier, diagnostic_sink=diagnostic_sink)
        if type(process.pid) is not int or process.pid <= 0:
            raise AdapterFault("permit_required")
        reply = session._exchange(InitCommand(session_id=bootstrap.session_id, bootstrap=bootstrap),
                                  limit=MAX_BOOTSTRAP_BYTES, startup=True)
        if reply.status != "ready" or reply.events:
            raise AdapterFault("unavailable")
    except BaseException:
        if session is not None:
            session._abort()
        else:
            try:
                process.terminate()
                process.wait(policy.close_timeout_seconds)
            except BaseException:
                pass  # Native failed-start cleanup must be investigated by host.
        raise AdapterFault("unavailable") from None
    return session
