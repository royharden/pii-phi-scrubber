"""D4 borrowed-context provider backed by D6's owned native handle leases.

No native operation during construction/registration; D4 performs real read-only
qualification later. Authentication alone never implies enforcement or a verdict.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock

from m7.data.native_controls_models import BorrowedNativeContext, NativeContextBinding, NativeHandleBinding
from m7.data.provenance import commitment
from .contracts import AdapterFault
from .native_launcher import PreparedWindowsProcess
from .worker_profile import WorkerLaunchPolicy, WorkerProfile, validate_worker_membership, worker_profile_digest


@dataclass(frozen=True)
class _ProcessContext:
    prepared: PreparedWindowsProcess
    binding: NativeContextBinding


class OwnedWindowsContextProvider:
    def __init__(self, profile: WorkerProfile, control_policy_sha256: str,
                 filesystem_policy_sha256: str, *, prepared_lease, verify_receipt):
        self.profile, self.control_policy_sha256 = profile, control_policy_sha256
        self.filesystem_policy_sha256 = filesystem_policy_sha256
        # External preprovisioned EMPTY prepared job lease, never attached/mutated
        # by D6. Running worker jobs below are new, separately exact-qualified.
        self.prepared_lease, self.verify_receipt = prepared_lease, verify_receipt
        self._processes = {}
        self._lock = RLock()

    def _check(self, binding: NativeContextBinding, stage: str):
        if (binding.stage != stage or binding.profile_sha256 != worker_profile_digest(self.profile)
                or binding.control_policy_sha256 != self.control_policy_sha256
                or binding.filesystem_policy_sha256 != self.filesystem_policy_sha256):
            raise AdapterFault("permit_required")
        if (self.verify_receipt("native_context_binding", commitment(binding)) is not True
                or self.verify_receipt("native_context_authority", binding.context_authority_sha256) is not True):
            raise AdapterFault("permit_required")

    def register_process(self, prepared: PreparedWindowsProcess, binding: NativeContextBinding,
                         policy: WorkerLaunchPolicy):
        binding = NativeContextBinding.model_validate_json(binding.model_dump_json())
        member = validate_worker_membership(self.profile, policy)
        self._check(binding, "process")
        if (prepared.pid != binding.pid or prepared.start_identity != binding.start_identity
                or prepared.profile_sha256 != binding.profile_sha256
                or prepared.launch_sha256 != binding.launch_sha256 or binding.launch_sha256 != member.launch_sha256
                or prepared.bootstrap_sha256 != binding.bootstrap_sha256
                or binding.bootstrap_sha256 != policy.bootstrap_sha256):
            raise AdapterFault("permit_required")
        if prepared.profile_sha256 != member.profile_sha256:
            raise AdapterFault("permit_required")
        key = (prepared.pid, prepared.start_identity, member.launch_sha256)
        with self._lock:
            if key in self._processes:
                raise AdapterFault("permit_required")
            self._processes[key] = _ProcessContext(prepared, binding)

    def revoke_process(self, pid: int, start_identity: str, launch_sha256: str):
        with self._lock:
            self._processes.pop((pid, start_identity, launch_sha256), None)
        # No process operation and no borrowed handles closed by revocation.

    @contextmanager
    def lease_prepared(self, profile_sha256: str):
        if profile_sha256 != worker_profile_digest(self.profile) or self.prepared_lease is None:
            raise AdapterFault("permit_required")
        with self.prepared_lease(profile_sha256) as context:
            self._check(context.binding, "prepared")
            if context.process_handle is not None or context.inherited_handles:
                raise AdapterFault("permit_required")
            yield context  # Borrowed originals remain owned by external host lease.

    @contextmanager
    def lease_process(self, pid: int, start_identity: str, launch_sha256: str):
        key = (pid, start_identity, launch_sha256)
        with self._lock:
            entry = self._processes.get(key)
        if entry is None:
            raise AdapterFault("permit_required")
        self._check(entry.binding, "process")
        with entry.prepared.lease_handles() as handles:
            roles = ("stdin", "stdout", "stderr")
            inherited = tuple(NativeHandleBinding(role, child, expected) for role, child, expected in
                              zip(roles, handles.child_handle_values, handles.stdio_expected, strict=True))
            yield BorrowedNativeContext(binding=entry.binding, job_handle=handles.job_handle,
                process_handle=handles.process_handle, inherited_handles=inherited)
        # D6 lease closes its own duplicate handles; D4 closes none of the sources.
