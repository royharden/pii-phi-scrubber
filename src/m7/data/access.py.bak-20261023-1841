"""Authenticated native-enforcement capability contract. No fake OS sandbox here."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sys
from typing import Callable, Literal, Protocol

from m7.contracts import Boundary, Digest, Identifier

from .provenance import commitment


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('isolation_timezone_required')
    return parsed.astimezone(timezone.utc)


class IsolationRequest(Boundary):
    schema_version: Literal['IsolationRequest/v1'] = 'IsolationRequest/v1'
    edition_id: Identifier
    corpus_manifest_sha256: Digest
    filesystem_policy_sha256: Digest
    worker_policy_sha256: Digest


class IsolationCapability(Boundary):
    schema_version: Literal['IsolationCapability/v1'] = 'IsolationCapability/v1'
    capability_id: Identifier
    edition_id: Identifier
    corpus_manifest_sha256: Digest
    filesystem_policy_sha256: Digest
    worker_policy_sha256: Digest
    enforcement_evidence_sha256: Digest
    issuer_id: Identifier
    platform: Literal['windows', 'linux', 'macos']
    mechanism_id: Identifier
    issued_at: str
    expires_at: str
    action: Literal['isolated_held_out_inference'] = 'isolated_held_out_inference'


class IsolationVerifier(Protocol):
    def verify(self, capability: IsolationCapability, request: IsolationRequest) -> bool:
        """Verify actual current native deny/access/process enforcement for request.

        Must check the trusted host's evidence/profile, principals and allowed
        artifacts. Returning true for directory names or subprocess existence is
        invalid. This package supplies NO implementation that claims enforcement.
        """
        ...


@dataclass(frozen=True)
class VerifiedIsolation:
    capability_sha256: str
    request_sha256: str
    filesystem_policy_sha256: str
    worker_policy_sha256: str


def require_isolation(capability: IsolationCapability, request: IsolationRequest, *,
                      verify_receipt: Callable[[str, str], bool],
                      platform_verifier: IsolationVerifier,
                      now: datetime | None = None) -> VerifiedIsolation:
    # Reparse: model_copy and mutable caller state cannot bypass the boundary.
    capability = IsolationCapability.model_validate_json(capability.model_dump_json())
    request = IsolationRequest.model_validate_json(request.model_dump_json())
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or not _time(capability.issued_at) <= instant < _time(capability.expires_at):
        raise ValueError('isolation_capability_expired')
    if any(getattr(capability, name) != getattr(request, name)
           for name in ('edition_id', 'corpus_manifest_sha256', 'filesystem_policy_sha256', 'worker_policy_sha256')):
        raise ValueError('isolation_capability_binding_mismatch')
    platform = {'win32': 'windows', 'linux': 'linux', 'darwin': 'macos'}.get(sys.platform)
    if capability.platform != platform:
        raise ValueError('isolation_platform_mismatch')
    try:
        authentic = (verify_receipt('isolation_capability', commitment(capability)) is True
            and verify_receipt('platform_isolation_enforcement', capability.enforcement_evidence_sha256) is True)
        enforced = authentic and platform_verifier is not None and platform_verifier.verify(capability, request) is True
    except Exception:
        raise ValueError('isolation_verification_unavailable') from None
    if not enforced:
        raise ValueError('authenticated_actual_platform_enforcement_required')
    return VerifiedIsolation(commitment(capability), commitment(request),
                             request.filesystem_policy_sha256, request.worker_policy_sha256)


class IsolationGuard:
    """Re-authenticates capability AND actual platform state on every activation."""
    def __init__(self, capability: IsolationCapability, request: IsolationRequest, *,
                 verify_receipt: Callable[[str, str], bool], platform_verifier: IsolationVerifier):
        self.capability, self.request = capability, request
        self.verify_receipt, self.platform_verifier = verify_receipt, platform_verifier

    @property
    def sha256(self) -> str:
        return commitment(self.capability)

    def require_current(self, edition_id: str, corpus_manifest_sha256: str, *,
                        filesystem_policy_sha256: str | None = None,
                        worker_policy_sha256: str | None = None) -> VerifiedIsolation:
        if (edition_id != self.request.edition_id or corpus_manifest_sha256 != self.request.corpus_manifest_sha256
                or filesystem_policy_sha256 is not None and filesystem_policy_sha256 != self.request.filesystem_policy_sha256
                or worker_policy_sha256 is not None and worker_policy_sha256 != self.request.worker_policy_sha256):
            raise ValueError('isolation_activation_binding_mismatch')
        return require_isolation(self.capability, self.request, verify_receipt=self.verify_receipt,
                                 platform_verifier=self.platform_verifier)
