"""Borrow-only lease adapter for application-owned D6 resources; no native calls."""
from __future__ import annotations

from contextlib import contextmanager
from threading import RLock
from typing import Callable

from .native_controls_models import BorrowedNativeContext, NativeContextBinding
from .provenance import commitment


class BorrowedContextRegistry:
    """Optional reference NativeControlContextProvider for the trusted launcher host.

    D6 remains sole resource owner. Register only actual context after native
    creation/qualification; registration authenticates metadata, NEVER enforcement.
    Host retires registration before its own cleanup closes resources. Lease lock
    prevents cleanup racing a query. No native handle is closed here.
    """
    def __init__(self, *, verify_receipt: Callable[[str, str], bool]):
        self.verify_receipt = verify_receipt
        self._lock = RLock()
        self._contexts: dict[str, BorrowedNativeContext] = {}
        self._retired: set[str] = set()
        self._leases: dict[str, int] = {}

    def _authenticate(self, context: BorrowedNativeContext) -> None:
        binding = NativeContextBinding.model_validate_json(context.binding.model_dump_json())
        if (self.verify_receipt('native_context_authority', binding.context_authority_sha256) is not True
                or self.verify_receipt('native_context_binding', commitment(binding)) is not True):
            raise ValueError('native_context_registration_not_authenticated')
        values = [context.job_handle]
        if binding.stage == 'process':
            values.append(context.process_handle)
            if {row.role for row in context.inherited_handles} != {'stdin', 'stdout', 'stderr'} or len(context.inherited_handles) != 3:
                raise ValueError('native_context_standard_handles_required')
            values.extend(value for row in context.inherited_handles for value in (row.child_handle, row.expected_local_handle))
        elif context.process_handle is not None or context.inherited_handles:
            raise ValueError('prepared_native_context_has_process')
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError('native_context_handle_missing')

    def register(self, context: BorrowedNativeContext) -> None:
        self._authenticate(context)
        with self._lock:
            key = context.binding.context_id
            if key in self._retired or key in self._contexts:
                raise ValueError('native_context_id_already_used')
            if any((c.binding.stage, c.binding.profile_sha256, c.binding.pid, c.binding.start_identity, c.binding.launch_sha256)
                   == (context.binding.stage, context.binding.profile_sha256, context.binding.pid,
                       context.binding.start_identity, context.binding.launch_sha256) for c in self._contexts.values()):
                raise ValueError('ambiguous_native_context_registration')
            self._contexts[key] = context

    @contextmanager
    def lease_prepared(self, profile_sha256: str):
        with self._lock:
            matches = [c for c in self._contexts.values()
                       if c.binding.stage == 'prepared' and c.binding.profile_sha256 == profile_sha256]
            if len(matches) != 1:
                raise ValueError('prepared_native_context_unavailable')
            self._authenticate(matches[0])
            key = matches[0].binding.context_id
            self._leases[key] = self._leases.get(key, 0) + 1
            try:
                yield matches[0]
            finally:
                self._leases[key] -= 1

    @contextmanager
    def lease_process(self, pid: int, start_identity: str, launch_sha256: str):
        with self._lock:
            matches = [c for c in self._contexts.values() if c.binding.stage == 'process'
                       and c.binding.pid == pid and c.binding.start_identity == start_identity
                       and c.binding.launch_sha256 == launch_sha256]
            if len(matches) != 1:
                raise ValueError('exact_native_context_unavailable')
            self._authenticate(matches[0])
            key = matches[0].binding.context_id
            self._leases[key] = self._leases.get(key, 0) + 1
            try:
                yield matches[0]
            finally:
                self._leases[key] -= 1

    def retire(self, context_id: str) -> BorrowedNativeContext:
        """Owner calls BEFORE cleanup; waits for leases then removes only metadata."""
        with self._lock:
            if context_id not in self._contexts:
                raise ValueError('unknown_native_context_registration')
            if self._leases.get(context_id, 0):
                raise ValueError('native_context_lease_still_active')
            context = self._contexts.pop(context_id)
            self._retired.add(context_id)
            return context  # Owner, never this adapter, closes its actual resources.
