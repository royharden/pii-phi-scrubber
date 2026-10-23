"""Pure campaign/worker joins and explicit authenticated handoff; never launches."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Callable, Literal

from pydantic import model_validator

from m7.contracts import Boundary, Digest
from m7.providers.contracts import config_digest
from m7.providers.worker_profile import WorkerLaunchPolicy, WorkerMembership, validate_worker_membership, worker_profile_digest
from m7.providers.worker_wire import MAX_BOOTSTRAP_BYTES, InitCommand, WorkerBootstrap, encode_line
from .campaign import CampaignHost, PreparedCampaign, campaign_arm_pins, prepare_campaign, validate_campaign
from .campaign_models import CampaignActivationReceipt, CampaignSpec
from .executor import _write_json
from .selection import authenticate
from .validation import digest, now_utc, utc

ARMS = ("regex", "frontier", "base", "finetuned")
MAX_BUNDLE_BYTES = 12_000_000
MAX_HANDOFF_BYTES = 16_000_000


def _encoded(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


class WorkerLaunchBundle(Boundary):
    schema_version: Literal["WorkerLaunchBundle/v1"] = "WorkerLaunchBundle/v1"
    campaign: CampaignSpec
    campaign_sha256: Digest
    profile_sha256: Digest
    bootstraps: dict[str, WorkerBootstrap]
    memberships: dict[str, WorkerMembership]

    @model_validator(mode="after")
    def all_arms(self):
        if set(self.bootstraps) != set(ARMS) or set(self.memberships) != set(ARMS):
            raise ValueError("four_exact_worker_arms_required")
        return self

    @property
    def sha256(self) -> str:
        return digest(self.model_dump(mode="json"))


class LaunchBundlePreparationReceipt(Boundary):
    schema_version: Literal["LaunchBundlePreparationReceipt/v1"] = "LaunchBundlePreparationReceipt/v1"
    bundle_sha256: Digest
    campaign_sha256: Digest
    profile_sha256: Digest
    launch_sha256_by_arm: dict[str, Digest]
    bootstrap_sha256_by_arm: dict[str, Digest]
    campaign_activation_sha256: Digest
    prepared_at: str
    expires_at: str
    status: Literal["prelaunch_qualified_no_worker_started_no_heldout_open"] = "prelaunch_qualified_no_worker_started_no_heldout_open"
    runtime_executed: Literal[False] = False


class WorkerLaunchHandoff(Boundary):
    schema_version: Literal["WorkerLaunchHandoff/v1"] = "WorkerLaunchHandoff/v1"
    bundle: WorkerLaunchBundle
    bundle_sha256: Digest
    campaign_activation: CampaignActivationReceipt
    preparation: LaunchBundlePreparationReceipt


@dataclass(frozen=True)
class WorkerLaunchDescriptor:
    """D7 parent-only dispatch values. No launcher/provider plugin path is added."""
    arm: str
    bootstrap: WorkerBootstrap
    policy: WorkerLaunchPolicy
    membership: WorkerMembership


@dataclass(frozen=True)
class PreparedLaunchBundle:
    bundle: WorkerLaunchBundle
    campaign: PreparedCampaign
    receipt: LaunchBundlePreparationReceipt

    def descriptors(self) -> tuple[WorkerLaunchDescriptor, ...]:
        if (self.bundle.sha256 != self.receipt.bundle_sha256 or
                self.campaign.spec.sha256 != self.bundle.campaign_sha256):
            raise ValueError("prepared_launch_bundle_mutated")
        return tuple(WorkerLaunchDescriptor(arm, self.bundle.bootstraps[arm],
            self.bundle.campaign.launch_policies[arm], self.bundle.memberships[arm]) for arm in ARMS)


def validate_launch_bundle(bundle: WorkerLaunchBundle, *, check_files: bool = False,
                           clock: Callable[[], datetime] = now_utc) -> dict:
    """Pure definition/pin join by default. No worker/service/native imports."""
    bundle = WorkerLaunchBundle.model_validate_json(bundle.model_dump_json())
    spec = bundle.campaign
    validate_campaign(spec, check_files=check_files, clock=clock)
    if len(_encoded(bundle.model_dump(mode="json"))) > MAX_BUNDLE_BYTES:
        raise ValueError("joined_worker_bundle_too_large")
    if (bundle.campaign_sha256 != spec.sha256 or
            bundle.profile_sha256 != worker_profile_digest(spec.worker_profile) or
            bundle.profile_sha256 != spec.resources.worker_policy_sha256):
        raise ValueError("worker_bundle_campaign_profile_mismatch")
    # D6 supplies both wire models and canonical membership/config hashing. The
    # producer only joins them to the already approved selected campaign.
    expected_pins = {p.arm: p for p in campaign_arm_pins(spec)}
    configs = {"base": spec.selected.base, "finetuned": spec.selected.finetuned, "frontier": spec.frontier}
    permits = {p.model_id: p for p in spec.permits}
    session_ids, working_directories = set(), []
    for arm in ARMS:
        bootstrap, policy = bundle.bootstraps[arm], spec.launch_policies[arm]
        membership = validate_worker_membership(spec.worker_profile, policy)
        pin = expected_pins[arm]
        if (bundle.memberships[arm] != membership or policy.arm != arm or bootstrap.pin.arm != arm or
                bootstrap.run_id != spec.run_id or bootstrap.pin.model_dump(mode="json") != pin.model_dump(mode="json") or
                config_digest(bootstrap) != policy.bootstrap_sha256 or
                bootstrap.limits.lifetime_seconds != policy.lifetime_seconds or
                bootstrap.limits.max_records != spec.intended_records or bootstrap.session_id in session_ids):
            raise ValueError("worker_bootstrap_pin_run_or_limit_mismatch")
        session_ids.add(bootstrap.session_id)
        directory = Path(policy.working_directory)
        if any(directory == prior or directory.is_relative_to(prior) or prior.is_relative_to(directory)
               for prior in working_directories):
            raise ValueError("worker_working_directories_must_be_disjoint")
        working_directories.append(directory)
        # Use D6's actual framed init serializer, including command/newline
        # overhead; a bootstrap-only estimate could exceed the physical line cap.
        encode_line(InitCommand(session_id=bootstrap.session_id, bootstrap=bootstrap), limit=MAX_BOOTSTRAP_BYTES)
        required = () if arm == "regex" else ("base", "finetuned") if arm == "finetuned" else (arm,)
        # Schema already enforces minimal sets; compare exact byte commitments
        # rather than trusting a duplicated model/version/threshold description.
        for key in required:
            cfg = configs[key]
            if (config_digest(bootstrap.configs[key]) != config_digest(cfg) or
                    config_digest(bootstrap.permits[key]) != config_digest(permits[cfg.model_id]) or
                    config_digest(bootstrap.policies[key]) != config_digest(spec.policies[key])):
                raise ValueError("worker_bootstrap_not_selected_campaign_configuration")
        if arm in ("base", "finetuned") and policy.artifact_root != configs[arm].artifact_root:
            raise ValueError("worker_active_artifact_root_mismatch")
        # Base metadata is needed for fine parity, but is not an active base load
        # in the fine worker. It is never rewritten to alias the fine root.
    from m7.detectors.registry import RegexAdapter
    regex = RegexAdapter(spec.run_id)
    if (regex.model_id != spec.regex_model_id or regex.configuration_sha256 != spec.regex_configuration_sha256 or
            check_files and regex.artifact_sha256 != spec.regex_artifact_sha256):
        raise ValueError("regex_source_or_version_not_campaign_pin")
    return {"schema_version": "WorkerLaunchBundleValidation/v1", "bundle_sha256": bundle.sha256,
        "campaign_sha256": spec.sha256, "profile_sha256": bundle.profile_sha256,
        "launch_sha256_by_arm": {arm: bundle.memberships[arm].launch_sha256 for arm in ARMS},
        "status": "files_checked_not_authenticated" if check_files else "structure_valid_not_authenticated",
        "activation_allowed": False, "worker_started": False, "heldout_opened": False}


def d7_worker_definitions(bundle: WorkerLaunchBundle):
    """Use D7's as-built internal view, never introduce another serialized wire."""
    from m7.experiment.isolated import WorkerDefinition
    return {arm: WorkerDefinition(bootstrap=bundle.bootstraps[arm], launch=bundle.campaign.launch_policies[arm])
            for arm in ARMS}


