"""Declaration-first registry: callers supply authority, pins and optional engines.

No loading, network activity, artifact reads, environment reads or calls at build.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from m7.contracts import Boundary, Identifier, LogRecord, Prediction, failure, validate_prediction
from m7.detectors.frontier import anchor_frontier
from m7.detectors.regex import detect_regex
from m7.providers.contracts import (
    AdapterFault, AttemptPolicy, ExecutionPermit, FrontierConfig, LocalModelConfig, config_digest,
)
from m7.providers.frontier import PermittedFrontier, TokenCounter, Transport
from m7.providers.local import LocalLoader, PermittedLocalBackend
from m7.providers.parity import validate_pair
from .attempts import AttemptController, AttemptResult, Ledger, ReceiptResolver

if TYPE_CHECKING:
    from m7.experiment.executor import AdapterBinding
    from m7.experiment.models import ArmPin

AdapterConfig = LocalModelConfig | FrontierConfig


class _Identity(Boundary):
    run_id: Identifier


@dataclass(frozen=True)
class AttemptMetadata:
    """Explicit allowlist. No quotes, completions, exception text or value hashes."""

    attempt_id: str
    arm: str
    model_id: str
    status: str
    error_code: str | None
    duration_ms: float | None
    input_tokens: int | None = None
    output_tokens: int | None = None
    # Authoritative cost reconciliation belongs to the later attempt controller.
    usage_status: str = "unknown"
    liability_status: str = "unknown"


@dataclass
class DetectorAdapter:
    run_id: str
    arm: str
    model_id: str
    backend: PermittedLocalBackend | PermittedFrontier = field(repr=False)
    controller: AttemptController | None = field(default=None, repr=False)
    last_attempt: AttemptMetadata | None = field(default=None, init=False)

    @property
    def configuration_sha256(self) -> str:
        return config_digest(self.backend.config)

    @property
    def artifact_sha256(self) -> str:
        config = self.backend.config
        return config.model_revision_sha256 if isinstance(config, FrontierConfig) else config.weights_sha256

    def preflight(self, records: tuple[LogRecord, ...]) -> None:
        """Check the whole intended corpus before the host opens an edition."""
        if self.controller is None:
            raise AdapterFault("permit_required")
        if len(records) > self.controller.policy.max_records:
            raise AdapterFault("truncated")
        identities = {record.record_id for record in records}
        if len(identities) != len(records):
            raise AdapterFault("invalid_output")
        self._check_policy()
        for record in records:
            if self.controller.cancel_requested():
                raise AdapterFault("cancelled")
            self._prepare(record)  # Tokenization/authorized local loading, no inference.

    @property
    def last_attempts(self):
        return () if self.controller is None else self.controller.last_attempts

    def _check_policy(self) -> None:
        if self.controller is None:
            raise AdapterFault("permit_required")
        self.backend.permit.check(run_id=self.run_id, model_id=self.model_id,
            scope="frontier_inference" if self.arm == "frontier" else "local_inference",
            config_sha256=self.configuration_sha256,
            attempt_policy_sha256=config_digest(self.controller.policy))

    def _prepare(self, record: LogRecord) -> None:
        self._check_policy()
        if isinstance(self.backend, PermittedFrontier):
            self.backend.preflight(record)
        else:
            self.backend.preflight((record,))

    def _invoke(self, record: LogRecord, attempt_id: str) -> AttemptResult:
        # No catch here: transient transport signals must reach the controller.
        if isinstance(self.backend, PermittedFrontier):
            completion = self.backend(record)
            prediction = anchor_frontier(record, completion.content, run_id=self.run_id,
                                         model_id=self.model_id, attempt_id=attempt_id)
            result = AttemptResult(prediction, completion.input_tokens, completion.output_tokens)
            del completion
            return result
        result = self.backend(record)
        prediction = Prediction(run_id=self.run_id, record_id=record.record_id,
            content_sha256=record.content_sha256, arm=self.arm, model_id=self.model_id,
            attempt_id=attempt_id, status="ok", spans=result.spans)
        return AttemptResult(validate_prediction(record, prediction))

    def __call__(self, record: LogRecord) -> Prediction:
        self.last_attempt = None
        if self.controller is None:
            return failure(record, run_id=self.run_id, arm=self.arm, model_id=self.model_id,
                           status="unavailable", error_code="permit_required")
        prediction = self.controller.run(record, prepare=lambda: self._prepare(record),
                                         operation=lambda attempt_id: self._invoke(record, attempt_id))
        final = self.last_attempts[-1] if self.last_attempts else None
        self.last_attempt = AttemptMetadata(prediction.attempt_id, self.arm, self.model_id,
            prediction.status, prediction.error_code, prediction.duration_ms,
            None if final is None else final.input_tokens,
            None if final is None else final.output_tokens,
            usage_status="reported" if final is not None and final.input_tokens is not None
                and final.output_tokens is not None else "unknown",
            liability_status="unknown" if final is None else final.liability_status)
        return prediction


@dataclass(frozen=True)
class RegexAdapter:
    run_id: str
    arm: str = field(default="regex", init=False)
    model_id: str = field(default="context-regex-v1", init=False)

    @property
    def configuration_sha256(self) -> str:
        return hashlib.sha256(b'{"model_id":"context-regex-v1"}').hexdigest()

    @property
    def artifact_sha256(self) -> str:
        # Read only when the host explicitly binds pins, never in build_registry.
        return hashlib.sha256(Path(__file__).with_name("regex.py").read_bytes()).hexdigest()

    def preflight(self, records: tuple[LogRecord, ...]) -> None:
        if any(not isinstance(record, LogRecord) or len(record.log.message) > 1024 for record in records):
            raise AdapterFault("truncated")

    def __call__(self, record: LogRecord) -> Prediction:
        return detect_regex(record, run_id=self.run_id)


def build_registry(
    configs: Mapping[str, AdapterConfig],
    permits: Mapping[str, ExecutionPermit],
    *,
    run_id: str,
    transports: Mapping[str, Transport] | None = None,
    counters: Mapping[str, TokenCounter] | None = None,
    loaders: Mapping[str, LocalLoader] | None = None,
    allow_execution: bool = False,
    include_regex: bool = True,
    policies: Mapping[str, AttemptPolicy] | None = None,
    ledgers: Mapping[str, Ledger] | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    receipt_resolvers: Mapping[str, ReceiptResolver] | None = None,
    diagnostic_sink: Callable[[dict], None] | None = None,
) -> dict[str, Callable[[LogRecord], Prediction]]:
    """Return arm -> callable(LogRecord)->Prediction; missing arms stay absent.

    Only explicitly configured/authorized adapters appear. The caller decides
    whether an absent arm is not_measured; never substitute fake model results.
    `allow_execution=False` is construction/validation default. Even injected
    transports/loaders require a matching approved, unexpired permit on invocation.
    Activation also requires policy-digest-bound permits and initialized ledgers.
    The controller can retry only one predeclared transient frontier failure.
    Instances are sequential workers; do not share last_attempt across threads.
    """
    _Identity(run_id=run_id)
    if set(configs) - {"base", "finetuned", "frontier"} or set(permits) != set(configs):
        raise ValueError("adapter_config_mismatch")
    transports, counters, loaders = transports or {}, counters or {}, loaders or {}
    policies, ledgers, receipt_resolvers = policies or {}, ledgers or {}, receipt_resolvers or {}
    if allow_execution and (set(policies) != set(configs) or set(ledgers) != set(configs)):
        raise ValueError("attempt_authority_required")
    if "finetuned" in configs:
        if ("base" not in configs or not isinstance(configs["base"], LocalModelConfig)
                or not isinstance(configs["finetuned"], LocalModelConfig)):
            raise ValueError("base_fine_pair_required")
        validate_pair(configs["base"], configs["finetuned"])
    registry: dict[str, Callable[[LogRecord], Prediction]] = {}
    if include_regex:
        registry["regex"] = RegexAdapter(run_id)
    for arm, config in configs.items():
        permit = permits[arm]
        if not isinstance(permit, ExecutionPermit):
            raise ValueError("adapter_permit_required")
        if arm == "frontier":
            if not isinstance(config, FrontierConfig) or arm not in transports or arm not in counters:
                raise ValueError("frontier_dependencies_required")
            backend = PermittedFrontier(config, permit, run_id=run_id, transport=transports[arm],
                                        counter=counters[arm], allow_execution=allow_execution)
        else:
            if not isinstance(config, LocalModelConfig) or config.arm != arm:
                raise ValueError("local_config_mismatch")
            backend = PermittedLocalBackend(config, permit, run_id=run_id, loader=loaders.get(arm),
                                            allow_execution=allow_execution)
        controller = None
        if allow_execution:
            policy = policies[arm]
            if (not isinstance(policy, AttemptPolicy)
                    or permit.attempt_policy_sha256 != config_digest(policy)):
                raise ValueError("attempt_policy_mismatch")
            if isinstance(config, FrontierConfig):
                policy.require_frontier_bound(config)
            controller = AttemptController(run_id=run_id, arm=arm, model_id=config.model_id,
                policy=policy, ledger=ledgers[arm], cancelled=cancelled,
                receipt_resolver=receipt_resolvers.get(arm), diagnostic_sink=diagnostic_sink)
        registry[arm] = DetectorAdapter(run_id, arm, config.model_id, backend, controller)
    return registry


def bind_registry(registry: Mapping[str, Callable[[LogRecord], Prediction]],
                  pins: Sequence[ArmPin], *, run_id: str) -> dict[str, AdapterBinding]:
    """Build D7 AdapterBinding objects after checking exact declared source pins.

    `pins` is a sequence of m7.experiment.models.ArmPin, never an edition/gold bundle.
    This checks identity commitments, not approval/receipt authenticity or runtime.
    """
    from m7.experiment.executor import AdapterBinding

    _Identity(run_id=run_id)
    declared = {pin.arm: pin for pin in pins}
    if len(declared) != len(pins) or set(registry) - set(declared):
        raise ValueError("adapter_pin_mismatch")
    bound = {}
    for arm, adapter in registry.items():
        pin = declared[arm]
        if (not isinstance(adapter, (DetectorAdapter, RegexAdapter)) or adapter.arm != arm
                or adapter.run_id != run_id
                or adapter.model_id != pin.model_id or adapter.artifact_sha256 != pin.artifact_sha256
                or adapter.configuration_sha256 != pin.configuration_sha256):
            raise ValueError("adapter_pin_mismatch")
        bound[arm] = AdapterBinding(pin=pin, predict=adapter, preflight=adapter.preflight)
    return bound

