"""Canonical value-free development selection and pre-test lock contracts."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from m7.contracts import Boundary, Digest, Identifier, Prediction
from m7.providers.contracts import LocalModelConfig
from .validation import digest, utc

Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
LABELS = ("NAME", "EMAIL", "PHONE", "ACCOUNT_ID")


class SelectionRule(Boundary):
    schema_version: Literal["DevSelectionRule/v1"] = "DevSelectionRule/v1"
    name: Literal["dev_macro_exact_f1_then_recall_then_lower_cost"] = "dev_macro_exact_f1_then_recall_then_lower_cost"
    thresholds: Annotated[tuple[Probability, ...], Field(min_length=1, max_length=21)]
    bootstrap_seed: Annotated[int, Field(ge=0, le=4294967295)]
    bootstrap_draws: Literal[2000] = 2000
    minimum_blocks: Literal[20] = 20
    minimum_valid_draws: Literal[1800] = 1800
    cost_policy: Literal["actual_else_reserved_upper_bound"] = "actual_else_reserved_upper_bound"

    @model_validator(mode="after")
    def coherent(self):
        if tuple(sorted(set(self.thresholds))) != self.thresholds:
            raise ValueError("threshold_grid_must_be_unique_sorted")
        return self

    @property
    def sha256(self) -> str:
        return digest(self.model_dump(mode="json"))


class DevSelectionPolicy(Boundary):
    schema_version: Literal["DevSelectionPolicy/v1"] = "DevSelectionPolicy/v1"
    edition_id: Identifier
    experiment_plan_sha256: Digest
    training_plan_sha256: Digest
    dev_sha256: Digest
    rule: SelectionRule
    registered_at: str

    @model_validator(mode="after")
    def timestamp(self):
        utc(self.registered_at)
        return self


class DevEvaluation(Boundary):
    """Actual measured predictions, externally authenticated before selection."""
    schema_version: Literal["DevEvaluation/v1"] = "DevEvaluation/v1"
    evaluation_id: Identifier
    execution_kind: Literal["actual_dev_evaluation"]
    edition_id: Identifier
    dev_sha256: Digest
    policy_sha256: Digest
    trial_id: Identifier | None = None
    checkpoint_export_sha256: Digest | None = None
    config: LocalModelConfig
    predictions: tuple[Prediction, ...]
    measured_at: str

    @model_validator(mode="after")
    def coherent(self):
        utc(self.measured_at)
        fine = self.config.arm == "finetuned"
        if fine != (self.trial_id is not None) or fine != (self.checkpoint_export_sha256 is not None):
            raise ValueError("development_trial_binding_required")
        return self


class ClassTarget(Boundary):
    precision: Probability = 0.90
    recall: Probability = 0.95
    recall_lower_95: Probability = 0.90

    @model_validator(mode="after")
    def coherent(self):
        if self.recall_lower_95 > self.recall:
            raise ValueError("target_lower_bound_exceeds_point_target")
        return self


class NumericalTargets(Boundary):
    schema_version: Literal["NumericalTargets/v1"] = "NumericalTargets/v1"
    per_class: dict[str, ClassTarget]
    structure_failures: Literal[0] = 0
    intended_record_accounting: Literal[1.0] = 1.0
    positive_fine_minus_base_macro_f1_ci: Literal[True] = True
    no_increase_residual_leak: Literal[True] = True
    failure_action: Literal["retain_benchmark_recommend_no_deployment"] = "retain_benchmark_recommend_no_deployment"

    @model_validator(mode="after")
    def labels(self):
        if set(self.per_class) != set(LABELS):
            raise ValueError("all_class_targets_required")
        return self


class PreTestLockApproval(Boundary):
    schema_version: Literal["PreTestLockApproval/v1"] = "PreTestLockApproval/v1"
    approval_id: Identifier
    approved_by: Identifier
    approved: Literal[True]
    allowed_action: Literal["lock_targets_before_heldout"]
    binding_sha256: Digest
    issued_at: str
    expires_at: str

    @model_validator(mode="after")
    def timestamp(self):
        if utc(self.expires_at) <= utc(self.issued_at):
            raise ValueError("invalid_lock_approval_window")
        return self


class PreTestSelectionLock(Boundary):
    schema_version: Literal["PreTestSelectionLock/v1"] = "PreTestSelectionLock/v1"
    edition_id: Identifier
    experiment_plan_sha256: Digest
    training_plan_sha256: Digest
    corpus_manifest_sha256: Digest
    selection_rule_sha256: Digest
    dev_selection_receipt_sha256: Digest
    selected_training_receipt_sha256: Digest
    selected_checkpoint_sha256: Digest
    base_configuration_sha256: Digest
    finetuned_configuration_sha256: Digest
    parity_receipt_sha256: Digest
    target_justification_sha256: Digest
    targets_sha256: Digest
    approval_sha256: Digest
    locked_at: str
    expires_at: str

    @model_validator(mode="after")
    def timestamp(self):
        if utc(self.expires_at) <= utc(self.locked_at):
            raise ValueError("invalid_lock_window")
        return self

    @property
    def sha256(self) -> str:
        # Same canonical JSON digest as D4/D7. No self-digest field.
        return digest(self.model_dump(mode="json"))