def validate_campaign_edition(bundle: WorkerLaunchBundle, edition, *,
                              clock: Callable[[], datetime] = now_utc) -> dict:
    """D7 loader join of known commitments only; no custody read/open or workers."""
    from m7.experiment.models import LockedEdition
    if not isinstance(edition, LockedEdition):
        raise ValueError("d7_locked_edition_required")
    validate_launch_bundle(bundle, clock=clock)
    edition = LockedEdition.model_validate_json(edition.model_dump_json())
    spec = bundle.campaign
    expected_population = digest([row.model_dump(mode="json") for row in edition.population])
    if (spec.edition_id != edition.edition_id or spec.run_id != edition.run_id or
            spec.experiment_plan_sha256 != edition.plan_sha256 or
            spec.corpus_manifest_sha256 != edition.corpus_manifest_sha256 or
            spec.population_sha256 != expected_population or spec.intended_records != len(edition.population) or
            spec.selection_lock.sha256 != edition.selection_lock_sha256 or
            spec.resources.custody_release_sha256 != edition.custody_release_sha256 or
            spec.resources.evaluation_authorization_sha256 != edition.execution_authorization_sha256 or
            spec.resources.independent_audit_sha256 != edition.independent_audit_sha256 or
            spec.adoption_policy_sha256 != digest(edition.adoption_policy.model_dump(mode="json")) or
            spec.timing_plan_sha256 != edition.timing_plan_sha256 or
            campaign_arm_pins(spec) != edition.arm_pins or utc(edition.expires_at) > utc(spec.expires_at)):
        raise ValueError("campaign_worker_bundle_not_locked_edition")
    if edition.adoption_policy.development_justification_sha256 != spec.selection_lock.target_justification_sha256:
        raise ValueError("campaign_target_justification_mismatch")
    for floor in edition.adoption_policy.per_class:
        target = spec.targets.per_class[floor.label]
        if (target.precision != floor.precision_minimum or target.recall != floor.recall_minimum or
                target.recall_lower_95 != floor.recall_lower95_minimum):
            raise ValueError("campaign_locked_target_floor_mismatch")
    edition.require_current(clock())
    return {"status": "edition_commitments_joined_not_opened", "bundle_sha256": bundle.sha256,
            "edition_sha256": edition.sha256, "worker_started": False, "heldout_opened": False}


