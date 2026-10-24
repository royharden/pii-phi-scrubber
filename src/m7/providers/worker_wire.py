"""Strict bounded record-only worker wire; no process creation or file I/O."""
from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from m7.contracts import Arm, Boundary, Digest, Identifier, LogRecord, Prediction
from .contracts import AttemptPolicy, ExecutionPermit, FrontierConfig, LocalModelConfig
from m7.experiment.timing_contracts import TimingPhaseRequest, TimingPhasePermit

MAX_BOOTSTRAP_BYTES = 2_000_000
MAX_RECORD_BYTES = 32768
MAX_REPLY_BYTES = 262144


class WorkerLimits(Boundary):
    max_records: Annotated[int, Field(ge=1, le=1000000)]
    request_timeout_seconds: Annotated[float, Field(gt=0, le=300, allow_inf_nan=False)] = 120.0
    lifetime_seconds: Annotated[float, Field(gt=0, le=21600, allow_inf_nan=False)] = 3600.0


class WorkerPin(Boundary):
    arm: Arm
    model_id: Identifier
    artifact_sha256: Digest
    configuration_sha256: Digest


class WorkerBootstrap(Boundary):
    schema_version: Literal["WorkerBootstrap/v1"] = "WorkerBootstrap/v1"
    session_id: Identifier
    run_id: Identifier
    pin: WorkerPin
    limits: WorkerLimits
    configs: dict[str, LocalModelConfig | FrontierConfig]
    permits: dict[str, ExecutionPermit]
    policies: dict[str, AttemptPolicy]
    timing_plan_sha256: Digest | None = None
    timing_order_sha256: Digest | None = None

    @model_validator(mode="after")
    def bounded_configuration(self) -> WorkerBootstrap:
        if (self.timing_plan_sha256 is None) != (self.timing_order_sha256 is None):
            raise ValueError("timing_preregistration_pair_required")
        required = (set() if self.pin.arm == "regex" else
                    {"base", "finetuned"} if self.pin.arm == "finetuned" else {self.pin.arm})
        if any(set(mapping) != required for mapping in (self.configs, self.permits, self.policies)):
            raise ValueError("worker_minimal_config_required")
        for arm in required:
            config = self.configs[arm]
            if ((arm == "frontier") != isinstance(config, FrontierConfig)
                    or isinstance(config, LocalModelConfig) and config.arm != arm
                    or self.policies[arm].max_records < self.limits.max_records):
                raise ValueError("worker_config_mismatch")
        return self


class InitCommand(Boundary):
    kind: Literal["init"] = "init"
    session_id: Identifier
    seq: Literal[0] = 0
    bootstrap: WorkerBootstrap


class RecordCommand(Boundary):
    kind: Literal["preflight", "predict"]
    session_id: Identifier
    seq: Annotated[int, Field(ge=1)]
    record: LogRecord


class SealCommand(Boundary):
    kind: Literal["seal_preflight"] = "seal_preflight"
    session_id: Identifier
    seq: Annotated[int, Field(ge=1)]
    count: Annotated[int, Field(ge=1, le=1000000)]
    population_sha256: Digest


class ControlCommand(Boundary):
    kind: Literal["close", "cancel"]
    session_id: Identifier
    seq: Annotated[int, Field(ge=1)]


class TimingCommand(Boundary):
    kind: Literal["timing_identity", "timing_begin", "timing_finish"]
    session_id: Identifier
    seq: Annotated[int, Field(ge=1)]
    request: TimingPhaseRequest | None = None
    permit: TimingPhasePermit | None = None

    @model_validator(mode="after")
    def shape(self):
        if ((self.kind == "timing_identity" and (self.request is not None or self.permit is not None))
                or (self.kind != "timing_identity" and self.request is None)
                or (self.kind == "timing_begin") != (self.permit is not None)):
            raise ValueError("invalid_timing_command")
        return self


class BackendState(Boundary):
    backend_instance_id: Identifier
    physical_calls: Annotated[int, Field(ge=1, le=10000000)]
    population_sha256: Digest
    order_sha256: Digest


