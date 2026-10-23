"""Selected local inference artifacts and future operator handoff. No execution."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Callable, Protocol
from urllib.parse import urlsplit

from m7.providers.contracts import LocalModelConfig, config_digest, verify_artifacts
from m7.providers.parity import validate_pair
from .artifacts import no_links, tree_sha256
from .campaign_models import CampaignActivationReceipt, CampaignSpec, SelectedArtifactManifest
from .checkpoints import verify_parity
from .executor import _write_json
from .locking import verify_pre_test_lock
from .selection import authenticate, Verifier
from .selection_models import NumericalTargets, PreTestLockApproval, PreTestSelectionLock
from .validation import digest, now_utc, utc, validate_training_receipt

if TYPE_CHECKING:
    from m7.data.access import IsolationGuard

_TOKENIZER_FILES = {"tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json",
                    "vocab.txt", "vocab.json", "merges.txt", "spm.model", "spiece.model", "tokenizer.model",
                    "sentencepiece.bpe.model"}


def _relative(value: str) -> PurePosixPath:
    if (not value or "\\" in value or ":" in value or value.startswith("/") or
            any(p in ("", ".", "..") for p in value.split("/"))):
        raise ValueError("invalid_inference_artifact_subdirectory")
    return PurePosixPath(value)


def _layout(config: LocalModelConfig, *, check_files: bool) -> Path:
    """Closed inference-only layout. Never allow data/receipts/scripts as assets."""
    root = Path(config.artifact_root)
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("absolute_local_inference_root_required")
    model, backbone = _relative(config.model_subdir), _relative(config.backbone_subdir)
    if model == backbone or model.is_relative_to(backbone) or backbone.is_relative_to(model):
        raise ValueError("distinct_model_backbone_subdirectories_required")
    observed = set()
    for pin in config.files:
        name = _relative(pin.relative_path)
        if pin.relative_path in observed:
            raise ValueError("duplicate_inference_file_pin")
        observed.add(pin.relative_path)
        if name.parent == model:
            allowed = _TOKENIZER_FILES | {"model.safetensors", "gliner_config.json"}
        elif name.parent == backbone:
            allowed = _TOKENIZER_FILES | {"model.safetensors", "config.json"}
        else:
            raise ValueError("non_inference_file_in_artifact_manifest")
        if name.name not in allowed:
            raise ValueError("incompatible_checkpoint_layout")
    required = {f"{model}/model.safetensors", f"{model}/gliner_config.json",
                f"{backbone}/config.json", f"{backbone}/tokenizer_config.json"}
    if not required <= observed or not any(f"{backbone}/{name}" in observed for name in
                                         ("tokenizer.json", "spm.model", "spiece.model", "tokenizer.model", "vocab.txt", "vocab.json")):
        raise ValueError("incomplete_checkpoint_tokenizer_layout")
    if check_files:
        # Reuse D4's stricter lexical/root/reparse/hardlink path policy. This is
        # still path validation, not a substitute for its native isolation guard.
        from m7.data.filesystem import checked_path
        root = checked_path(root)
        for pin in config.files:
            checked_path(root / pin.relative_path)
        verify_artifacts(config)  # D6's canonical closed manifest/weight/tokenizer validation.
        root = root.resolve(strict=True)
    return root


def build_selected_artifacts(*, training_plan: dict, training_permit: dict, training_receipt: dict,
                             training_run: dict, checkpoint_export: dict, selection: dict, parity: dict,
                             lock: PreTestSelectionLock, targets: NumericalTargets, justification: dict,
                             approval: PreTestLockApproval, base: LocalModelConfig, finetuned: LocalModelConfig,
                             training_root: Path, verify_receipt: Verifier) -> SelectedArtifactManifest:
    """Create a manifest from real supplied receipts; never train/select/convert."""
    validate_training_receipt(training_receipt, training_plan, training_permit)
    verify_pre_test_lock(lock, selection=selection, parity=parity, justification=justification,
                         approval=approval, verify_receipt=verify_receipt)
    authenticate(verify_receipt, "training_run_closeout", digest(training_run))
    if (digest(training_run) != selection["training_run_closeout_sha256"] or
            digest(training_receipt) != lock.selected_training_receipt_sha256 or
            training_receipt["checkpoint_sha256"] != lock.selected_checkpoint_sha256 or
            config_digest(base) != lock.base_configuration_sha256 or
            config_digest(finetuned) != lock.finetuned_configuration_sha256 or
            digest(targets.model_dump(mode="json")) != lock.targets_sha256):
        raise ValueError("selected_training_lock_lineage_mismatch")
    from m7.data.filesystem import checked_path
    training_root = checked_path(training_root)
    roots = [_layout(cfg, check_files=True) for cfg in (base, finetuned)]
    for root in roots:
        if root.is_relative_to(training_root) or training_root.is_relative_to(root):
            raise ValueError("training_data_root_must_not_be_worker_artifact_root")
    if roots[0].is_relative_to(roots[1]) or roots[1].is_relative_to(roots[0]):
        raise ValueError("base_fine_inference_roots_must_be_separate")
    actual_parity = verify_parity(base, finetuned, receipt=training_receipt, plan=training_plan,
        permit=training_permit, export=checkpoint_export, verify_receipt=verify_receipt)
    if digest(parity) != digest(actual_parity):
        raise ValueError("selected_parity_receipt_mismatch")
    authenticate(verify_receipt, "parity_receipt", digest(parity))
    accounting = training_run["accounting"]
    if accounting is None or accounting.get("authorization_id") != training_permit["authorization_id"]:
        raise ValueError("training_accounting_closeout_required")
    manifest = SelectedArtifactManifest(
        edition_id=lock.edition_id, training_plan_sha256=digest(training_plan),
        training_receipt_sha256=digest(training_receipt), training_run_closeout_sha256=digest(training_run),
        checkpoint_export_sha256=digest(checkpoint_export),
        original_checkpoint_sha256=training_receipt["checkpoint_sha256"],
        exported_artifact_tree_sha256=checkpoint_export["artifact_tree_sha256"],
        dev_selection_receipt_sha256=digest(selection), selection_lock_sha256=lock.sha256,
        parity_receipt_sha256=digest(parity), training_artifact_hashes=training_receipt["artifact_hashes"],
        prior_known_training_cash_micros=accounting["known_provider_cash_micros"],
        prior_unknown_training_liability_micros=accounting["unresolved_liability_micros"],
        seed=training_receipt["seed"], optimizer_steps=training_receipt["optimizer_steps"],
        epochs=float(training_receipt["epochs"]), base=base, finetuned=finetuned)
    return SelectedArtifactManifest.model_validate_json(manifest.model_dump_json())


def validate_campaign(spec: CampaignSpec, *, check_files: bool = False,
                      clock: Callable[[], datetime] = now_utc) -> dict:
    """Structural/read-only validation; never authentication or activation."""
    spec = CampaignSpec.model_validate_json(spec.model_dump_json())
    selected, lock, resources = spec.selected, spec.selection_lock, spec.resources
    if (spec.edition_id != selected.edition_id or spec.edition_id != lock.edition_id or
            spec.experiment_plan_sha256 != lock.experiment_plan_sha256 or
            spec.corpus_manifest_sha256 != lock.corpus_manifest_sha256 or
            selected.selection_lock_sha256 != lock.sha256 or
            selected.training_plan_sha256 != lock.training_plan_sha256 or
            selected.training_receipt_sha256 != lock.selected_training_receipt_sha256 or
            selected.original_checkpoint_sha256 != lock.selected_checkpoint_sha256 or
            selected.dev_selection_receipt_sha256 != lock.dev_selection_receipt_sha256 or
            selected.parity_receipt_sha256 != lock.parity_receipt_sha256 or
            config_digest(selected.base) != lock.base_configuration_sha256 or
            config_digest(selected.finetuned) != lock.finetuned_configuration_sha256 or
            digest(spec.targets.model_dump(mode="json")) != lock.targets_sha256 or
            resources.local_license_packet_sha256 != selected.training_artifact_hashes["license_packet"] or
            resources.provider_terms_sha256 != spec.frontier.provider_terms_sha256 or
            spec.budget.training_run_closeout_sha256 != selected.training_run_closeout_sha256 or
            spec.budget.prior_known_training_cash_micros != selected.prior_known_training_cash_micros or
            spec.budget.prior_unknown_training_liability_micros != selected.prior_unknown_training_liability_micros):
        raise ValueError("campaign_selected_lock_or_cost_binding_mismatch")
    if not utc(lock.locked_at) <= utc(spec.issued_at) <= clock() < utc(spec.expires_at) <= utc(lock.expires_at):
        raise ValueError("campaign_or_lock_expired")
    validate_pair(selected.base, selected.finetuned)
    roots = [_layout(cfg, check_files=check_files) for cfg in (selected.base, selected.finetuned)]
    if roots[0].is_relative_to(roots[1]) or roots[1].is_relative_to(roots[0]):
        raise ValueError("overlapping_inference_artifact_roots")
    if check_files and tree_sha256(roots[1]) != selected.exported_artifact_tree_sha256:
        raise ValueError("selected_export_artifact_tree_mismatch")
    endpoint = urlsplit(spec.frontier.endpoint)
    if (endpoint.scheme != "https" or not endpoint.netloc or endpoint.username or endpoint.password or
            endpoint.query or endpoint.fragment):
        raise ValueError("credential_free_approved_https_endpoint_required")
    configs = {"base": selected.base, "finetuned": selected.finetuned, "frontier": spec.frontier}
    permits = {p.model_id: p for p in spec.permits}
    if len(permits) != 3 or len({c.model_id for c in configs.values()}) != 3:
        raise ValueError("unique_per_arm_model_permits_required")
    for arm, cfg in configs.items():
        policy, allocation = spec.policies[arm], spec.budget.allocations[arm]
        permit = permits.get(cfg.model_id)
        if permit is None:
            raise ValueError("campaign_model_permit_missing")
        permit.check(run_id=spec.run_id, model_id=cfg.model_id,
            scope="frontier_inference" if arm == "frontier" else "local_inference",
            config_sha256=config_digest(cfg), now=clock(),
            attempt_policy_sha256=digest(policy.model_dump(mode="json")))
        if (utc(permit.expires_at) < utc(spec.expires_at) or
                permit.authorization_sha256 != resources.cost_authorization_sha256 or
                permit.license_receipt_sha256 != (resources.provider_license_receipt_sha256 if arm == "frontier"
                                                  else resources.local_inference_license_receipt_sha256) or
                permit.resource_receipt_sha256 != (resources.provider_resource_receipt_sha256 if arm == "frontier"
                                                   else resources.local_hardware_receipt_sha256) or
                policy.authorization_id != allocation.authorization_id or
                policy.authorization_cap_micros != allocation.cash_cap_micros or
                policy.max_records < allocation.max_logical_calls or
                allocation.max_logical_calls < spec.intended_records * 4 or
                allocation.cash_cap_micros < allocation.max_logical_calls * policy.worst_case_micros *
                    (1 + policy.max_transient_retries)):
            raise ValueError("campaign_resource_or_attempt_budget_mismatch")
        if arm == "frontier":
            policy.require_frontier_bound(cfg)
    return {"schema_version": "CampaignValidation/v1", "campaign_sha256": spec.sha256,
        "selected_artifacts_sha256": selected.sha256,
        "status": "files_verified_not_authenticated" if check_files else "structure_valid_not_authenticated",
        "activation_allowed": False, "runtime_executed": False,
        "remaining_permissions": ["authenticated_current_receipts", "local_inference_license_permission",
                                  "local_hardware_authorization", "provider_license_terms_and_resource_permission",
                                  "actual_platform_isolation", "custody_release", "evaluation_authorization",
                                  "combined_training_inference_cash_authorization"]}


def campaign_arm_pins(spec: CampaignSpec):
    """D7 canonical ArmPin projection; no duplicated selection or pin schema."""
    from m7.experiment.models import ArmPin
    return (
        ArmPin(arm="regex", model_id=spec.regex_model_id, artifact_sha256=spec.regex_artifact_sha256,
               configuration_sha256=spec.regex_configuration_sha256),
        ArmPin(arm="frontier", model_id=spec.frontier.model_id,
               artifact_sha256=spec.frontier.model_revision_sha256, configuration_sha256=config_digest(spec.frontier)),
        ArmPin(arm="base", model_id=spec.selected.base.model_id,
               artifact_sha256=spec.selected.base.weights_sha256, configuration_sha256=config_digest(spec.selected.base)),
        ArmPin(arm="finetuned", model_id=spec.selected.finetuned.model_id,
               artifact_sha256=spec.selected.finetuned.weights_sha256, configuration_sha256=config_digest(spec.selected.finetuned)),
    )


@dataclass(frozen=True)
class CampaignHost:
    """Trusted D7/operator composition. No permissive verifier or sandbox stub."""
    verify_receipt: Verifier
    isolation_guard: IsolationGuard


@dataclass(frozen=True)
class PreparedCampaign:
    spec: CampaignSpec
    receipt: CampaignActivationReceipt


class CampaignProducer(Protocol):
    def validate(self, spec: CampaignSpec, *, check_files: bool = False) -> dict: ...
    def prepare(self, spec: CampaignSpec, *, host: CampaignHost) -> PreparedCampaign: ...


def prepare_campaign(spec: CampaignSpec, *, host: CampaignHost,
                     clock: Callable[[], datetime] = now_utc) -> PreparedCampaign:
    """Future explicit activation prepares a handoff; never spawns workers/models."""
    if host is None or host.isolation_guard is None or not callable(host.verify_receipt):
        raise ValueError("campaign_activation_host_required")
    spec = CampaignSpec.model_validate_json(spec.model_dump_json())
    validate_campaign(spec, check_files=True, clock=clock)
    selected, resources = spec.selected, spec.resources
    for kind, sha in (
        ("campaign_spec", spec.sha256), ("selected_artifact_manifest", selected.sha256),
        ("training_receipt", selected.training_receipt_sha256),
        ("training_run_closeout", selected.training_run_closeout_sha256),
        ("checkpoint_export", selected.checkpoint_export_sha256),
        ("pre_test_selection_lock", spec.selection_lock.sha256), ("parity_receipt", selected.parity_receipt_sha256),
        ("numerical_targets", spec.selection_lock.targets_sha256),
        ("target_justification", spec.selection_lock.target_justification_sha256),
        ("pre_test_lock_approval", spec.selection_lock.approval_sha256),
        ("license_packet", resources.local_license_packet_sha256),
        ("local_inference_license", resources.local_inference_license_receipt_sha256),
        ("local_hardware", resources.local_hardware_receipt_sha256),
        ("provider_license", resources.provider_license_receipt_sha256),
        ("provider_resource", resources.provider_resource_receipt_sha256),
        ("provider_terms", resources.provider_terms_sha256),
        ("campaign_cash_authorization", resources.cost_authorization_sha256),
        ("custody_release", resources.custody_release_sha256),
        ("evaluation_authorization", resources.evaluation_authorization_sha256),
        ("independent_audit", resources.independent_audit_sha256),
        ("adoption_policy", spec.adoption_policy_sha256), ("timing_plan", spec.timing_plan_sha256),
    ):
        authenticate(host.verify_receipt, kind, sha)
    for permit in spec.permits:
        authenticate(host.verify_receipt, "adapter_permit", digest(permit.model_dump(mode="json")))
    for policy in spec.policies.values():
        authenticate(host.verify_receipt, "attempt_policy", digest(policy.model_dump(mode="json")))
        authenticate(host.verify_receipt, "rate_quote", policy.rate_receipt_sha256)
    if host.isolation_guard.sha256 != resources.isolation_capability_sha256:
        raise ValueError("campaign_isolation_capability_mismatch")
    isolation = host.isolation_guard.require_current(spec.edition_id, spec.corpus_manifest_sha256,
        filesystem_policy_sha256=resources.filesystem_policy_sha256,
        worker_policy_sha256=resources.worker_policy_sha256)
    receipt = CampaignActivationReceipt(campaign_id=spec.campaign_id, edition_id=spec.edition_id,
        run_id=spec.run_id, campaign_sha256=spec.sha256, selected_artifacts_sha256=selected.sha256,
        selection_lock_sha256=spec.selection_lock.sha256,
        isolation_capability_sha256=isolation.capability_sha256, isolation_request_sha256=isolation.request_sha256,
        resources_sha256=digest(resources.model_dump(mode="json")),
        budget_sha256=digest(spec.budget.model_dump(mode="json")), prepared_at=clock().isoformat(),
        expires_at=spec.expires_at)
    return PreparedCampaign(spec, receipt)


class SelectedCampaignProducer:
    def validate(self, spec: CampaignSpec, *, check_files: bool = False) -> dict:
        return validate_campaign(spec, check_files=check_files)

    def prepare(self, spec: CampaignSpec, *, host: CampaignHost) -> PreparedCampaign:
        return prepare_campaign(spec, host=host)


def export_prepared_campaign(prepared: PreparedCampaign, directory: Path, *, host: CampaignHost) -> dict:
    """Recheck current authority before immutable handoff persistence."""
    current = prepare_campaign(prepared.spec, host=host)
    if current.spec.sha256 != prepared.receipt.campaign_sha256:
        raise ValueError("prepared_campaign_binding_mismatch")
    for path in (directory, *directory.parents):
        no_links(path)
    directory = directory.resolve(strict=True)
    if any(directory.is_relative_to(Path(cfg.artifact_root).resolve(strict=True))
           for cfg in (current.spec.selected.base, current.spec.selected.finetuned)):
        raise ValueError("handoff_must_be_outside_worker_artifact_roots")
    target = directory / (current.spec.campaign_id + ".campaign.json")
    envelope = {"schema_version": "PreparedCampaignExport/v1", "campaign": current.spec.model_dump(mode="json"),
                "campaign_sha256": current.spec.sha256, "activation": current.receipt.model_dump(mode="json"),
                "activation_sha256": digest(current.receipt.model_dump(mode="json"))}
    _write_json(target, envelope)
    return {"status": "immutable_handoff_written_no_evaluation", "campaign_sha256": current.spec.sha256,
            "runtime_executed": False}