def build_worker_launch_bundle(spec: CampaignSpec, bootstraps: dict[str, WorkerBootstrap], *,
                               clock: Callable[[], datetime] = now_utc) -> WorkerLaunchBundle:
    """No config/model selection, bootstrap repair, profile creation or approval."""
    memberships = {arm: validate_worker_membership(spec.worker_profile, policy)
                   for arm, policy in spec.launch_policies.items()}
    bundle = WorkerLaunchBundle(campaign=spec, campaign_sha256=spec.sha256,
        profile_sha256=worker_profile_digest(spec.worker_profile), bootstraps=bootstraps, memberships=memberships)
    validate_launch_bundle(bundle, clock=clock)
    return WorkerLaunchBundle.model_validate_json(bundle.model_dump_json())


def prepare_launch_bundle(bundle: WorkerLaunchBundle, *, host: CampaignHost,
                          clock: Callable[[], datetime] = now_utc) -> PreparedLaunchBundle:
    """Prelaunch qualification only: no PID/start-identity/process-proof dependency."""
    if host is None:
        raise ValueError("authenticated_launch_bundle_host_required")
    bundle = WorkerLaunchBundle.model_validate_json(bundle.model_dump_json())
    validate_launch_bundle(bundle, check_files=True, clock=clock)
    authenticate(host.verify_receipt, "worker_launch_bundle", bundle.sha256)
    for bootstrap in bundle.bootstraps.values():
        authenticate(host.verify_receipt, "worker_bootstrap", config_digest(bootstrap))
    campaign = prepare_campaign(bundle.campaign, host=host, clock=clock)
    receipt = LaunchBundlePreparationReceipt(bundle_sha256=bundle.sha256,
        campaign_sha256=bundle.campaign_sha256, profile_sha256=bundle.profile_sha256,
        launch_sha256_by_arm={arm: bundle.memberships[arm].launch_sha256 for arm in ARMS},
        bootstrap_sha256_by_arm={arm: bundle.memberships[arm].bootstrap_sha256 for arm in ARMS},
        campaign_activation_sha256=digest(campaign.receipt.model_dump(mode="json")),
        prepared_at=clock().isoformat(), expires_at=bundle.campaign.expires_at)
    return PreparedLaunchBundle(bundle, campaign, receipt)


