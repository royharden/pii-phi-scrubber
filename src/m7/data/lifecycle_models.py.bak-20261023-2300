"""Value-free custody lifecycle receipts; no approval is manufactured here."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from m7.contracts import Boundary, Digest, Identifier
from .timing_models import TimingPhaseConsumed, TimingPhaseTerminal


class CustodyActionAuthorization(Boundary):
    schema_version: Literal['CustodyActionAuthorization/v1'] = 'CustodyActionAuthorization/v1'
    authorization_id: Identifier
    edition_id: Identifier
    action: Literal['freeze', 'revoke', 'supersede']
    binding_sha256: Digest
    issued_at: str
    expires_at: str


class FreezeReceipt(Boundary):
    schema_version: Literal['CustodyFreeze/v1'] = 'CustodyFreeze/v1'
    edition_id: Identifier
    custodian_id: Identifier
    inventory_sha256: Digest
    plan_sha256: Digest
    guide_sha256: Digest
    generator_sha256: Digest
    assignments_sha256: Digest
    selection_rule_sha256: Digest
    family_author_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    test_semantic_source_pins: Annotated[tuple[Digest, ...], Field(min_length=1)]
    split_seed: Annotated[int, Field(ge=0)]
    sampling_seed: Annotated[int, Field(ge=0)]
    benign_fraction: Annotated[float, Field(ge=0.2, lt=1, allow_inf_nan=False)]
    challenge_fraction: Annotated[float, Field(gt=0, lt=1, allow_inf_nan=False)]
    authorization_sha256: Digest
    frozen_at: str
    supersedes_edition_id: Identifier | None = None


class SealReceipt(Boundary):
    schema_version: Literal['CustodySeal/v1'] = 'CustodySeal/v1'
    edition_id: Identifier
    freeze_sha256: Digest
    corpus_manifest_sha256: Digest
    population_sha256: Digest
    intended_test_records: Annotated[int, Field(ge=1)]
    independent_audit_sha256: Digest
    authorization_sha256: Digest
    sealed_at: str


class SelectionLockReference(Boundary):
    """Host-authenticated projection of D5's full pre-test lock, not a second lock.

    Verifier authenticates BOTH the original D5 receipt and this projection's
    bindings. Host must check actual D5 schema/selection/parity, not copy strings.
    """
    schema_version: Literal['SelectionLockReference/v1'] = 'SelectionLockReference/v1'
    edition_id: Identifier
    receipt_sha256: Digest
    corpus_manifest_sha256: Digest
    selection_rule_sha256: Digest
    locked_at: str


class ReleaseAuthorization(Boundary):
    schema_version: Literal['CustodyReleaseAuthorization/v2'] = 'CustodyReleaseAuthorization/v2'
    authorization_id: Identifier
    edition_id: Identifier
    run_id: Identifier
    experiment_plan_sha256: Digest
    corpus_manifest_sha256: Digest
    population_sha256: Digest
    selection_lock_sha256: Digest
    independent_audit_sha256: Digest
    isolation_capability_sha256: Digest
    custodian_id: Identifier
    issued_at: str
    expires_at: str
    action: Literal['release_one_held_out_edition'] = 'release_one_held_out_edition'


class CustodyRelease(Boundary):
    schema_version: Literal['CustodyRelease/v2'] = 'CustodyRelease/v2'
    edition_id: Identifier
    run_id: Identifier
    experiment_plan_sha256: Digest
    freeze_sha256: Digest
    seal_sha256: Digest
    corpus_manifest_sha256: Digest
    population_sha256: Digest
    selection_lock_sha256: Digest
    selection_lock_reference_sha256: Digest
    independent_audit_sha256: Digest
    authorization_sha256: Digest
    isolation_capability_sha256: Digest
    filesystem_policy_sha256: Digest
    worker_policy_sha256: Digest
    custodian_id: Identifier
    released_at: str
    expires_at: str


class OpenReceipt(Boundary):
    schema_version: Literal['CustodyOpen/v1'] = 'CustodyOpen/v1'
    edition_id: Identifier
    run_id: Identifier
    locked_edition_sha256: Digest
    custody_release_sha256: Digest
    opened_at: str


class RevokeReceipt(Boundary):
    schema_version: Literal['CustodyRevoke/v1'] = 'CustodyRevoke/v1'
    edition_id: Identifier
    authorization_sha256: Digest
    reason_code: Literal['authorization_withdrawn', 'custody_compromised', 'source_changed', 'audit_invalidated']
    revoked_at: str


class SupersedeReceipt(Boundary):
    schema_version: Literal['CustodySupersede/v1'] = 'CustodySupersede/v1'
    edition_id: Identifier
    replacement_edition_id: Identifier
    authorization_sha256: Digest
    superseded_at: str


Receipt = (FreezeReceipt | SealReceipt | CustodyRelease | OpenReceipt | RevokeReceipt |
           SupersedeReceipt | TimingPhaseConsumed | TimingPhaseTerminal)


class CustodyEvent(Boundary):
    schema_version: Literal['CustodyEvent/v1'] = 'CustodyEvent/v1'
    sequence: Annotated[int, Field(ge=1)]
    previous_sha256: Digest
    receipt: Receipt


class TrainingExportAuthorization(Boundary):
    schema_version: Literal['TrainingExportAuthorization/v1'] = 'TrainingExportAuthorization/v1'
    authorization_id: Identifier
    edition_id: Identifier
    corpus_manifest_sha256: Digest
    split: Literal['train', 'dev']
    issued_at: str
    expires_at: str
    action: Literal['export_training_labels'] = 'export_training_labels'
