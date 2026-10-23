"""Narrow selected-artifact/campaign wire. No training or held-out file paths."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from m7.contracts import Boundary, Digest, Identifier
from m7.providers.contracts import AttemptPolicy, ExecutionPermit, FrontierConfig, LocalModelConfig
from m7.providers.worker_profile import WorkerLaunchPolicy, WorkerProfile
from .selection_models import NumericalTargets, PreTestSelectionLock
from .validation import ARTIFACTS, digest, utc

Cash = Annotated[int, Field(ge=0, le=9223372036854775807)]


class SelectedArtifactManifest(Boundary):
    schema_version: Literal["SelectedArtifactManifest/v1"] = "SelectedArtifactManifest/v1"
    edition_id: Identifier
    training_plan_sha256: Digest
    training_receipt_sha256: Digest
    training_run_closeout_sha256: Digest
    checkpoint_export_sha256: Digest
    original_checkpoint_sha256: Digest
    exported_artifact_tree_sha256: Digest
    dev_selection_receipt_sha256: Digest
    selection_lock_sha256: Digest
    parity_receipt_sha256: Digest
    training_artifact_hashes: dict[str, Digest]
    prior_known_training_cash_micros: Cash
    prior_unknown_training_liability_micros: Cash
    seed: Annotated[int, Field(ge=0, le=4294967295)]
    optimizer_steps: Annotated[int, Field(ge=1, le=1000)]
    epochs: Annotated[float, Field(gt=0, le=3, allow_inf_nan=False)]
    base: LocalModelConfig
    finetuned: LocalModelConfig

    @model_validator(mode="after")
    def complete(self):
        if set(self.training_artifact_hashes) != ARTIFACTS or self.base.arm != "base" or self.finetuned.arm != "finetuned":
            raise ValueError("incomplete_selected_artifact_manifest")
        return self

    @property
    def sha256(self) -> str:
        return digest(self.model_dump(mode="json"))


class CampaignResources(Boundary):
    schema_version: Literal["CampaignResources/v1"] = "CampaignResources/v1"
    local_license_packet_sha256: Digest
    local_inference_license_receipt_sha256: Digest
    local_hardware_receipt_sha256: Digest
    provider_license_receipt_sha256: Digest
    provider_resource_receipt_sha256: Digest
    provider_terms_sha256: Digest
    cost_authorization_sha256: Digest
    custody_release_sha256: Digest
    evaluation_authorization_sha256: Digest
    independent_audit_sha256: Digest
    filesystem_policy_sha256: Digest
    worker_policy_sha256: Digest
    isolation_capability_sha256: Digest


class CampaignAllocation(Boundary):
    authorization_id: Identifier
    cash_cap_micros: Cash
    max_logical_calls: Annotated[int, Field(ge=1, le=1000000)]


class CampaignBudget(Boundary):
    schema_version: Literal["CampaignBudget/v1"] = "CampaignBudget/v1"
    currency: Identifier
    total_authorized_cash_micros: Cash
    prior_known_training_cash_micros: Cash
    prior_unknown_training_liability_micros: Cash
    training_run_closeout_sha256: Digest
    allocations: dict[str, CampaignAllocation]
    economic_cost_status: Literal["requires_combined_training_and_inference_accounting"] = "requires_combined_training_and_inference_accounting"

    @model_validator(mode="after")
    def no_unfunded_calls(self):
        if set(self.allocations) != {"base", "finetuned", "frontier"}:
            raise ValueError("all_inference_allocations_required")
        ids = [row.authorization_id for row in self.allocations.values()]
        if len(set(ids)) != 3:
            raise ValueError("separate_allocation_authorizations_required")
        liability = self.prior_known_training_cash_micros + self.prior_unknown_training_liability_micros
        if liability + sum(row.cash_cap_micros for row in self.allocations.values()) > self.total_authorized_cash_micros:
            raise ValueError("combined_training_inference_cap_exceeded")
        return self


class CampaignSpec(Boundary):
    schema_version: Literal["CampaignSpec/v1"] = "CampaignSpec/v1"
    campaign_id: Identifier
    edition_id: Identifier
    run_id: Identifier
    experiment_plan_sha256: Digest
    corpus_manifest_sha256: Digest
    population_sha256: Digest
    intended_records: Annotated[int, Field(ge=1, le=1000000)]
    selected: SelectedArtifactManifest
    selection_lock: PreTestSelectionLock
    targets: NumericalTargets
    adoption_policy_sha256: Digest
    timing_plan_sha256: Digest
    frontier: FrontierConfig
    regex_model_id: Identifier
    regex_artifact_sha256: Digest
    regex_configuration_sha256: Digest
    permits: Annotated[tuple[ExecutionPermit, ...], Field(min_length=3, max_length=3)]
    policies: dict[str, AttemptPolicy]
    worker_profile: WorkerProfile
    launch_policies: dict[str, WorkerLaunchPolicy]
    resources: CampaignResources
    budget: CampaignBudget
    issued_at: str
    expires_at: str
    purpose: Literal["locked_synthetic_evaluation"] = "locked_synthetic_evaluation"

    @model_validator(mode="after")
    def all_required(self):
        if (set(self.policies) != {"base", "finetuned", "frontier"} or
                set(self.launch_policies) != {"regex", "base", "finetuned", "frontier"} or
                set(self.worker_profile.members) != set(self.launch_policies) or
                utc(self.expires_at) <= utc(self.issued_at)):
            raise ValueError("incomplete_campaign_specification")
        return self

    @property
    def sha256(self) -> str:
        return digest(self.model_dump(mode="json"))


class CampaignActivationReceipt(Boundary):
    schema_version: Literal["CampaignActivationReceipt/v1"] = "CampaignActivationReceipt/v1"
    campaign_id: Identifier
    edition_id: Identifier
    run_id: Identifier
    campaign_sha256: Digest
    selected_artifacts_sha256: Digest
    selection_lock_sha256: Digest
    isolation_capability_sha256: Digest
    isolation_request_sha256: Digest
    worker_profile_sha256: Digest
    launch_policy_sha256_by_arm: dict[str, Digest]
    resources_sha256: Digest
    budget_sha256: Digest
    prepared_at: str
    expires_at: str
    status: Literal["prepared_for_authorized_evaluator_not_executed"] = "prepared_for_authorized_evaluator_not_executed"
    runtime_executed: Literal[False] = False
