"""One internally consistent, value-free campaign world for R5 structural tests.

Build order follows the adopted acyclic seam (SEAM-DECISION-WORKER-PROFILE-R1,
D5-E-API): configs -> arm pins -> timing plan -> resource schedule -> bootstraps
(with timing pins) -> launch members -> profile P -> full launch policies (L)
-> CampaignSpec. Every hash is a hand-chosen constant or a canonical digest used
only to BUILD a consistent input; tests never assert against values computed
by the function under test. No files exist at the absolute paths below: every
caller uses check_files=False, so nothing is read, loaded or started.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from m7.experiment.models import ArmPin, PopulationMember, commitment
from m7.experiment.timing_contracts import HardwareContext, IsolatedTimingPlan, TimingLengthSlice
from m7.providers.contracts import (
    AttemptPolicy, DecoderConfig, ExecutionPermit, FilePin, FrontierConfig, LocalModelConfig, config_digest,
)
from m7.providers.worker_profile import (
    WorkerLaunchMember, WorkerLaunchPolicy, WorkerProfile, launch_member_digest, worker_profile_digest,
)
from m7.providers.worker_wire import WorkerBootstrap, WorkerLimits, WorkerPin
from m7.training.campaign_models import (
    CampaignAllocation, CampaignBudget, CampaignResources, CampaignSpec, SelectedArtifactManifest,
)
from m7.training.selection_models import ClassTarget, NumericalTargets, PreTestSelectionLock
from m7.training.timing_resources import build_timing_resource_schedule
from m7.training.validation import ARTIFACTS, digest

CLOCK = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
ARMS = ("regex", "frontier", "base", "finetuned")
PAID = ("base", "finetuned", "frontier")
N = 2              # intended records
WORST = 10         # micros per attempt
ROOT = Path(Path.cwd().anchor) / "m7-r5-fixture"   # absolute on Windows and POSIX; never created
REGEX_CONFIG_SHA = hashlib.sha256(b'{"model_id":"context-regex-v1"}').hexdigest()  # registry.py constant


def h(c: str) -> str:
    return c * 64


def local(arm: str, *, root: Path, weights: str, threshold: float) -> LocalModelConfig:
    files = tuple(FilePin(relative_path=p, sha256=h(c)) for p, c in (
        ("model/model.safetensors", weights[0]), ("model/gliner_config.json", "2"),
        ("backbone/config.json", "3"), ("backbone/tokenizer_config.json", "4"), ("backbone/tokenizer.json", "5")))
    return LocalModelConfig(
        arm=arm, model_id="gliner-" + arm, base_revision="small-v2-1", base_weights_sha256=h("a"),
        architecture_sha256=h("b"), training_receipt_sha256=None if arm == "base" else h("c"),
        artifact_root=str(root), model_subdir="model", backbone_subdir="backbone", files=files,
        weights_sha256=weights, tokenizer_sha256=h("d"), gliner_version="0.2.1", transformers_version="4.40.0",
        decoder=DecoderConfig(threshold=threshold, threshold_selection_sha256=h("e")),
        max_input_tokens=512, max_words=256)


@dataclass
class World:
    base: LocalModelConfig
    fine: LocalModelConfig
    frontier: FrontierConfig
    policies: dict
    permits: tuple
    budget: CampaignBudget
    resources: CampaignResources
    plan: IsolatedTimingPlan
    schedule: object
    bootstraps: dict
    members: dict
    profile: WorkerProfile
    launches: dict
    spec: CampaignSpec
    extra: dict = field(default_factory=dict)


def build(*, frontier_retries: int = 0, frontier_cap: int = 100) -> World:
    base = local("base", root=ROOT / "base", weights=h("a"), threshold=0.5)
    fine = local("finetuned", root=ROOT / "fine", weights=h("f"), threshold=0.6)
    frontier = FrontierConfig(model_id="frontier-m", provider_model="provider-model-1", model_revision_sha256=h("1"),
        endpoint="https://api.example.test/v1", provider_terms_sha256=h("6"), prompt_sha256=h("7"),
        token_counter_sha256=h("8"), max_input_tokens=1000, max_output_tokens=100, context_window_tokens=2048)
    configs = {"base": base, "finetuned": fine, "frontier": frontier}

    # Allocation: 4N = 8 logical calls (primary + three timing passes); cap >= 8 * w * (1 + r).
    allocations = {arm: CampaignAllocation(authorization_id="alloc-" + arm,
                                           cash_cap_micros=frontier_cap if arm == "frontier" else 100,
                                           max_logical_calls=4 * N) for arm in PAID}
    budget = CampaignBudget(currency="USD", total_authorized_cash_micros=500, prior_known_training_cash_micros=0,
                            prior_unknown_training_liability_micros=100, training_run_closeout_sha256=h("9"),
                            allocations=allocations)
    policies = {arm: AttemptPolicy(policy_id="pol-" + arm, authorization_id="alloc-" + arm, rate_receipt_sha256=h("0"),
                                   max_transient_retries=frontier_retries if arm == "frontier" else 0,
                                   authorization_cap_micros=allocations[arm].cash_cap_micros, worst_case_micros=WORST,
                                   max_records=4 * N,
                                   input_micros_per_million_tokens=1000 if arm == "frontier" else None,
                                   output_micros_per_million_tokens=1000 if arm == "frontier" else None)
                for arm in PAID}
    resources = CampaignResources(local_license_packet_sha256=h("1"), local_inference_license_receipt_sha256=h("2"),
        local_hardware_receipt_sha256=h("3"), provider_license_receipt_sha256=h("4"),
        provider_resource_receipt_sha256=h("5"), provider_terms_sha256=frontier.provider_terms_sha256,
        cost_authorization_sha256=h("7"), custody_release_sha256=h("8"), evaluation_authorization_sha256=h("9"),
        independent_audit_sha256=h("a"), filesystem_policy_sha256=h("b"), worker_policy_sha256=h("0"),  # P set below
        isolation_capability_sha256=h("c"))
    permits = tuple(ExecutionPermit(permit_id="permit-" + arm, run_id="run-1", model_id=cfg.model_id,
        scope="frontier_inference" if arm == "frontier" else "local_inference", config_sha256=config_digest(cfg),
        authorization_sha256=resources.cost_authorization_sha256,
        license_receipt_sha256=resources.provider_license_receipt_sha256 if arm == "frontier"
        else resources.local_inference_license_receipt_sha256,
        resource_receipt_sha256=resources.provider_resource_receipt_sha256 if arm == "frontier"
        else resources.local_hardware_receipt_sha256,
        issued_at="2026-01-01T00:00:00Z", expires_at="2026-01-31T00:00:00Z", approved=True,
        attempt_policy_sha256=digest(policies[arm].model_dump(mode="json"))) for arm, cfg in configs.items())
    by_model = {p.model_id: p for p in permits}

    pins = (ArmPin(arm="regex", model_id="context-regex-v1", artifact_sha256=h("e"), configuration_sha256=REGEX_CONFIG_SHA),
            ArmPin(arm="frontier", model_id=frontier.model_id, artifact_sha256=frontier.model_revision_sha256,
                   configuration_sha256=config_digest(frontier)),
            ArmPin(arm="base", model_id=base.model_id, artifact_sha256=base.weights_sha256, configuration_sha256=config_digest(base)),
            ArmPin(arm="finetuned", model_id=fine.model_id, artifact_sha256=fine.weights_sha256,
                   configuration_sha256=config_digest(fine)))
    order = (PopulationMember(record_id="rec-2", content_sha256=h("2")), PopulationMember(record_id="rec-1", content_sha256=h("1")))
    population = commitment([m.model_dump(mode="json") for m in sorted(order, key=lambda m: m.record_id)])
    plan = IsolatedTimingPlan(edition_id="ed-1", run_id="run-1", population_sha256=population, record_order=order,
        arm_pins=pins, environment_sha256=h("3"), package_lock_sha256=h("4"), hardware_receipt_sha256=h("5"),
        hardware=HardwareContext(cpu="cpu-x", gpu=None, ram_gib=16.0, driver="none", precision="fp32",
                                 package_lock_sha256=h("4"), environment_sha256=h("3")),
        length_slices=(TimingLengthSlice(minimum=0, maximum=1024),))
    schedule = build_timing_resource_schedule(plan, policies=policies, budget=budget)

    required = {"regex": (), "frontier": ("frontier",), "base": ("base",), "finetuned": ("base", "finetuned")}
    bootstraps = {arm: WorkerBootstrap(session_id="sess-" + arm, run_id="run-1",
        pin=WorkerPin(**pin.model_dump()), limits=WorkerLimits(max_records=N),
        configs={k: configs[k] for k in required[arm]}, permits={k: by_model[configs[k].model_id] for k in required[arm]},
        policies={k: policies[k] for k in required[arm]},
        timing_plan_sha256=plan.sha256, timing_order_sha256=plan.order_sha256)
        for arm, pin in zip(ARMS, pins)}
    roots = {"base": base.artifact_root, "finetuned": fine.artifact_root}
    members = {arm: WorkerLaunchMember(arm=arm, edition_id="ed-1", corpus_manifest_sha256=h("6"),
        filesystem_policy_sha256=resources.filesystem_policy_sha256, bootstrap_sha256=config_digest(bootstraps[arm]),
        application_manifest_sha256=h("7"), runtime_environment_sha256=h("8"),
        executable=str(ROOT / "py" / "python.exe"), executable_sha256=h("9"),
        entrypoint=str(ROOT / "app" / "worker.py"), entrypoint_sha256=h("a"),
        working_directory=str(ROOT / "work" / arm), artifact_root=roots.get(arm)) for arm in ARMS}
    profile = WorkerProfile(profile_id="profile-1", members={arm: launch_member_digest(m) for arm, m in members.items()})
    p = worker_profile_digest(profile)
    launches = {arm: WorkerLaunchPolicy(**m.model_dump(), profile_sha256=p) for arm, m in members.items()}
    resources = resources.model_copy(update={"worker_policy_sha256": p})
    resources = CampaignResources.model_validate_json(resources.model_dump_json())

    targets = NumericalTargets(per_class={label: ClassTarget() for label in ("NAME", "EMAIL", "PHONE", "ACCOUNT_ID")})
    lock = PreTestSelectionLock(edition_id="ed-1", experiment_plan_sha256=h("1"), training_plan_sha256=h("2"),
        corpus_manifest_sha256=h("6"), selection_rule_sha256=h("3"), dev_selection_receipt_sha256=h("4"),
        selected_training_receipt_sha256=h("5"), selected_checkpoint_sha256=h("7"),
        base_configuration_sha256=config_digest(base), finetuned_configuration_sha256=config_digest(fine),
        parity_receipt_sha256=h("8"), target_justification_sha256=h("9"),
        targets_sha256=digest(targets.model_dump(mode="json")), approval_sha256=h("a"),
        locked_at="2026-01-01T00:00:00+00:00", expires_at="2026-02-01T00:00:00+00:00")
    selected = SelectedArtifactManifest(edition_id="ed-1", training_plan_sha256=h("2"), training_receipt_sha256=h("5"),
        training_run_closeout_sha256=budget.training_run_closeout_sha256, checkpoint_export_sha256=h("b"),
        original_checkpoint_sha256=h("7"), exported_artifact_tree_sha256=h("c"), dev_selection_receipt_sha256=h("4"),
        selection_lock_sha256=lock.sha256, parity_receipt_sha256=h("8"),
        training_artifact_hashes={k: (resources.local_license_packet_sha256 if k == "license_packet" else h("d"))
                                  for k in ARTIFACTS},
        prior_known_training_cash_micros=0, prior_unknown_training_liability_micros=100,
        seed=1, optimizer_steps=10, epochs=1.0, base=base, finetuned=fine)
    spec = CampaignSpec(campaign_id="camp-1", edition_id="ed-1", run_id="run-1", experiment_plan_sha256=h("1"),
        corpus_manifest_sha256=h("6"), population_sha256=population, intended_records=N, selected=selected,
        selection_lock=lock, targets=targets, adoption_policy_sha256=h("e"), timing_plan_sha256=plan.sha256,
        timing_resource_schedule_sha256=schedule.sha256, frontier=frontier, regex_model_id="context-regex-v1",
        regex_artifact_sha256=h("e"), regex_configuration_sha256=REGEX_CONFIG_SHA, permits=permits,
        policies=policies, worker_profile=profile, launch_policies=launches, resources=resources, budget=budget,
        issued_at="2026-01-05T00:00:00Z", expires_at="2026-01-20T00:00:00Z")
    return World(base, fine, frontier, policies, permits, budget, resources, plan, schedule, bootstraps,
                 members, profile, launches, spec)


def respec(world: World, **updates) -> CampaignSpec:
    """Revalidated copy of the spec with top-level fields replaced."""
    data = world.spec.model_dump(mode="json")
    data.update({k: (v.model_dump(mode="json") if hasattr(v, "model_dump") else v) for k, v in updates.items()})
    return CampaignSpec.model_validate_json(json.dumps(data))
