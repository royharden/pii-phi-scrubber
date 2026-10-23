"""D6 public PreparedWindowsProcess lease bridge, no guessed private handles."""
from __future__ import annotations

from contextlib import contextmanager
from threading import RLock
from typing import Callable

from .native_controls_models import BorrowedNativeContext, NativeContextBinding, NativeHandleBinding
from .provenance import commitment


class D6WindowsContextProvider:
    """Join D6 WindowsLaunchHost.prepare_suspended to the read-only qualifier.

    Register actual public PreparedWindowsProcess metadata after creation and
    original authentication. Keep its callback, never retain numeric lease copies.
    Each process lease enters D6's own lease_handles and leaves it after the query;
    D6 alone closes its query copies. Prepared context comes from an explicit real
    host provider and has no running-worker prerequisite.
    """
    def __init__(self, prepared_lease: Callable, *, verify_receipt: Callable[[str, str], bool]):
        self.prepared_lease, self.verify_receipt = prepared_lease, verify_receipt
        self._lock = RLock()
        self._processes = {}
        self._retired = set()
        self._active = {}

    def _auth(self, binding: NativeContextBinding) -> None:
        if (self.verify_receipt('native_context_authority', binding.context_authority_sha256) is not True
                or self.verify_receipt('native_context_binding', commitment(binding)) is not True):
            raise ValueError('d6_native_context_not_authenticated')

    def register_suspended(self, prepared, binding: NativeContextBinding) -> None:
        from m7.providers.native_launcher import PreparedWindowsProcess
        binding = NativeContextBinding.model_validate_json(binding.model_dump_json())
        if (type(prepared) is not PreparedWindowsProcess or binding.stage != 'process'
                or (binding.pid, binding.start_identity, binding.profile_sha256, binding.launch_sha256, binding.bootstrap_sha256)
                    != (prepared.pid, prepared.start_identity, prepared.profile_sha256, prepared.launch_sha256, prepared.bootstrap_sha256)
                or binding.launcher_context_id != prepared.native_context_id):
            raise ValueError('d6_prepared_process_binding_mismatch')
        self._auth(binding)
        key = (prepared.pid, prepared.start_identity, prepared.launch_sha256)
        with self._lock:
            if key in self._processes or key in self._retired:
                raise ValueError('d6_process_registration_already_used')
            self._processes[key] = (prepared, binding)

    @contextmanager
    def lease_prepared(self, profile_sha256: str):
        with self.prepared_lease(profile_sha256) as context:
            if (context.binding.stage != 'prepared' or context.binding.profile_sha256 != profile_sha256
                    or context.process_handle is not None or context.inherited_handles):
                raise ValueError('d6_prepared_context_mismatch')
            self._auth(context.binding)
            yield context

    @contextmanager
    def lease_process(self, pid: int, start_identity: str, launch_sha256: str):
        key = (pid, start_identity, launch_sha256)
        with self._lock:
            if key not in self._processes:
                raise ValueError('d6_exact_process_context_unavailable')
            prepared, binding = self._processes[key]
            self._auth(binding)
            self._active[key] = self._active.get(key, 0) + 1
            try:
                with prepared.lease_handles() as handles:
                    if len(handles.stdio_expected) != 3 or len(handles.child_handle_values) != 3:
                        raise ValueError('d6_standard_handle_lease_incomplete')
                    bindings = tuple(NativeHandleBinding(role, child, expected) for role, child, expected in
                        zip(('stdin', 'stdout', 'stderr'), handles.child_handle_values, handles.stdio_expected, strict=True))
                    yield BorrowedNativeContext(binding, handles.job_handle, handles.process_handle, bindings)
            finally:
                self._active[key] -= 1

    def retire_process(self, pid: int, start_identity: str, launch_sha256: str) -> None:
        key = (pid, start_identity, launch_sha256)
        with self._lock:
            if key not in self._processes or self._active.get(key, 0):
                raise ValueError('d6_context_unknown_or_lease_active')
            self._processes.pop(key)
            self._retired.add(key)
