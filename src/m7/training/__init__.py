"""Canonical training source; no model or filesystem effects at import."""
from .executor import (
    EngineResult, TrainingCancelled, TrainingEngine, TrainingOOM, TrialContext, execute_training,
)
from .validation import validate_training_plan, validate_training_receipt, validate_training_outcome
from .dataset import prepare_training_dataset
from .selection_models import (
    ClassTarget, DevEvaluation, DevSelectionPolicy, NumericalTargets, PreTestLockApproval,
    PreTestSelectionLock, SelectionRule,
)
from .selection import DevRecord, select_checkpoint
from .checkpoints import configuration_from_export, export_checkpoint, verify_checkpoint_export, verify_parity
from .locking import (
    create_pre_test_lock, export_pre_test_lock, justify_targets, lock_binding,
    selection_lock_reference, verify_pre_test_lock,
)
from .recovery import RecoveryAuthorization, recover_training_run
from .campaign_models import (
    CampaignActivationReceipt, CampaignAllocation, CampaignBudget, CampaignResources, CampaignSpec,
    SelectedArtifactManifest,
)
from .campaign import (
    CampaignHost, CampaignProducer, PreparedCampaign, SelectedCampaignProducer, build_selected_artifacts,
    campaign_arm_pins, export_prepared_campaign, prepare_campaign, validate_campaign,
)
from .launch_bundle import (
    LaunchBundlePreparationReceipt, PreparedLaunchBundle, WorkerLaunchBundle, WorkerLaunchDescriptor,
    WorkerLaunchHandoff, build_worker_launch_bundle, d7_worker_definitions, export_launch_bundle, load_launch_bundle,
    parse_launch_bundle, prepare_launch_bundle, validate_campaign_edition, validate_launch_bundle,
)
from .timing_resources import (
    CashBalance, PreparedTimingResources, TimingArmBound, TimingCashSnapshot,
    TimingHandoffPreparation, TimingResourceAuthority, TimingResourceAuthorization,
    TimingResourceReceipt, TimingResourceSchedule, TimingResourcesHandoff,
    build_timing_resource_schedule, export_timing_handoff, load_timing_handoff,
    normalize_timing_cash_snapshot, prepare_timing_handoff, validate_timing_handoff,
    validate_timing_resources,
)

__all__ = ["EngineResult", "TrainingCancelled", "TrainingEngine", "TrainingOOM", "TrialContext",
           "execute_training", "validate_training_plan", "validate_training_receipt", "prepare_training_dataset",
           "validate_training_outcome", "ClassTarget", "DevEvaluation", "DevSelectionPolicy", "NumericalTargets",
           "PreTestLockApproval", "PreTestSelectionLock", "SelectionRule", "DevRecord", "select_checkpoint",
           "configuration_from_export", "export_checkpoint", "verify_checkpoint_export", "verify_parity", "create_pre_test_lock",
           "export_pre_test_lock", "justify_targets", "lock_binding", "selection_lock_reference",
           "verify_pre_test_lock", "RecoveryAuthorization", "recover_training_run",
           "CampaignActivationReceipt", "CampaignAllocation", "CampaignBudget", "CampaignResources",
           "CampaignSpec", "SelectedArtifactManifest", "CampaignHost", "CampaignProducer", "PreparedCampaign",
           "SelectedCampaignProducer", "build_selected_artifacts", "campaign_arm_pins",
           "export_prepared_campaign", "prepare_campaign", "validate_campaign",
           "LaunchBundlePreparationReceipt", "PreparedLaunchBundle", "WorkerLaunchBundle", "WorkerLaunchDescriptor",
           "WorkerLaunchHandoff", "build_worker_launch_bundle", "export_launch_bundle", "load_launch_bundle",
           "parse_launch_bundle", "prepare_launch_bundle", "validate_launch_bundle", "d7_worker_definitions",
           "validate_campaign_edition", "CashBalance", "PreparedTimingResources", "TimingArmBound",
           "TimingCashSnapshot", "TimingHandoffPreparation", "TimingResourceAuthority", "TimingResourceAuthorization",
           "TimingResourceReceipt", "TimingResourceSchedule", "TimingResourcesHandoff",
           "build_timing_resource_schedule", "export_timing_handoff", "load_timing_handoff",
           "normalize_timing_cash_snapshot", "prepare_timing_handoff", "validate_timing_handoff",
           "validate_timing_resources"]
