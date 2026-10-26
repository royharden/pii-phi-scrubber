"""Read-only training facts for readiness composition; never an execution permit."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Literal

from pydantic import field_validator

from m7.contracts import Boundary, Digest
from m7.providers.contracts import AdapterFault, LocalModelConfig, config_digest
from m7.providers.parity import validate_pair
from .artifacts import check_installed_environment, inspect_artifacts, no_links
from .validation import digest, validate_training_plan

Diagnostic = Literal[
    "training_plan_missing",
    "training_permit_missing",
    "training_contract_invalid",
    "artifact_root_missing",
    "local_artifact_missing",
    "local_artifact_invalid",
    "training_dependency_unavailable",
    "training_environment_mismatch",
    "configuration_parity_invalid",
]


class TrainingArtifactFacts(Boundary):
    schema_version: Literal["TrainingArtifactFacts/v1"] = "TrainingArtifactFacts/v1"
    evidence_kind: Literal["readiness"] = "readiness"
    input_status: Literal["missing_plan", "missing_permit", "invalid", "validated"]
    artifact_status: Literal["not_inspected", "missing", "invalid", "verified"] = "not_inspected"
    environment_status: Literal["not_checked", "unavailable", "mismatch", "matched"] = "not_checked"
    parity_status: Literal["not_supplied", "invalid", "declared_compatible"] = "not_supplied"
    plan_sha256: Digest | None = None
    permit_sha256: Digest | None = None
    base_configuration_sha256: Digest | None = None
    finetuned_configuration_sha256: Digest | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    training_status: Literal["not_run"] = "not_run"
    actual_training_observed: Literal[False] = False
    execution_allowed_now: Literal[False] = False
    m7_02_accepted: Literal[False] = False

    @field_validator("actual_training_observed", "execution_allowed_now", "m7_02_accepted", mode="before")
    @classmethod
    def false_flags_are_booleans(cls, value):
        # Literal[False] alone accepts integer zero even in strict Pydantic mode.
        if value is not False:
            raise ValueError("readiness_false_boolean_required")
        return value


def _configuration(value: LocalModelConfig | dict) -> LocalModelConfig:
    payload = value.model_dump(mode="json") if isinstance(value, LocalModelConfig) else value
    return LocalModelConfig.model_validate_json(json.dumps(payload, allow_nan=False))


def inspect_training_readiness(
    plan: dict | None = None,
    permit: dict | None = None,
    *,
    staging_root: Path | str | None = None,
    base: LocalModelConfig | dict | None = None,
    finetuned: LocalModelConfig | dict | None = None,
    at: datetime | None = None,
) -> TrainingArtifactFacts:
    """Reuse canonical validators and project only hashes/closed diagnostics.

    No model import, training, ledger/run creation, download or approval occurs.
    Local manifest booleans are structural claims, not authenticated rights.
    Parity compares immutable configuration declarations without reading their roots.
    A caller may inspect only its explicitly approved staging root; no search/fallback.
    """
    fields: dict = {"input_status": "missing_plan"}
    diagnostics: list[Diagnostic] = []
    if base is not None or finetuned is not None:
        try:
            first, second = _configuration(base), _configuration(finetuned)
            validate_pair(first, second)
            fields.update(
                parity_status="declared_compatible",
                base_configuration_sha256=config_digest(first),
                finetuned_configuration_sha256=config_digest(second),
            )
        except (AdapterFault, ValueError, TypeError):
            fields["parity_status"] = "invalid"
            diagnostics.append("configuration_parity_invalid")
    if plan is None:
        diagnostics.append("training_plan_missing")
    elif permit is None:
        fields["input_status"] = "missing_permit"
        diagnostics.append("training_permit_missing")
    else:
        try:
            # Detach mutable caller input before validating or inspecting pins.
            plan = json.loads(json.dumps(plan, allow_nan=False))
            permit = json.loads(json.dumps(permit, allow_nan=False))
            if type(plan) is not dict or plan.get("schema_version") != "TrainingPlan/v2":
                raise ValueError("execution_requires_v2_plan")
            validate_training_plan(plan, permit, at=at)
            fields.update(input_status="validated", plan_sha256=digest(plan), permit_sha256=digest(permit))
        except (ValueError, TypeError, KeyError, OverflowError):
            fields["input_status"] = "invalid"
            diagnostics.append("training_contract_invalid")
    if fields["input_status"] == "validated":
        if staging_root is None:
            fields["artifact_status"] = "missing"
            diagnostics.append("artifact_root_missing")
        else:
            try:
                root = Path(staging_root)
                if not root.is_absolute():
                    raise ValueError("absolute_artifact_root_required")
                for part in (root, *root.parents):
                    no_links(part)
                root = root.resolve(strict=True)
                _, metadata = inspect_artifacts(plan, root, check_environment=False)
                fields["artifact_status"] = "verified"
            except FileNotFoundError:
                fields["artifact_status"] = "missing"
                diagnostics.append("local_artifact_missing")
            except (OSError, ValueError, TypeError, KeyError):
                fields["artifact_status"] = "invalid"
                diagnostics.append("local_artifact_invalid")
            else:
                try:
                    check_installed_environment(metadata["environment"])
                    fields["environment_status"] = "matched"
                except ValueError as exc:
                    if exc.args == ("training_dependency_unavailable",):
                        fields["environment_status"] = "unavailable"
                        diagnostics.append("training_dependency_unavailable")
                    else:
                        fields["environment_status"] = "mismatch"
                        diagnostics.append("training_environment_mismatch")
    fields["diagnostics"] = tuple(diagnostics)
    return TrainingArtifactFacts(**fields)
