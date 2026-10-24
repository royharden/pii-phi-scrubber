"""Value-free timing authority/receipts; declarations grant no execution rights."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from m7.contracts import Arm, Boundary, Digest, Identifier
from .provenance import commitment


class TimingBackendPin(Boundary):
    arm: Arm
    identity_sha256: Digest
    launch_sha256: Digest


class CustodyTimingAuthorization(Boundary):
    schema_version: Literal['CustodyTimingAuthorization/v1'] = 'CustodyTimingAuthorization/v1'
    authorization_id: Identifier
    edition_id: Identifier
    run_id: Identifier
    edition_sha256: Digest
    custody_release_sha256: Digest
    experiment_plan_sha256: Digest
    corpus_manifest_sha256: Digest
    selection_lock_sha256: Digest
    primary_accounting_sha256: Digest
    timing_plan_sha256: Digest
    population_sha256: Digest
    order_sha256: Digest
    arm_pins_sha256: Digest
    worker_profile_sha256: Digest
    # Failed primary arms may have no surviving process. Absence is unavailable,
    # never a fabricated identity or permission to change the four-arm plan.
    backends: Annotated[tuple[TimingBackendPin, ...], Field(max_length=4)]
    isolation_capability_sha256: Digest
    filesystem_policy_sha256: Digest
    resource_authorization_sha256: Digest
    issued_at: str
    expires_at: str
    passes: Literal[3] = 3
    concurrency: Literal[1] = 1
    action: Literal['continue_original_warm_backends'] = 'continue_original_warm_backends'

    @model_validator(mode='after')
    def ordered_backends(self):
        arms = tuple(p.arm for p in self.backends)
        if arms != tuple(a for a in ('regex', 'frontier', 'base', 'finetuned') if a in arms):
            raise ValueError('timing_surviving_backend_subset_must_be_unique_ordered')
        if len({p.identity_sha256 for p in self.backends}) != len(self.backends):
            raise ValueError('timing_backend_identities_must_be_distinct')
        return self

    @property
    def sha256(self) -> str:
        return commitment(self)


class TimingPhaseConsumed(Boundary):
    schema_version: Literal['CustodyTimingConsumed/v1'] = 'CustodyTimingConsumed/v1'
    edition_id: Identifier
    run_id: Identifier
    edition_sha256: Digest
    custody_release_sha256: Digest
    authorization_sha256: Digest
    primary_accounting_sha256: Digest
    timing_plan_sha256: Digest
    request_sha256: Digest
    resource_receipt_sha256: Digest
    arm: Arm
    ordinal: Annotated[int, Field(ge=1, le=3)]
    attempt_namespace: Digest
    backend_identity_sha256: Digest
    worker_profile_sha256: Digest
    launch_sha256: Digest
    consumed_at: str
    expires_at: str


class TimingPhaseTerminal(Boundary):
    schema_version: Literal['CustodyTimingTerminal/v1'] = 'CustodyTimingTerminal/v1'
    edition_id: Identifier
    run_id: Identifier
    consumed_sha256: Digest
    request_sha256: Digest
    arm: Arm
    ordinal: Annotated[int, Field(ge=1, le=3)]
    # Completion means the phase protocol ended, not all predictions succeeded.
    outcome: Literal['completed', 'aborted']
    finished_at: str


TimingReceipt = TimingPhaseConsumed | TimingPhaseTerminal


def validate_timing_transition(receipt: TimingReceipt, previous: tuple[TimingReceipt, ...],
                               *, release, opened, active: bool) -> None:
    """Pure replay guard, including expiry/revocation and no replacement journal.

    An abort can be recorded after revocation/expiry. It never erases consumption
    or permits the failed arm to advance. Unknown begins block every new phase.
    """
    if release is None or opened is None:
        raise ValueError('timing_original_release_and_open_required')
    starts = [r for r in previous if isinstance(r, TimingPhaseConsumed)]
    ends = {r.consumed_sha256: r for r in previous if isinstance(r, TimingPhaseTerminal)}
    if isinstance(receipt, TimingPhaseConsumed):
        from .lifecycle import utc
        if (not active or receipt.run_id != release.run_id
                or receipt.custody_release_sha256 != commitment(release)
                or receipt.edition_sha256 != opened.locked_edition_sha256
                or receipt.worker_profile_sha256 != release.worker_policy_sha256
                or not utc(receipt.consumed_at) < utc(receipt.expires_at) <= utc(release.expires_at)):
            raise ValueError('timing_release_binding_or_revocation_mismatch')
        if any(commitment(r) not in ends for r in starts):
            raise ValueError('timing_uncertain_phase_requires_investigation')
        if any(r.request_sha256 == receipt.request_sha256 or
               r.attempt_namespace == receipt.attempt_namespace for r in starts):
            raise ValueError('timing_request_or_namespace_already_consumed')
        if starts and any(getattr(starts[0], key) != getattr(receipt, key) for key in (
                'authorization_sha256', 'primary_accounting_sha256', 'timing_plan_sha256',
                'edition_sha256', 'run_id', 'worker_profile_sha256')):
            raise ValueError('timing_continuation_authority_changed')
        arm_starts = [r for r in starts if r.arm == receipt.arm]
        if receipt.ordinal != len(arm_starts) + 1:
            raise ValueError('timing_phase_must_be_next_of_three')
        if arm_starts and (ends[commitment(arm_starts[-1])].outcome != 'completed'
                or arm_starts[-1].backend_identity_sha256 != receipt.backend_identity_sha256
                or arm_starts[-1].launch_sha256 != receipt.launch_sha256):
            raise ValueError('timing_aborted_or_changed_backend_cannot_continue')
    else:
        matches = [r for r in starts if commitment(r) == receipt.consumed_sha256]
        if len(matches) != 1 or receipt.consumed_sha256 in ends:
            raise ValueError('timing_terminal_without_unique_unfinished_consumption')
        start = matches[0]
        if any(getattr(start, key) != getattr(receipt, key) for key in (
                'edition_id', 'run_id', 'request_sha256', 'arm', 'ordinal')):
            raise ValueError('timing_terminal_binding_mismatch')
        if receipt.outcome == 'completed':
            from .lifecycle import utc
            if not active or utc(receipt.finished_at) >= utc(start.expires_at):
                raise ValueError('timing_completion_after_revocation_or_expiry_forbidden')
