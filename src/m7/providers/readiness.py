"""Pure provider declaration facts; never an execution or authenticity grant."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import TypeAdapter, model_validator

from m7.contracts import Boundary, Digest, Identifier
from .contracts import (
    AdapterFault, AttemptPolicy, ExecutionPermit, FrontierConfig, LocalModelConfig,
    config_digest,
)
from .parity import validate_pair

ProviderArm = Literal["base", "finetuned", "frontier"]


class ProviderArmFact(Boundary):
    arm: ProviderArm
    status: Literal["missing", "shape_valid", "invalid"]
    reason: Literal["missing_declarations", "permit_required", "invalid_output",
                    "truncated", "backend_failure", "declarations_only"]
    configuration_sha256: Digest | None = None
    artifact_sha256: Digest | None = None

    @model_validator(mode="after")
    def coherent(self) -> ProviderArmFact:
        declared = self.status == "shape_valid"
        if ((self.reason == "declarations_only") != declared
                or (self.reason == "missing_declarations") != (self.status == "missing")
                or (self.configuration_sha256 is not None) != declared
                or (self.artifact_sha256 is not None) != declared):
            raise ValueError("invalid_provider_fact")
        return self


class ProviderFacts(Boundary):
    schema_version: Literal["ProviderFacts/v1"] = "ProviderFacts/v1"
    evidence_kind: Literal["readiness"] = "readiness"
    actual_model_execution: Literal[False] = False
    execution_allowed: Literal[False] = False
    arms: tuple[ProviderArmFact, ProviderArmFact, ProviderArmFact]

    @model_validator(mode="after")
    def ordered(self) -> ProviderFacts:
        if tuple(fact.arm for fact in self.arms) != ("base", "finetuned", "frontier"):
            raise ValueError("invalid_provider_fact_order")
        return self


def assess_provider_facts(
    configs: Mapping[str, LocalModelConfig | FrontierConfig] | None = None,
    permits: Mapping[str, ExecutionPermit] | None = None,
    policies: Mapping[str, AttemptPolicy] | None = None,
    *,
    run_id: str,
) -> ProviderFacts:
    """Inspect in-memory declarations using existing pure validators only.

    shape_valid does not authenticate receipts, inspect artifacts, qualify a
    tokenizer/host, or establish model execution. Missing declarations stay missing.
    Raw config fields and exception messages never enter the returned facts.
    """
    configs = {} if configs is None else configs
    permits = {} if permits is None else permits
    policies = {} if policies is None else policies
    arms = ("base", "finetuned", "frontier")
    try:
        TypeAdapter(Identifier).validate_python(run_id, strict=True)
    except Exception:
        raise ValueError("invalid_provider_declarations") from None
    if (any(not isinstance(items, Mapping) or set(items) - set(arms)
                   for items in (configs, permits, policies))):
        raise ValueError("invalid_provider_declarations")
    facts = []
    for arm in arms:
        present = tuple(arm in items for items in (configs, permits, policies))
        if not any(present):
            facts.append(ProviderArmFact(arm=arm, status="missing", reason="missing_declarations"))
            continue
        try:
            if not all(present):
                raise AdapterFault("permit_required")
            config, permit, policy = configs[arm], permits[arm], policies[arm]
            if (not isinstance(permit, ExecutionPermit) or not isinstance(policy, AttemptPolicy)
                    or (arm == "frontier" and not isinstance(config, FrontierConfig))
                    or (arm != "frontier" and
                        (not isinstance(config, LocalModelConfig) or config.arm != arm))):
                raise AdapterFault("permit_required")
            permit.check(run_id=run_id, model_id=config.model_id,
                         scope="frontier_inference" if arm == "frontier" else "local_inference",
                         config_sha256=config_digest(config),
                         attempt_policy_sha256=config_digest(policy))
            if arm == "frontier":
                policy.require_frontier_bound(config)
                artifact = config.model_revision_sha256
            else:
                artifact = config.weights_sha256
                if arm == "base":
                    if (config.base_weights_sha256 != config.weights_sha256
                            or config.training_receipt_sha256 is not None):
                        raise AdapterFault("permit_required")
                else:
                    base = configs.get("base")
                    if not isinstance(base, LocalModelConfig):
                        raise AdapterFault("permit_required")
                    validate_pair(base, config)
            facts.append(ProviderArmFact(arm=arm, status="shape_valid", reason="declarations_only",
                                        configuration_sha256=config_digest(config), artifact_sha256=artifact))
        except AdapterFault as error:
            facts.append(ProviderArmFact(arm=arm, status="invalid", reason=error.code))
        except Exception:
            # No backend/provider exception text, paths or source values are exposed.
            facts.append(ProviderArmFact(arm=arm, status="invalid", reason="invalid_output"))
    return ProviderFacts(arms=tuple(facts))
