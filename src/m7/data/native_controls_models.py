"""Exact native control policies, borrowed-context and external-observation contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, ContextManager, Literal, Protocol

from pydantic import Field, model_validator
from m7.contracts import Boundary, Digest, Identifier

MitigationName = Literal['strict_handles', 'child_process', 'extension_points', 'image_load']
FactName = Literal['prepared_token_policy', 'prepared_namespace_policy', 'environment_exact',
    'network_enforced', 'complete_child_handle_inventory', 'lifetime_enforced', 'runtime_code_closure',
    'race_protection', 'context_handle_ownership']


class MitigationRequirement(Boundary):
    name: MitigationName
    required_mask: Annotated[int, Field(gt=0, le=4294967295)]
    forbidden_mask: Annotated[int, Field(ge=0, le=4294967295)] = 0


class WindowsControlPolicy(Boundary):
    schema_version: Literal['WindowsControlPolicy/v1'] = 'WindowsControlPolicy/v1'
    policy_id: Identifier
    profile_sha256: Digest
    filesystem_policy_sha256: Digest
    active_process_limit: Literal[1] = 1
    kill_on_close: Literal[True] = True
    allow_breakaway: Literal[False] = False
    process_memory_limit: Annotated[int, Field(ge=1048576, le=2**46)] | None = None
    job_memory_limit: Annotated[int, Field(ge=1048576, le=2**46)] | None = None
    process_user_time_100ns: Annotated[int, Field(gt=0, le=2**63 - 1)] | None = None
    cpu_rate_hundredths: Annotated[int, Field(ge=1, le=10000)] | None = None
    ui_restrictions: Annotated[int, Field(ge=0, le=255)] | None = None
    max_wall_lifetime_seconds: Annotated[float, Field(gt=0, le=21600, allow_inf_nan=False)]
    max_external_age_seconds: Annotated[int, Field(ge=1, le=60)] = 5
    mitigations: Annotated[tuple[MitigationRequirement, ...], Field(min_length=1, max_length=4)]

    @model_validator(mode='after')
    def coherent(self):
        by_name = {row.name: row for row in self.mitigations}
        if len(by_name) != len(self.mitigations) or 'child_process' not in by_name:
            raise ValueError('native_mitigation_requirements_incomplete')
        supported = {'strict_handles': 3, 'child_process': 7, 'extension_points': 1, 'image_load': 31}
        for row in self.mitigations:
            if (row.required_mask | row.forbidden_mask) & ~supported[row.name] or row.required_mask & row.forbidden_mask:
                raise ValueError('unsupported_native_mitigation_mask')
        if ('strict_handles' in by_name and by_name['strict_handles'].required_mask != 3) or not by_name['child_process'].required_mask & 1:
            raise ValueError('native_handle_or_descendant_enforcement_missing')
        if self.process_memory_limit is not None and self.job_memory_limit is not None and self.process_memory_limit > self.job_memory_limit:
            raise ValueError('native_memory_limits_inconsistent')
        return self


class NativeContextBinding(Boundary):
    schema_version: Literal['NativeContextBinding/v1'] = 'NativeContextBinding/v1'
    context_id: Identifier
    profile_sha256: Digest
    control_policy_sha256: Digest
    filesystem_policy_sha256: Digest
    stage: Literal['prepared', 'process']
    pid: Annotated[int, Field(gt=0, le=4294967295)] | None = None
    start_identity: str | None = None
    launch_sha256: Digest | None = None
    bootstrap_sha256: Digest | None = None
    context_authority_sha256: Digest
    launcher_context_id: Identifier | None = None

    @model_validator(mode='after')
    def coherent(self):
        values = (self.pid, self.start_identity, self.launch_sha256, self.bootstrap_sha256)
        if self.stage == 'prepared' and any(v is not None for v in values):
            raise ValueError('prepared_context_must_not_require_process')
        if self.stage == 'process' and any(v is None for v in values):
            raise ValueError('process_context_binding_incomplete')
        return self


@dataclass(frozen=True)
class NativeHandleBinding:
    role: Literal['stdin', 'stdout', 'stderr']
    child_handle: int
    expected_local_handle: int


@dataclass(frozen=True)
class BorrowedNativeContext:
    """Host lease owns/stabilizes EVERY handle. No numeric handle in JSON receipts.

    expected_local_handle is a retained noninheritable reference to the EXACT
    child-side object, not the opposite pipe endpoint. D4 duplicates child handles
    only for comparison, never reads a pipe, closes a source or changes properties.
    """
    binding: NativeContextBinding
    job_handle: int
    process_handle: int | None = None
    inherited_handles: tuple[NativeHandleBinding, ...] = ()


class NativeControlContextProvider(Protocol):
    def lease_prepared(self, profile_sha256: str) -> ContextManager[BorrowedNativeContext]: ...
    def lease_process(self, pid: int, start_identity: str, launch_sha256: str) -> ContextManager[BorrowedNativeContext]: ...


class ExternalControlFact(Boundary):
    name: FactName
    status: Literal['observed', 'unknown', 'unsupported']
    evidence_sha256: Digest | None = None

    @model_validator(mode='after')
    def observed_evidence_required(self):
        if (self.status == 'observed') != (self.evidence_sha256 is not None):
            raise ValueError('external_native_fact_evidence_inconsistent')
        return self


class ExternalControlObservation(Boundary):
    schema_version: Literal['ExternalControlObservation/v1'] = 'ExternalControlObservation/v1'
    observation_id: Identifier
    context_binding_sha256: Digest
    control_policy_sha256: Digest
    observed_at: str
    expires_at: str
    facts: tuple[ExternalControlFact, ...]


class NativeExternalObservationProvider(Protocol):
    """Actual current authorized native facts; declarations/booleans are invalid.

    Do not read raw environment credentials or unrelated processes. If complete
    handle inventory, safe environment fingerprint or network/lifetime/runtime/
    race evidence is unavailable, return unknown/unsupported, never observed.
    """
    def observe_prepared(self, context: BorrowedNativeContext, policy: WindowsControlPolicy, evidence) -> ExternalControlObservation: ...
    def observe_process(self, context: BorrowedNativeContext, policy: WindowsControlPolicy, approval, spec, observation) -> ExternalControlObservation: ...


class ControlQualificationReport(Boundary):
    schema_version: Literal['ControlQualificationReport/v1'] = 'ControlQualificationReport/v1'
    status: Literal['validation_only', 'qualified_snapshot', 'unqualified']
    stage: Literal['prepared', 'process']
    profile_sha256: Digest | None = None
    launch_sha256: Digest | None = None
    context_binding_sha256: Digest | None = None
    native_snapshot_sha256: Digest | None = None
    external_observation_sha256: Digest | None = None
    supported_facts: tuple[Identifier, ...] = ()
    unknown_facts: tuple[Identifier, ...] = ()
    native_queries_attempted: bool | None = False
    authority_issued: Literal[False] = False