class Diagnostic(Boundary):
    attempt_id: Identifier
    ordinal: Annotated[int, Field(ge=1, le=2)]
    status: Literal["ok", "invalid_output", "unavailable", "failed", "cancelled"]
    error_code: Literal["invalid_output", "identity_mismatch", "invalid_bounds", "unavailable",
                        "backend_failure", "truncated", "permit_required", "cancelled"] | None
    duration_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    input_tokens: Annotated[int, Field(ge=0, le=262144)] | None
    output_tokens: Annotated[int, Field(ge=0, le=262144)] | None
    reservation_micros: Annotated[int, Field(ge=0, le=9223372036854775807)] | None
    actual_micros: Annotated[int, Field(ge=0, le=9223372036854775807)] | None
    liability_status: Literal["not_reserved", "unknown", "known", "known_no_call", "reconciliation_failed"]
    retry_reason: Literal["transient_transport", "cancelled_before_reserve", "preflight_rejected",
                          "preflight_failed", "initial_budget_rejected", "retry_budget_rejected",
                          "reservation_error", "reservation_interrupted"] | None
    physical_may_have_started: bool

    @model_validator(mode="after")
    def coherent(self) -> Diagnostic:
        if ((self.status == "ok") != (self.error_code is None)
                or self.liability_status == "not_reserved" and
                   (self.reservation_micros is not None or self.actual_micros is not None or self.physical_may_have_started)
                or self.liability_status in ("unknown", "reconciliation_failed") and self.actual_micros is not None
                or self.liability_status == "known" and self.actual_micros is None
                or self.liability_status == "known_no_call" and
                   (self.actual_micros != 0 or self.physical_may_have_started)):
            raise ValueError("invalid_attempt_diagnostic")
        return self


class AttemptEvent(Boundary):
    schema_version: Literal["AdapterAttempt/v1"] = "AdapterAttempt/v1"
    run_id: Identifier
    arm: Arm
    model_id: Identifier
    record_id: Identifier
    content_sha256: Digest
    attempt: Diagnostic


class WorkerReply(Boundary):
    kind: Literal["reply"] = "reply"
    session_id: Identifier
    seq: Annotated[int, Field(ge=0)]
    status: Literal["ready", "preflight_ok", "sealed", "prediction", "closed", "cancelled",
                    "budget_rejected", "error", "timing_identity", "timing_begun", "timing_finished"]
    prediction: Prediction | None = None
    events: Annotated[tuple[AttemptEvent, ...], Field(max_length=4)] = ()
    backend_state: BackendState | None = None
    error_code: Literal["invalid_request", "unavailable", "cancelled", "worker_failure"] | None = None

    @model_validator(mode="after")
    def shape(self) -> WorkerReply:
        if ((self.status == "timing_identity") != (self.backend_state is not None)
                or (self.status == "prediction") != (self.prediction is not None)
                or (self.status == "error") != (self.error_code is not None)):
            raise ValueError("invalid_worker_reply")
        return self


class ReserveRequest(Boundary):
    kind: Literal["reserve"] = "reserve"
    session_id: Identifier
    seq: Annotated[int, Field(ge=1)]
    rpc_seq: Annotated[int, Field(ge=1, le=16)]
    attempt_id: Identifier
    arm: Arm
    worst_case_micros: Annotated[int, Field(ge=0, le=9223372036854775807)]
    category: Literal["inference", "retry"]


class ReconcileRequest(Boundary):
    kind: Literal["reconcile"] = "reconcile"
    session_id: Identifier
    seq: Annotated[int, Field(ge=1)]
    rpc_seq: Annotated[int, Field(ge=1, le=16)]
    attempt_id: Identifier
    arm: Arm
    actual_micros: Annotated[int, Field(ge=0, le=9223372036854775807)] | None
    state: Literal["succeeded", "failed", "cancelled", "unknown"]
    usage_units: Annotated[int, Field(ge=0, le=524288)] | None = None
    receipt_id: Identifier | None = None


class BrokerReply(Boundary):
    kind: Literal["broker_reply"] = "broker_reply"
    session_id: Identifier
    seq: Annotated[int, Field(ge=1)]
    rpc_seq: Annotated[int, Field(ge=1, le=16)]
    status: Literal["ok", "budget_rejected", "failed", "reconciled_unknown"]


Command = Annotated[InitCommand | RecordCommand | SealCommand | ControlCommand | TimingCommand, Field(discriminator="kind")]
Response = Annotated[WorkerReply | ReserveRequest | ReconcileRequest, Field(discriminator="kind")]


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("nonfinite_json")


def _unicode(value, depth=0):
    if depth > 16:
        raise ValueError("wire_depth")
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("invalid_unicode")
    elif isinstance(value, dict):
        for key, item in value.items():
            _unicode(key, depth + 1)
            _unicode(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 4096:
            raise ValueError("wire_array_limit")
        for item in value:
            _unicode(item, depth + 1)


def decode_line(raw: bytes, schema, *, limit: int):
    if type(raw) is not bytes or not raw.endswith(b"\n") or len(raw) > limit:
        raise ValueError("wire_byte_limit")
    value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs,
                       parse_constant=_constant)
    _unicode(value)
    # JSON-mode strict boundaries permit arrays for immutable tuple fields.
    return TypeAdapter(schema).validate_json(json.dumps(value, allow_nan=False).encode(), strict=True)


def encode_line(message: Boundary, *, limit: int) -> bytes:
    value = message.model_dump(mode="json")
    _unicode(value)
    raw = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    if len(raw) > limit:
        raise ValueError("wire_byte_limit")
    return raw
