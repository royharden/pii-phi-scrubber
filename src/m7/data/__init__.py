"""Corpus/custody producer API. CorpusBundle is evaluator-private, never detector input."""
from .models import (
    Ancestor, BlockAssignment, CorpusBundle, CorpusManifest, CorpusPlan, Family,
    FamilyInventory, GoldRow, Lexicon, Recipe, RecordProvenance, SealAuthorization,
    Segment, SplitAudit,
)
from .provenance import allocate_blocks, audit_inventory, canonical_bytes, commitment, family_components
from .corpus import generate_development, inference_records, near_duplicate_audit, seal_corpus, verify_bundle
from .lifecycle import CustodyLifecycle, freeze_binding
from .lifecycle_models import (
    CustodyActionAuthorization, CustodyRelease, FreezeReceipt, OpenReceipt, ReleaseAuthorization,
    RevokeReceipt, SealReceipt, SelectionLockReference, SupersedeReceipt, TrainingExportAuthorization,
)
from .exports import TrainingChannels, released_channels, training_channels, write_released_channels, write_training_channels
from .access import IsolationCapability, IsolationGuard, IsolationRequest, IsolationVerifier, VerifiedIsolation, require_isolation
from .filesystem import CustodyFilesystem, CustodyPathPolicy, ExportCommitment, FilesystemPolicyApproval, checked_path
from .audit_handoff import AuditHandoff, IndependentAuditVerdict, build_audit_handoff, verify_independent_audit
from .native_windows import WindowsIsolationVerifier, WindowsWorkerProcessVerifier
from .native_windows_models import (
    NativeObservation, NativeQualificationResult, WindowsControlVerifier, WindowsPolicyEvidence, WindowsProcessApproval,
)
from .native_controls import ReadOnlyWindowsControlVerifier
from .native_context_registry import BorrowedContextRegistry
from .native_d6_context import D6WindowsContextProvider
from .native_controls_models import (
    BorrowedNativeContext, ControlQualificationReport, ExternalControlFact, ExternalControlObservation,
    MitigationRequirement, NativeContextBinding, NativeControlContextProvider, NativeExternalObservationProvider,
    NativeHandleBinding, WindowsControlPolicy,
)

__all__ = [
    'Ancestor', 'BlockAssignment', 'CorpusBundle', 'CorpusManifest', 'CorpusPlan', 'Family',
    'FamilyInventory', 'GoldRow', 'Lexicon', 'Recipe', 'RecordProvenance', 'SealAuthorization',
    'Segment', 'SplitAudit', 'allocate_blocks', 'audit_inventory', 'canonical_bytes',
    'commitment', 'family_components', 'generate_development', 'inference_records',
    'near_duplicate_audit', 'seal_corpus', 'verify_bundle',
    'CustodyLifecycle', 'freeze_binding', 'CustodyActionAuthorization', 'CustodyRelease',
    'FreezeReceipt', 'OpenReceipt', 'ReleaseAuthorization', 'RevokeReceipt', 'SealReceipt',
    'SelectionLockReference', 'SupersedeReceipt', 'TrainingExportAuthorization', 'TrainingChannels',
    'released_channels', 'training_channels', 'write_released_channels', 'write_training_channels',
    'IsolationCapability', 'IsolationGuard', 'IsolationRequest', 'IsolationVerifier', 'VerifiedIsolation',
    'require_isolation', 'CustodyFilesystem', 'CustodyPathPolicy', 'ExportCommitment',
    'FilesystemPolicyApproval', 'checked_path', 'AuditHandoff', 'IndependentAuditVerdict',
    'build_audit_handoff', 'verify_independent_audit',
    'WindowsIsolationVerifier', 'WindowsWorkerProcessVerifier', 'NativeObservation', 'NativeQualificationResult',
    'WindowsControlVerifier', 'WindowsPolicyEvidence', 'WindowsProcessApproval',
    'ReadOnlyWindowsControlVerifier', 'BorrowedContextRegistry', 'D6WindowsContextProvider', 'BorrowedNativeContext', 'ControlQualificationReport',
    'ExternalControlFact', 'ExternalControlObservation', 'MitigationRequirement', 'NativeContextBinding',
    'NativeControlContextProvider', 'NativeExternalObservationProvider', 'NativeHandleBinding', 'WindowsControlPolicy',
]
