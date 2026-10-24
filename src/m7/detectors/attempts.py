"""Bounded logical-call controller. No database/model I/O until explicitly called.

Only a first reservation rejection may escape as BudgetExceeded. Once any physical
attempt may have started, all failures/cancellation/retry denial return predictions.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from threading import RLock
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from m7.contracts import LogRecord, Prediction, failure, validate_prediction
from m7.ledger import BudgetExceeded
from m7.providers.contracts import AdapterFault, AttemptPolicy, CashReceipt
from m7.providers.frontier import TransportFault


class Ledger(Protocol):
    authorization_id: str
    cap: int

    def reserve(self, attempt_id: str, worst_case_micros: int, *, category: str) -> None: ...

    def reconcile(self, attempt_id: str, *, actual_micros: int | None, state: str,
                  usage_units: int | None = None, receipt_id: str | None = None,
                  compute_seconds: float | None = None) -> None: ...


@dataclass(frozen=True)
class AttemptResult:
    prediction: Prediction
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class AttemptDiagnostic:
    attempt_id: str
    ordinal: int
    status: str
    error_code: str | None
    duration_ms: float
    input_tokens: int | None
    output_tokens: int | None
    reservation_micros: int | None
    actual_micros: int | None
    liability_status: str
    retry_reason: str | None
    physical_may_have_started: bool


ReceiptResolver = Callable[[str, AttemptResult | None], CashReceipt | None]


class AttemptController:
    """Sequential worker with in-memory replay guard; D7 owns durable begin/terminal.

    Ledger is initialized externally after authorization, never by registry creation.
    Cancel is cooperative before/after blocking calls. An in-flight interruption may
    have cost money: absent a verified receipt its full reservation remains unknown.
    """

    def __init__(self, *, run_id: str, arm: str, model_id: str, policy: AttemptPolicy,
                 ledger: Ledger, cancelled: Callable[[], bool] = lambda: False,
                 receipt_resolver: ReceiptResolver | None = None,
                 diagnostic_sink: Callable[[dict], None] | None = None,
                 attempt_namespace: str | None = None):
        if (ledger.authorization_id != policy.authorization_id or ledger.cap != policy.authorization_cap_micros
                or policy.worst_case_micros > policy.authorization_cap_micros):
            raise ValueError("ledger_authorization_mismatch")
        self.run_id, self.arm, self.model_id = run_id, arm, model_id
        self.policy, self.ledger = policy, ledger
        self.cancelled, self.receipt_resolver = cancelled, receipt_resolver
        self.diagnostic_sink = diagnostic_sink
        if attempt_namespace is not None and (len(attempt_namespace) != 64 or
                any(c not in "0123456789abcdef" for c in attempt_namespace)):
            raise ValueError("invalid_attempt_namespace")
        self.attempt_namespace = attempt_namespace
        self.last_attempts: tuple[AttemptDiagnostic, ...] = ()
        self._records: dict[str, tuple[str, Prediction | None]] = {}
        self._completed_attempts: dict[str, tuple[AttemptDiagnostic, ...]] = {}
        self._lock = RLock()

    def _failure(self, record: LogRecord, attempt_id: str, code: str) -> Prediction:
        status = ("cancelled" if code == "cancelled" else
                  "unavailable" if code in ("permit_required", "unavailable") else
                  "failed" if code == "backend_failure" else "invalid_output")
        return failure(record, run_id=self.run_id, arm=self.arm, model_id=self.model_id,
                       attempt_id=attempt_id, status=status, error_code=code)

    def _cancelled(self) -> bool:
        try:
            return self.cancelled() is not False
        except BaseException:
            return True

    def cancel_requested(self) -> bool:
        return self._cancelled()

    def _emit(self, record: LogRecord, diagnostic: AttemptDiagnostic) -> bool:
        if self.diagnostic_sink is None:
            return True  # Host may instead consume last_attempts synchronously.
        event = {"schema_version": "AdapterAttempt/v1", "run_id": self.run_id,
                 "arm": self.arm, "model_id": self.model_id, "record_id": record.record_id,
                 "content_sha256": record.content_sha256, "attempt": asdict(diagnostic)}
        try:
            self.diagnostic_sink(event)
            return True
        except BaseException:
            return False  # Never stringify sink failures or repeat a model call.

    def _reconcile(self, attempt_id: str, result: AttemptResult | None, *, state: str,
                   no_physical_call: bool, compute_seconds: float | None = None) -> tuple[int | None, str]:
        receipt = None
        actual = None
        receipt_id = None
        if no_physical_call and self.policy.no_call_zero_cash_approved:
            # A controller fact, not fabricated provider billing: operation was
            # never entered, and the resource receipt explicitly approved this
            # zero-incremental-cash rule. Otherwise preserve unknown liability.
            actual, receipt_id = 0, "no-call-" + attempt_id
        elif self.receipt_resolver is not None:
            try:
                candidate = self.receipt_resolver(attempt_id, result)
                if isinstance(candidate, CashReceipt) and candidate.attempt_id == attempt_id:
                    receipt = candidate
            except BaseException:
                # Missing/unreadable provider receipt cannot release liability.
                receipt = None
        if receipt is not None:
            actual, receipt_id = receipt.actual_micros, receipt.receipt_id
        usage = None
        if result is not None:
            counts = (result.input_tokens, result.output_tokens)
            if all(type(value) is int and value >= 0 for value in counts):
                usage = sum(counts)
        try:
            self.ledger.reconcile(attempt_id, actual_micros=actual,
                                  state=state, usage_units=usage,
                                  receipt_id=receipt_id, compute_seconds=compute_seconds)
        except BaseException:
            # Do not retry the operation because bookkeeping failed. Reserve row
            # survives as unknown; later operator repair uses the physical ID.
            return None, "reconciliation_failed"
        return (None, "unknown") if actual is None else (actual, "known_no_call" if no_physical_call else "known")

    def run(self, record: LogRecord, *, prepare: Callable[[], None],
            operation: Callable[[str], AttemptResult]) -> Prediction:
        with self._lock:
            return self._run(record, prepare=prepare, operation=operation)

    def _run(self, record: LogRecord, *, prepare: Callable[[], None],
             operation: Callable[[str], AttemptResult]) -> Prediction:
        self.last_attempts = ()
        if not isinstance(record, LogRecord):
            raise ValueError("record_wire_required")
        previous = self._records.get(record.record_id)
        if previous is not None:
            digest, terminal = previous
            if digest != record.content_sha256:
                return self._failure(record, "identity-conflict", "invalid_output")
            # A begun-but-uncertain call is never blindly reexecuted in-process.
            self.last_attempts = self._completed_attempts.get(record.record_id, ())
            return terminal if terminal is not None else self._failure(record, "interrupted", "cancelled")
        if len(self._records) >= self.policy.max_records or len(record.log.message) > 1024:
            return self._failure(record, "record-cap", "truncated")
        if self._cancelled():
            return self._failure(record, "before-start", "cancelled")
        self._records[record.record_id] = (record.content_sha256, None)
        diagnostics = []
        logical_started = perf_counter()
        final = self._failure(record, "not-started", "backend_failure")
        def not_reserved(attempt_id: str, ordinal: int, started: float, reason: str) -> None:
            diagnostics.append(AttemptDiagnostic(attempt_id, ordinal, final.status, final.error_code,
                (perf_counter() - started) * 1000, None, None, None, None,
                "not_reserved", reason, False))
            self.last_attempts = tuple(diagnostics)
            self._emit(record, diagnostics[-1])

        for ordinal in range(1, 2 + self.policy.max_transient_retries):
            attempt_id = (("t-" + self.attempt_namespace + "-") if self.attempt_namespace else "a-") + uuid4().hex
            started = perf_counter()
            try:
                prepare()  # Permission/revocation/expiry/token limits before reserve.
            except KeyboardInterrupt:
                final = self._failure(record, attempt_id, "cancelled")
                not_reserved(attempt_id, ordinal, started, "cancelled_before_reserve")
                break
            except AdapterFault as error:
                final = self._failure(record, attempt_id, error.code)
                not_reserved(attempt_id, ordinal, started, "preflight_rejected")
                break
            except Exception:
                final = self._failure(record, attempt_id, "backend_failure")
                not_reserved(attempt_id, ordinal, started, "preflight_failed")
                break
            if self._cancelled():
                final = self._failure(record, attempt_id, "cancelled")
                not_reserved(attempt_id, ordinal, started, "cancelled_before_reserve")
                break
            try:
                self.ledger.reserve(attempt_id, self.policy.worst_case_micros,
                                    category="inference" if ordinal == 1 else "retry")
            except BudgetExceeded:
                final = self._failure(record, attempt_id, "backend_failure")
                not_reserved(attempt_id, ordinal, started, "initial_budget_rejected" if ordinal == 1
                             else "retry_budget_rejected")
                if ordinal == 1:
                    # No operation entered. D7 may safely mark this unattempted.
                    self._records.pop(record.record_id, None)
                    raise
                break  # Earlier attempt exists: NEVER escape BudgetExceeded.
            except Exception:
                final = self._failure(record, attempt_id, "backend_failure")
                # A database error may follow commit. No operation ran; reconcile
                # if a row exists and preserve failure rather than reopening it.
                actual, liability = self._reconcile(attempt_id, None, state="failed", no_physical_call=True)
                diagnostics.append(AttemptDiagnostic(attempt_id, ordinal, final.status, final.error_code,
                    (perf_counter() - started) * 1000, None, None, self.policy.worst_case_micros,
                    actual, liability, "reservation_error", False))
                self.last_attempts = tuple(diagnostics)
                self._emit(record, diagnostics[-1])
                break
            except BaseException:
                final = self._failure(record, attempt_id, "cancelled")
                actual, liability = self._reconcile(attempt_id, None, state="cancelled", no_physical_call=True)
                diagnostics.append(AttemptDiagnostic(attempt_id, ordinal, final.status, final.error_code,
                    (perf_counter() - started) * 1000, None, None, self.policy.worst_case_micros,
                    actual, liability, "reservation_interrupted", False))
                self.last_attempts = tuple(diagnostics)
                self._emit(record, diagnostics[-1])
                break
            physical = False
            operation_started = None
            result = None
            transient = False
            retry_reason = None
            try:
                if self._cancelled():
                    raise AdapterFault("cancelled")
                prepare()  # A permit may expire during reserve I/O.
                if self._cancelled():
                    raise AdapterFault("cancelled")
                physical = True  # Conservatively entered; transport may have sent.
                operation_started = perf_counter()
                result = operation(attempt_id)
                if not isinstance(result, AttemptResult):
                    result = None
                    raise AdapterFault("invalid_output")
                prediction = result.prediction
                if (not isinstance(prediction, Prediction)
                        or any(value is not None and (type(value) is not int or value < 0)
                               for value in (result.input_tokens, result.output_tokens))
                        or prediction.run_id != self.run_id or prediction.arm != self.arm
                        or prediction.model_id != self.model_id or prediction.attempt_id != attempt_id):
                    result = None
                    raise AdapterFault("invalid_output")
                final = validate_prediction(record, prediction)
                if self._cancelled():
                    final = self._failure(record, attempt_id, "cancelled")
            except TransportFault as error:
                transient = physical and error.transient and self.arm == "frontier"
                retry_reason = "transient_transport" if transient else None
                final = self._failure(record, attempt_id, "backend_failure")
            except KeyboardInterrupt:
                final = self._failure(record, attempt_id, "cancelled")
            except AdapterFault as error:
                final = self._failure(record, attempt_id, error.code)
            except Exception:
                final = self._failure(record, attempt_id, "backend_failure")
            except BaseException:
                # SystemExit/GeneratorExit also leave uncertain in-flight exits.
                final = self._failure(record, attempt_id, "cancelled")
            state = ("succeeded" if final.status == "ok" else
                     "cancelled" if final.status == "cancelled" else "failed")
            # Measured wall time of the entered operation only (a time proxy, not billing);
            # None when no operation was entered.
            compute = None if operation_started is None else max(0.0, perf_counter() - operation_started)
            actual, liability = self._reconcile(attempt_id, result, state=state,
                                                no_physical_call=not physical, compute_seconds=compute)
            elapsed = (perf_counter() - started) * 1000
            diagnostics.append(AttemptDiagnostic(attempt_id, ordinal, final.status, final.error_code,
                elapsed, None if result is None else result.input_tokens,
                None if result is None else result.output_tokens, self.policy.worst_case_micros,
                actual, liability, retry_reason, physical))
            self.last_attempts = tuple(diagnostics)
            emitted = self._emit(record, diagnostics[-1])
            if not emitted:
                final = self._failure(record, attempt_id, "backend_failure")
            # Malformed/truncated/partial anchoring, local errors, bookkeeping
            # failures, cancellation or exhausted policy can NEVER content-retry.
            if (not emitted or not transient or ordinal > self.policy.max_transient_retries
                    or liability == "reconciliation_failed" or self._cancelled()):
                break
        reserved = [row for row in diagnostics if row.reservation_micros is not None]
        final = final.model_copy(update={"duration_ms": (perf_counter() - logical_started) * 1000,
                                         "usage_ref": reserved[-1].attempt_id if reserved else None})
        self._records[record.record_id] = (record.content_sha256, final)
        self._completed_attempts[record.record_id] = tuple(diagnostics)
        return final
