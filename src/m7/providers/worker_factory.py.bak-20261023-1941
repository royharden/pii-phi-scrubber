"""Fixed application-owned active-arm factory, never imports a wire-supplied plugin.

Frontier execution needs actual trusted-host qualification. No provider, tokenizer,
credential lookup, estimated token count or permissive qualification is a default.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import Field

from m7.contracts import Boundary, Digest, Identifier
from m7.detectors.attempts import AttemptController, Ledger
from m7.detectors.registry import DetectorAdapter, RegexAdapter
from .contracts import AdapterFault, FrontierConfig, LocalModelConfig, config_digest
from .frontier import HttpsChatTransport, PermittedFrontier, TokenCounter
from .local import PermittedLocalBackend
from .parity import validate_pair
from .worker_wire import WorkerBootstrap


class FrontierWorkerQualification(Boundary):
    schema_version: Literal["FrontierWorkerQualification/v1"] = "FrontierWorkerQualification/v1"
    qualification_id: Identifier
    run_id: Identifier
    model_id: Identifier
    provider_model: Identifier
    configuration_sha256: Digest
    provider_terms_sha256: Digest
    token_counter_sha256: Digest
    factory_source_sha256: Digest
    counter_qualification_sha256: Digest
    credential_boundary_sha256: Digest
    issued_at: Annotated[str, Field(min_length=1, max_length=64)]
    expires_at: Annotated[str, Field(min_length=1, max_length=64)]


class FrontierRuntimeVerifier(Protocol):
    def verify(self, qualification: FrontierWorkerQualification, config: FrontierConfig,
               counter: TokenCounter) -> bool:
        """Authenticate actual pinned provider/model/tokenizer/framing implementation
        and credential isolation. Counter methods must be local/pure: no provider
        request, credential lookup or telemetry during preflight. Unknown semantics are unavailable;
        no guessed framing constant, model-name heuristic or approval-shaped flag.
        """
        ...


@dataclass(frozen=True)
class QualifiedFrontierRuntime:
    qualification: FrontierWorkerQualification
    counter: TokenCounter = field(repr=False)
    credential: Callable[[], str] = field(repr=False)
    verify_receipt: Callable[[str, str], bool] = field(repr=False)
    verifier: FrontierRuntimeVerifier = field(repr=False)

    def require_current(self, config: FrontierConfig, run_id: str):
        q = self.qualification
        try:
            issued = datetime.fromisoformat(q.issued_at.replace("Z", "+00:00"))
            expires = datetime.fromisoformat(q.expires_at.replace("Z", "+00:00"))
            if (issued.tzinfo is None or expires.tzinfo is None
                    or not issued <= datetime.now(timezone.utc) < expires
                    or q.run_id != run_id or q.model_id != config.model_id
                    or q.provider_model != config.provider_model or q.configuration_sha256 != config_digest(config)
                    or q.provider_terms_sha256 != config.provider_terms_sha256
                    or q.token_counter_sha256 != config.token_counter_sha256):
                raise AdapterFault("permit_required")
            if q.token_counter_sha256 != self.counter.sha256:
                raise AdapterFault("permit_required")
            if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != q.factory_source_sha256:
                raise AdapterFault("permit_required")
            for kind, digest in (("frontier_worker_runtime", config_digest(q)),
                                 ("frontier_token_counter", q.counter_qualification_sha256),
                                 ("frontier_credential_boundary", q.credential_boundary_sha256)):
                if self.verify_receipt(kind, digest) is not True:
                    raise AdapterFault("permit_required")
            if self.verifier is None or self.verifier.verify(q, config, self.counter) is not True:
                raise AdapterFault("permit_required")
        except BaseException:
            raise AdapterFault("permit_required") from None


class _QualifiedCounter:
    def __init__(self, runtime: QualifiedFrontierRuntime, config: FrontierConfig, run_id: str):
        self.runtime, self.config, self.run_id = runtime, config, run_id

    @property
    def sha256(self):
        self.runtime.require_current(self.config, self.run_id)
        return self.config.token_counter_sha256

    def request_tokens(self, payload: dict) -> int:
        self.runtime.require_current(self.config, self.run_id)
        return self.runtime.counter.request_tokens(payload)

    def completion_tokens(self, content: str) -> int:
        self.runtime.require_current(self.config, self.run_id)
        return self.runtime.counter.completion_tokens(content)


class FixedWorkerFactory:
    def __init__(self, frontier_runtime: QualifiedFrontierRuntime | None = None):
        self.frontier_runtime = frontier_runtime

    def __call__(self, bootstrap: WorkerBootstrap, ledgers: Mapping[str, Ledger],
                 sink: Callable[[dict], None], cancelled: Callable[[], bool]):
        arm = bootstrap.pin.arm
        if arm == "regex":
            return {"regex": RegexAdapter(bootstrap.run_id)}
        # Fine's base config is PURE parity metadata: no backend/loader/registry
        # construction, no path probe, no artifact read or preflight for that arm.
        if arm == "finetuned":
            validate_pair(bootstrap.configs["base"], bootstrap.configs["finetuned"])
        config, permit, policy = bootstrap.configs[arm], bootstrap.permits[arm], bootstrap.policies[arm]
        if set(ledgers) != {arm}:
            raise AdapterFault("permit_required")
        permit.check(run_id=bootstrap.run_id, model_id=config.model_id,
            scope="frontier_inference" if arm == "frontier" else "local_inference",
            config_sha256=config_digest(config), attempt_policy_sha256=config_digest(policy))
        if arm == "frontier":
            if not isinstance(config, FrontierConfig) or self.frontier_runtime is None:
                raise AdapterFault("unavailable")
            runtime = self.frontier_runtime
            runtime.require_current(config, bootstrap.run_id)
            policy.require_frontier_bound(config)
            counter = _QualifiedCounter(runtime, config, bootstrap.run_id)
            def credential():
                runtime.require_current(config, bootstrap.run_id)
                return runtime.credential()  # In-memory trusted host boundary, not a file/env lookup.
            transport = HttpsChatTransport(credential)
            backend = PermittedFrontier(config, permit, run_id=bootstrap.run_id,
                transport=transport, counter=counter, allow_execution=True)
        else:
            if not isinstance(config, LocalModelConfig) or config.arm != arm:
                raise AdapterFault("permit_required")
            backend = PermittedLocalBackend(config, permit, run_id=bootstrap.run_id, allow_execution=True)
        controller = AttemptController(run_id=bootstrap.run_id, arm=arm, model_id=config.model_id,
            policy=policy, ledger=ledgers[arm], cancelled=cancelled, diagnostic_sink=sink)
        return {arm: DetectorAdapter(bootstrap.run_id, arm, config.model_id, backend, controller)}
