"""Pure timing continuation seam. No custody, worker, clock or filesystem access.

Plan hashes deliberately exclude edition digest/profile/launch: those depend on
the preregistered plan. Actual identities belong in the later signed request.
"""
from __future__ import annotations

from typing import Annotated, Callable, Literal, Protocol
from pydantic import Field, model_validator
from m7.contracts import Arm, Boundary, Digest, Identifier, LogRecord, Prediction
from .models import ARMS, ArmPin, PopulationMember, commitment


class TimingLengthSlice(Boundary):
    minimum: Annotated[int, Field(ge=0, le=1024)]
    maximum: Annotated[int, Field(ge=0, le=1024)]


class HardwareContext(Boundary):
    cpu: Identifier
    gpu: Identifier | None
    ram_gib: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    driver: Identifier
    precision: Literal['fp32', 'fp16', 'bf16', 'int8', 'mixed']
    batch_size: Literal[1] = 1
    package_lock_sha256: Digest
    environment_sha256: Digest


class IsolatedTimingPlan(Boundary):
    schema_version: Literal['IsolatedTimingPlan/v1'] = 'IsolatedTimingPlan/v1'
    edition_id: Identifier
    run_id: Identifier
    population_sha256: Digest
    record_order: tuple[PopulationMember, ...]
    arm_pins: tuple[ArmPin, ...]
    environment_sha256: Digest
    package_lock_sha256: Digest
    hardware_receipt_sha256: Digest
    hardware: HardwareContext
    length_slices: tuple[TimingLengthSlice, ...]
    passes: Literal[3] = 3
    concurrency: Literal[1] = 1
    backend_policy: Literal['retain_primary_process_and_backend'] = 'retain_primary_process_and_backend'

    @model_validator(mode='after')
    def fixed(self):
        if (self.hardware.environment_sha256 != self.environment_sha256 or
                self.hardware.package_lock_sha256 != self.package_lock_sha256):
            raise ValueError('timing_hardware_environment_pins_mismatch')
        if tuple(p.arm for p in self.arm_pins) != ARMS:
            raise ValueError('timing_all_four_ordered_pins_required')
        ids = [r.record_id for r in self.record_order]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError('timing_population_required_unique')
        population = sorted(self.record_order, key=lambda r: r.record_id)
        if commitment([r.model_dump(mode='json') for r in population]) != self.population_sha256:
            raise ValueError('timing_population_digest_mismatch')
        cursor = 0
        for item in self.length_slices:
            if item.minimum != cursor or item.maximum < item.minimum:
                raise ValueError('timing_length_partition_invalid')
            cursor = item.maximum + 1
        if cursor != 1025:
            raise ValueError('timing_complete_length_partition_required')
        return self

    @property
    def sha256(self) -> str:
        return commitment(self.model_dump(mode='json'))

    @property
    def order_sha256(self) -> str:
        return commitment([r.model_dump(mode='json') for r in self.record_order])


class PrimaryAccountingReceipt(Boundary):
    schema_version: Literal['PrimaryAccountingReceipt/v1'] = 'PrimaryAccountingReceipt/v1'
    edition_sha256: Digest
    journal_head_sha256: Digest
    population_sha256: Digest
    terminal_cells_sha256: Digest
    quality_sha256: Digest
    intended_cells: Annotated[int, Field(gt=0)]
    terminal_cells: Annotated[int, Field(gt=0)]
    uncertain_terminal_cells: Annotated[int, Field(ge=0)]
    unresolved_begins: Literal[0] = 0

    @model_validator(mode='after')
    def complete(self):
        if self.intended_cells != self.terminal_cells or self.uncertain_terminal_cells > self.terminal_cells:
            raise ValueError('closed_primary_accounting_required')
        return self

    @property
    def sha256(self) -> str:
        return commitment(self.model_dump(mode='json'))


class WarmBackendIdentity(Boundary):
    schema_version: Literal['WarmBackendIdentity/v1'] = 'WarmBackendIdentity/v1'
    arm: Arm
    session_id: Identifier
    process_id: Annotated[int, Field(gt=0)]
    process_start_identity: Identifier
    backend_instance_id: Identifier
    profile_sha256: Digest
    launch_sha256: Digest
    bootstrap_sha256: Digest
    pin: ArmPin
    primary_population_sha256: Digest
    primary_order_sha256: Digest
    # Authenticated parent/process attestation, never self-report alone.
    attestation_sha256: Digest


class TimingPhaseRequest(Boundary):
    schema_version: Literal['TimingPhaseRequest/v1'] = 'TimingPhaseRequest/v1'
    edition_sha256: Digest
    primary_accounting_sha256: Digest
    plan_sha256: Digest
    population_sha256: Digest
    order_sha256: Digest
    identity: WarmBackendIdentity
    ordinal: Annotated[int, Field(ge=1, le=3)]
    # Deterministic parent namespace; no ledger/custody path crosses the wire.
    attempt_namespace: Digest


class TimingPhasePermit(Boundary):
    schema_version: Literal['TimingPhasePermit/v1'] = 'TimingPhasePermit/v1'
    request_sha256: Digest
    custody_receipt_sha256: Digest
    resource_receipt_sha256: Digest


class WarmTimingSession(Protocol):
    """D6 implements; methods must reattest exact native process before messages.

    identity is available only for the original primary-loaded backend. begin
    resets logical caches/controllers once, never backend/process; predict uses
    bounded original records in the supplied order. finish reports authenticated
    completion; failure cannot be resumed or respawned by this protocol.
    """
    def timing_identity(self) -> WarmBackendIdentity: ...
    def begin_timing_phase(self, request: TimingPhaseRequest, permit: TimingPhasePermit, *,
                           verify_receipt: Callable[[str, str], bool]) -> None: ...
    def predict(self, record: LogRecord) -> Prediction: ...
    def finish_timing_phase(self, request: TimingPhaseRequest) -> None: ...


class TimingContinuationAuthority(Protocol):
    """D4 consumes a durable phase once; D5 authenticates worst-case resources.

    prepare is nonconsuming and cannot open/reopen heldout custody. authorize
    persists consumed phase before any reset/messages. current rechecks original
    release, revocation, native proof, expiry and cash before each record.
    finish persists completed/aborted; uncertainty requires investigation.
    """
    def prepare(self, primary: PrimaryAccountingReceipt, plan: IsolatedTimingPlan) -> None: ...
    def authorize(self, request: TimingPhaseRequest) -> TimingPhasePermit: ...
    def current(self, request: TimingPhaseRequest, permit: TimingPhasePermit) -> None: ...
    def finish(self, request: TimingPhaseRequest, *, completed: bool) -> None: ...
    def verify_receipt(self, kind: str, digest: str) -> bool: ...
