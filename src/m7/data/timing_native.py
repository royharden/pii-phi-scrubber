"""Exact native timing guard adapter. Construction never queries Windows."""
from __future__ import annotations

from typing import Mapping

from m7.experiment.timing_contracts import WarmBackendIdentity
from m7.providers.worker_profile import WorkerLaunchPolicy, validate_worker_membership

from .lifecycle import CustodyLifecycle
from .native_windows import WindowsWorkerProcessVerifier


class WindowsTimingProcessGuard:
    """Callback for CustodyTimingAuthority.verify_process, not an approval issuer.

    Each explicit call rechecks actual capability and the exact running worker
    using D4's native/control verifier. The parent must retain the original D6
    launch context and current signed exact-process approval for these queries.
    Unsupported facts return false; a cached prepared-policy proof never passes
    as a running-process observation. No accounts/rights/jobs/processes are made.
    """
    def __init__(self, lifecycle: CustodyLifecycle, verifier: WindowsWorkerProcessVerifier,
                 policies: Mapping[str, WorkerLaunchPolicy]):
        if not isinstance(verifier, WindowsWorkerProcessVerifier):
            raise ValueError('timing_concrete_native_process_verifier_required')
        self.lifecycle, self.verifier = lifecycle, verifier
        self.policies = {arm: WorkerLaunchPolicy.model_validate_json(p.model_dump_json())
                         for arm, p in policies.items()}
        if any(arm != p.arm for arm, p in self.policies.items()):
            raise ValueError('timing_native_policy_arm_mismatch')

    def __call__(self, identity: WarmBackendIdentity) -> bool:
        from m7.providers.worker_transport import launch_spec
        identity = WarmBackendIdentity.model_validate_json(identity.model_dump_json())
        policy = self.policies.get(identity.arm)
        if policy is None or self.lifecycle.isolation_guard is None:
            return False
        try:
            member = validate_worker_membership(self.verifier.profile, policy)
            if (identity.profile_sha256 != member.profile_sha256
                    or identity.launch_sha256 != member.launch_sha256
                    or identity.bootstrap_sha256 != member.bootstrap_sha256
                    or self.lifecycle.filesystem is not self.verifier.filesystem):
                return False
            verified = self.lifecycle.isolation_guard.require_current(policy.edition_id,
                policy.corpus_manifest_sha256, filesystem_policy_sha256=policy.filesystem_policy_sha256,
                worker_policy_sha256=member.profile_sha256)
            return self.verifier.verify(identity.process_id, identity.process_start_identity,
                launch_spec(policy), verified, policy) is True
        except Exception:
            return False