def parse_launch_bundle(raw: bytes, *, clock: Callable[[], datetime] = now_utc) -> WorkerLaunchBundle:
    if type(raw) is not bytes or len(raw) > MAX_HANDOFF_BYTES:
        raise ValueError("worker_handoff_byte_limit")
    from m7.data.filesystem import strict_json
    obj = strict_json(raw)
    if type(obj) is not dict:
        raise ValueError("worker_handoff_object_required")
    if obj.get("schema_version") == "WorkerLaunchHandoff/v1":
        handoff = WorkerLaunchHandoff.model_validate_json(_encoded(obj))
        bundle = handoff.bundle
        preparation, activation = handoff.preparation, handoff.campaign_activation
        if (handoff.bundle_sha256 != bundle.sha256 or preparation.bundle_sha256 != bundle.sha256 or
                preparation.campaign_sha256 != bundle.campaign_sha256 or
                preparation.profile_sha256 != bundle.profile_sha256 or
                preparation.campaign_activation_sha256 != digest(activation.model_dump(mode="json")) or
                activation.campaign_sha256 != bundle.campaign_sha256 or
                activation.campaign_id != bundle.campaign.campaign_id or activation.edition_id != bundle.campaign.edition_id or
                activation.run_id != bundle.campaign.run_id or
                activation.selected_artifacts_sha256 != bundle.campaign.selected.sha256 or
                activation.selection_lock_sha256 != bundle.campaign.selection_lock.sha256 or
                activation.isolation_capability_sha256 != bundle.campaign.resources.isolation_capability_sha256 or
                activation.resources_sha256 != digest(bundle.campaign.resources.model_dump(mode="json")) or
                activation.budget_sha256 != digest(bundle.campaign.budget.model_dump(mode="json")) or
                activation.worker_profile_sha256 != bundle.profile_sha256 or
                preparation.expires_at != bundle.campaign.expires_at or activation.expires_at != bundle.campaign.expires_at or
                not utc(bundle.campaign.selection_lock.locked_at) <= utc(activation.prepared_at) <=
                    utc(preparation.prepared_at) <= clock() < utc(preparation.expires_at)):
            raise ValueError("worker_handoff_receipt_binding_mismatch")
        expected_launches = {arm: row.launch_sha256 for arm, row in bundle.memberships.items()}
        expected_bootstraps = {arm: row.bootstrap_sha256 for arm, row in bundle.memberships.items()}
        if (preparation.launch_sha256_by_arm != expected_launches or
                activation.launch_policy_sha256_by_arm != expected_launches or
                preparation.bootstrap_sha256_by_arm != expected_bootstraps):
            raise ValueError("worker_handoff_membership_receipt_mismatch")
    elif obj.get("schema_version") == "WorkerLaunchBundle/v1":
        bundle = WorkerLaunchBundle.model_validate_json(_encoded(obj))
    else:
        raise ValueError("unsupported_worker_handoff_schema")
    validate_launch_bundle(bundle, clock=clock)
    # Receipt parsing does not recreate PreparedLaunchBundle or claim authority.
    # A host must freshly call prepare_launch_bundle before any D7 dispatch.
    return bundle


def load_launch_bundle(path: Path, *, clock: Callable[[], datetime] = now_utc) -> WorkerLaunchBundle:
    from m7.data.filesystem import checked_path
    path = checked_path(path)
    if not path.is_file() or path.stat().st_size > MAX_HANDOFF_BYTES:
        raise ValueError("worker_handoff_file_limit")
    with path.open("rb") as stream:
        raw = stream.read(MAX_HANDOFF_BYTES + 1)
    return parse_launch_bundle(raw, clock=clock)


def export_launch_bundle(prepared: PreparedLaunchBundle, directory: Path, *, host: CampaignHost) -> dict:
    if prepared.bundle.sha256 != prepared.receipt.bundle_sha256:
        raise ValueError("prepared_launch_bundle_mutated")
    current = prepare_launch_bundle(prepared.bundle, host=host)
    handoff = WorkerLaunchHandoff(bundle=current.bundle, bundle_sha256=current.bundle.sha256,
                                  campaign_activation=current.campaign.receipt, preparation=current.receipt)
    value = handoff.model_dump(mode="json")
    if len(_encoded(value)) + 1 > MAX_HANDOFF_BYTES:
        raise ValueError("worker_handoff_too_large")
    from m7.data.filesystem import checked_path
    directory = checked_path(directory)
    for cfg in (current.bundle.campaign.selected.base, current.bundle.campaign.selected.finetuned):
        if directory.is_relative_to(checked_path(cfg.artifact_root)):
            raise ValueError("worker_handoff_must_be_outside_artifact_roots")
    target = directory / (current.bundle.campaign.campaign_id + ".workers.json")
    _write_json(target, value)
    return {"status": "immutable_worker_handoff_written_no_execution", "bundle_sha256": current.bundle.sha256,
            "handoff_sha256": digest(value), "worker_started": False, "heldout_opened": False}
