"""Concrete future Windows launch adapter; default denied and never probes on import.

Preprovisioned native context and real host qualification are mandatory. This does
not provision accounts, obtain credentials, enable privileges or mutate other jobs.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, Queue
from threading import RLock, Thread
from time import monotonic
from typing import Annotated, Literal, Protocol

from pydantic import Field

from m7.contracts import Boundary, Digest, Identifier
from .contracts import AdapterFault, config_digest
from .native_launch_api import Win32LaunchApi
from .worker_profile import WorkerLaunchPolicy, WorkerProfile, validate_worker_membership
from .worker_transport import PythonLaunchSpec, WorkerProcessVerifier, launch_spec


class NativeLaunchApproval(Boundary):
    schema_version: Literal["NativeLaunchContext/v1"] = "NativeLaunchContext/v1"
    context_id: Identifier
    profile_sha256: Digest
    launch_sha256: Digest
    bootstrap_sha256: Digest
    capability_sha256: Digest
    filesystem_policy_sha256: Digest
    token_qualification_sha256: Digest
    caller_privileges_sha256: Digest
    resource_receipt_sha256: Digest
    issued_at: Annotated[str, Field(min_length=1, max_length=64)]
    expires_at: Annotated[str, Field(min_length=1, max_length=64)]


@dataclass(frozen=True)
class PreprovisionedWindowsContext:
    # Borrowed explicit OS handle, never serialized/logged/discovered/closed here.
    primary_token_handle: int = field(repr=False)
    approval: NativeLaunchApproval


@dataclass(frozen=True)
class BorrowedWindowsHandles:
    process_handle: int = field(repr=False)
    job_handle: int = field(repr=False)
    stdio_expected: tuple[int, int, int] = field(repr=False)
    child_handle_values: tuple[int, int, int] = field(repr=False)


@dataclass(frozen=True)
class PreparedWindowsProcess:
    pid: int
    start_identity: str
    profile_sha256: str
    launch_sha256: str
    bootstrap_sha256: str
    native_context_id: str
    lease_handles: Callable = field(repr=False)


class WindowsLaunchHost(Protocol):
    def verify_context(self, context: PreprovisionedWindowsContext, policy: WorkerLaunchPolicy,
                       spec: PythonLaunchSpec, verified_isolation) -> bool:
        """Inspect actual approved restricted nonadmin low-integrity primary token,
        rights/session/root restrictions and already-enabled caller privileges.
        No account lookup, token discovery, privilege enabling or false-valued fact
        upgraded to approval. Host must keep the borrowed context stable throughout.
        """
        ...

    def prepare_suspended(self, process: PreparedWindowsProcess, policy: WorkerLaunchPolicy,
                          spec: PythonLaunchSpec, verified_isolation) -> bool:
        """Publish/authenticate REAL exact-PID/start/image/token/job/handle controls
        for D4 WindowsWorkerProcessVerifier. Can borrow only managed query copies.
        Missing observer/evidence must return False, never synthesize a verdict.
        """
        ...


def validate_native_host_spec(approval: NativeLaunchApproval, policy: WorkerLaunchPolicy,
                              profile: WorkerProfile) -> dict:
    """Pure definition check. Does not authenticate or inspect any token/context."""
    approval = NativeLaunchApproval.model_validate_json(approval.model_dump_json())
    membership = validate_worker_membership(profile, policy)
    if (approval.profile_sha256 != membership.profile_sha256
            or approval.launch_sha256 != membership.launch_sha256
            or approval.bootstrap_sha256 != policy.bootstrap_sha256
            or approval.filesystem_policy_sha256 != policy.filesystem_policy_sha256):
        raise AdapterFault("permit_required")
    return {"status": "native_launch_definition_only", "native_operations_performed": False,
            "profile_sha256": membership.profile_sha256, "launch_sha256": membership.launch_sha256,
            "actual_token_verified": False, "authority_issued": False}

def _timed(operation, seconds: float):
    if seconds <= 0:
        raise AdapterFault("unavailable")
    result = Queue(maxsize=1)
    def perform():
        try:
            result.put((True, operation()))
        except BaseException:
            result.put((False, None))
    Thread(target=perform, daemon=True).start()
    try:
        ok, value = result.get(timeout=seconds)
    except Empty:
        raise AdapterFault("unavailable") from None
    if not ok:
        raise AdapterFault("unavailable")
    return value


class WindowsOwnedWorker:
    """Owns only resources allocated by one successful suspended native creation."""

    def __init__(self, api, handles: dict[str, int], pid: int, start_identity: str):
        self.api, self.handles, self.pid, self.start_identity = api, handles, pid, start_identity
        self._lock = RLock()
        self._active_leases = 0
        self._closed = False
        self._buffer = b""
        self._monitor = None
        self._monitor_failed = False
        self._lease_cleanup_failed = False
        self._cleanup_failed = False

    def arm_lifetime(self, seconds: float):
        self.api.arm_timer(self.handles["timer"], seconds)

    def start_monitor(self):
        def watch():
            try:
                if self.api.wait_lifetime(self.handles["process"], self.handles["timer"]) == 1:
                    self.terminate()
            except BaseException:
                self._monitor_failed = True
                try:
                    self.terminate()
                except BaseException:
                    pass
        self._monitor = Thread(target=watch, daemon=True)
        self._monitor.start()  # One native wait, not a polling/service loop.

    @contextmanager
    def lease_handles(self):
        copies = []
        with self._lock:
            if self._closed:
                raise AdapterFault("unavailable")
            try:
                process = self.api.copy_handle(self.handles["process"], access=0x1000 | 0x0040)
                copies.append(process)
                job = self.api.copy_handle(self.handles["job"], access=0x0004)  # QUERY only.
                copies.append(job)
                stdio = tuple(self.handles[key] for key in ("child_stdin", "child_stdout", "null"))
                expected = []
                for handle in stdio:
                    duplicate = self.api.copy_handle(handle)
                    copies.append(duplicate)
                    expected.append(duplicate)
                self._active_leases += 1
            except BaseException:
                for handle in reversed(copies):
                    self.api.close(handle)
                raise
        try:
            yield BorrowedWindowsHandles(process, job, tuple(expected), stdio)
        finally:
            failed = False
            try:
                for handle in reversed(copies):
                    try:
                        self.api.close(handle)  # Only our own query duplicates.
                    except BaseException:
                        failed = True
            finally:
                with self._lock:
                    self._active_leases -= 1
                    self._lease_cleanup_failed = self._lease_cleanup_failed or failed
            if failed:
                raise AdapterFault("unavailable")

    def drop(self, key: str):
        with self._lock:
            handle = self.handles.pop(key, None)
            if handle is not None:
                self.api.close(handle)

    def terminate(self):
        with self._lock:
            if not self._closed:
                self.api.terminate(self.handles["job"])

    def wait(self, timeout: float):
        if self._closed:
            if self._cleanup_failed or self._lease_cleanup_failed or self._active_leases:
                raise AdapterFault("unavailable")
            return
        self.api.wait_process(self.handles["process"], timeout)
        if self._monitor is not None:
            self._monitor.join(timeout=max(0.0, timeout))
            if self._monitor.is_alive():
                raise AdapterFault("unavailable")
        failed = self._monitor_failed or self._lease_cleanup_failed
        with self._lock:
            failed = failed or self._active_leases != 0
            for key in tuple(reversed(self.handles)):
                try:
                    self.drop(key)
                except BaseException:
                    failed = True
            self._closed = True
            self._cleanup_failed = failed
        if failed:
            raise AdapterFault("unavailable")  # Cleanup cannot be claimed confirmed.

    def send(self, raw: bytes, timeout: float):
        def write():
            cursor = 0
            while cursor < len(raw):
                cursor += self.api.write(self.handles["parent_stdin"], raw[cursor:])
        _timed(write, timeout)

    def receive(self, limit: int, timeout: float) -> bytes:
        def read():
            while True:
                end = self._buffer.find(b"\n")
                if end >= 0:
                    if end + 1 > limit:
                        raise AdapterFault("invalid_output")
                    line, self._buffer = self._buffer[:end + 1], self._buffer[end + 1:]
                    return line
                if len(self._buffer) >= limit:
                    raise AdapterFault("invalid_output")
                chunk = self.api.read(self.handles["parent_stdout"], min(4096, limit - len(self._buffer)))
                if not chunk:
                    raise AdapterFault("unavailable")
                self._buffer += chunk
        return _timed(read, timeout)


class WindowsIsolatedLauncher:
    def __init__(self, context: PreprovisionedWindowsContext, policy: WorkerLaunchPolicy,
                 profile: WorkerProfile, *, isolation_guard, host: WindowsLaunchHost,
                 process_verifier: WorkerProcessVerifier, allow_execution: bool = False):
        self.context, self.policy, self.profile = context, policy, profile
        self.guard, self.host, self.process_verifier = isolation_guard, host, process_verifier
        self.allow_execution = allow_execution
        self.last_cleanup_status = "not_requested"

    def validate(self) -> dict:
        if type(self.context.primary_token_handle) is not int or self.context.primary_token_handle <= 0:
            raise AdapterFault("permit_required")
        return validate_native_host_spec(self.context.approval, self.policy, self.profile)

    def launch(self, spec: PythonLaunchSpec, verified_isolation, *, timeout: float) -> WindowsOwnedWorker:
        if self.allow_execution is not True or self.host is None or self.process_verifier is None:
            raise AdapterFault("permit_required")
        self.validate()
        if spec != launch_spec(self.policy) or not 0 < timeout <= self.policy.startup_timeout_seconds:
            raise AdapterFault("permit_required")
        deadline, started = monotonic() + timeout, monotonic()
        handles, api, worker = {}, None, None
        try:
            approval = self.context.approval
            now = datetime.now(timezone.utc)
            issued = datetime.fromisoformat(approval.issued_at.replace("Z", "+00:00"))
            expires = datetime.fromisoformat(approval.expires_at.replace("Z", "+00:00"))
            if issued.tzinfo is None or expires.tzinfo is None or not issued <= now < expires:
                raise AdapterFault("permit_required")
            current = self.guard.require_current(self.policy.edition_id, self.policy.corpus_manifest_sha256,
                filesystem_policy_sha256=self.policy.filesystem_policy_sha256,
                worker_policy_sha256=self.policy.profile_sha256)
            if current != verified_isolation or approval.capability_sha256 != current.capability_sha256:
                raise AdapterFault("permit_required")
            for kind, digest in (("native_launch_context", config_digest(approval)),
                                 ("native_launch_token", approval.token_qualification_sha256),
                                 ("native_launch_caller_privileges", approval.caller_privileges_sha256),
                                 ("native_launch_resources", approval.resource_receipt_sha256)):
                if self.guard.verify_receipt(kind, digest) is not True:
                    raise AdapterFault("permit_required")
            if _timed(lambda: self.host.verify_context(self.context, self.policy, spec, current),
                      deadline - monotonic()) is not True:
                raise AdapterFault("permit_required")
            api = Win32LaunchApi()  # First native binding only after explicit authority.
            handles["job"] = api.new_job()
            handles["token"] = api.primary_token(self.context.primary_token_handle)
            handles["parent_stdin"], handles["child_stdin"] = api.pipe(parent_reads=False)
            handles["parent_stdout"], handles["child_stdout"] = api.pipe(parent_reads=True)
            handles["null"] = api.null_output()
            process = api.suspended(handles["token"], spec, handles["job"], handles["child_stdin"],
                                    handles["child_stdout"], handles["null"])
            handles["process"], handles["thread"] = process.process, process.thread
            identity = api.start_identity(handles["process"])
            handles["timer"] = api.new_timer(min(deadline - monotonic(), spec.lifetime_seconds))
            worker = WindowsOwnedWorker(api, handles, process.pid, identity)
            worker.start_monitor()  # Startup qualification cannot leave an unbounded child.
            prepared = PreparedWindowsProcess(worker.pid, worker.start_identity, self.policy.profile_sha256,
                config_digest(self.policy), self.policy.bootstrap_sha256, approval.context_id, worker.lease_handles)
            if _timed(lambda: self.host.prepare_suspended(prepared, self.policy, spec, current),
                      deadline - monotonic()) is not True:
                raise AdapterFault("permit_required")
            if _timed(lambda: self.process_verifier.verify(worker.pid, worker.start_identity, spec,
                      current, self.policy), deadline - monotonic()) is not True:
                raise AdapterFault("permit_required")
            if monotonic() >= deadline:
                raise AdapterFault("unavailable")
            live = self.guard.require_current(self.policy.edition_id, self.policy.corpus_manifest_sha256,
                filesystem_policy_sha256=self.policy.filesystem_policy_sha256,
                worker_policy_sha256=self.policy.profile_sha256)
            if (live != current or datetime.now(timezone.utc) >= expires
                    or self.guard.verify_receipt("native_launch_context", config_digest(approval)) is not True):
                raise AdapterFault("permit_required")
            worker.arm_lifetime(min(spec.lifetime_seconds - (monotonic() - started),
                                   (expires - datetime.now(timezone.utc)).total_seconds()))
            api.resume(handles["thread"])
            worker.drop("thread")
            worker.drop("token")  # Duplicate only; original borrowed token untouched.
            self.last_cleanup_status = "active"
            return worker
        except BaseException:
            cleanup_failed = False
            if worker is not None:
                try:
                    worker.terminate()
                    worker.wait(self.policy.close_timeout_seconds)
                except BaseException:
                    cleanup_failed = True
            elif api is not None:
                if "job" in handles:
                    try:
                        api.terminate(handles["job"])
                    except BaseException:
                        cleanup_failed = True
                if "process" in handles:
                    try:
                        api.wait_process(handles["process"], self.policy.close_timeout_seconds)
                    except BaseException:
                        cleanup_failed = True
                for handle in tuple(reversed(handles.values())):
                    try:
                        api.close(handle)
                    except BaseException:
                        cleanup_failed = True
            self.last_cleanup_status = ("not_started" if api is None else
                                        "cleanup_unverified" if cleanup_failed else "failed_closed")
            raise AdapterFault("unavailable") from None
