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
           "export_prepared_campaign", "prepare_campaign", "validate_campaign"]
