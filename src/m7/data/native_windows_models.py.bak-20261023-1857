"""Private native qualification inputs and value-free results. No native calls."""
from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import Field

from m7.contracts import Boundary, Digest, Identifier


class WindowsPolicyEvidence(Boundary):
    schema_version: Literal['WindowsPolicyEvidence/v1'] = 'WindowsPolicyEvidence/v1'
    evidence_id: Identifier
    capability_sha256: Digest
    request_sha256: Digest
    profile_sha256: Digest
    filesystem_policy_sha256: Digest
    descriptor_tree_sha256: Digest
    prepared_controls_sha256: Digest
    issued_at: str
    expires_at: str


class WindowsProcessApproval(Boundary):
    schema_version: Literal['WindowsProcessApproval/v1'] = 'WindowsProcessApproval/v1'
    approval_id: Identifier
    pid: Annotated[int, Field(gt=0, le=4294967295)]
    start_identity: Annotated[str, Field(pattern=r'^[0-9]{1,20}$')]
    profile_sha256: Digest
    launch_sha256: Digest
    bootstrap_sha256: Digest
    filesystem_policy_sha256: Digest
    capability_sha256: Digest
    image_sha256: Digest
    entrypoint_sha256: Digest
    descriptor_tree_sha256: Digest
    worker_sid: Annotated[str, Field(pattern=r'^S-1-[0-9-]+$')]
    custodian_sid: Annotated[str, Field(pattern=r'^S-1-[0-9-]+$')]
    token_id: Annotated[str, Field(pattern=r'^[0-9a-f]{16}$')]
    token_modified_id: Annotated[str, Field(pattern=r'^[0-9a-f]{16}$')]
    expected_handle_count: Annotated[int, Field(ge=1, le=100000)]
    process_controls_sha256: Digest
    issued_at: str
    expires_at: str


class NativeObservation(Boundary):
    schema_version: Literal['WindowsNativeObservation/v1'] = 'WindowsNativeObservation/v1'
    pid: int
    start_identity: str
    profile_sha256: Digest
    launch_sha256: Digest
    image_sha256: Digest
    descriptor_tree_sha256: Digest
    token_id: str
    token_modified_id: str
    checked_objects: int
    denied_objects: int
    read_only_objects: int
    handle_count: int
    in_job: Literal[True]


class NativeQualificationResult(Boundary):
    schema_version: Literal['NativeQualificationResult/v1'] = 'NativeQualificationResult/v1'
    status: Literal['validation_only', 'qualified_snapshot', 'unqualified']
    reason_codes: tuple[Identifier, ...]
    observation: NativeObservation | None = None
    native_inspection_performed: bool | None = False
    authority_issued: Literal[False] = False


class WindowsControlVerifier(Protocol):
    """Trusted actual enforcement evidence, not a true-valued receipt-shaped flag.

    Supported Win32 query APIs cannot enumerate inherited handle access, inspect
    another process environment, or prove network/descendant restrictions. The
    operating host MUST supply current native-backed verification for those exact
    facts, or qualification fails closed. This adapter never fabricates them.
    """
    def verify_policy(self, evidence: WindowsPolicyEvidence, capability, request, profile) -> bool: ...
    def verify_process(self, approval: WindowsProcessApproval, observation: NativeObservation, spec, policy) -> bool: ...
