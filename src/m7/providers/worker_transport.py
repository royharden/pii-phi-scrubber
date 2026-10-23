"""Explicit native-launch contract and bounded pipes. No default OS sandbox."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from queue import Queue, Empty
import subprocess
from threading import Thread
from typing import Literal, Protocol

from .contracts import AdapterFault
from .worker_profile import WorkerLaunchPolicy


@dataclass(frozen=True)
class PythonLaunchSpec:
    argv: tuple[str, ...]
    cwd: str
    environment: dict[str, str]
    lifetime_seconds: float
    shell: Literal[False] = False
    close_fds: Literal[True] = True
    stderr: Literal["discard"] = "discard"
    stdin: Literal["pipe"] = "pipe"
    stdout: Literal["pipe"] = "pipe"


def launch_spec(policy: WorkerLaunchPolicy) -> PythonLaunchSpec:
    if any(not Path(value).is_absolute() for value in
           (policy.executable, policy.entrypoint, policy.working_directory)):
        raise AdapterFault("permit_required")
    environment = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                   "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
                   "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                   "TMP": policy.working_directory, "TEMP": policy.working_directory}
    if policy.windows_directory is not None:
        if not Path(policy.windows_directory).is_absolute():
            raise AdapterFault("permit_required")
        environment["SystemRoot"] = policy.windows_directory
        environment["WINDIR"] = policy.windows_directory
    # No inherited env, HOME/USERPROFILE, tokens, PATH, PYTHONPATH or caller args.
    return PythonLaunchSpec((policy.executable, "-I", "-B", policy.entrypoint, "--worker"),
                            policy.working_directory, environment, policy.lifetime_seconds)


class OwnedWorker(Protocol):
    pid: int
    start_identity: str

    def send(self, raw: bytes, timeout: float) -> None: ...
    def receive(self, limit: int, timeout: float) -> bytes: ...
    def terminate(self) -> None:
        """Stop ONLY this launch's owned native process/job tree, including descendants."""
        ...
    def wait(self, timeout: float) -> None: ...


class IsolatedLauncher(Protocol):
    def launch(self, spec: PythonLaunchSpec, verified_isolation, *, timeout: float) -> OwnedWorker:
        """Native adapter must enforce spec and provisioned restricted principal/job.

        No implementation is supplied that equates Popen with isolation. Must not
        inherit gold/custody/credential handles, spawn via shell, or reuse a process.
        Must enforce startup/lifetime bounds and clean its owned job on failed start.
        """
        ...


class WorkerProcessVerifier(Protocol):
    def verify(self, pid: int, start_identity: str, spec: PythonLaunchSpec, verified_isolation,
               policy: WorkerLaunchPolicy) -> bool:
        """Attest this exact PID/principal/job, code pins, environment, handles,
        filesystem/network policy and descendant/lifetime restrictions. No default.
        """
        ...


class PipedWorker:
    """Pipe adapter for a native launcher's OWNED, already-restricted Popen handle.

    Constructed only by an operator's authenticated native launcher. It does not
    create a process or grant rights. The supplied terminate_job must target only
    that launch's verified owned job/process tree; it is not a PID lookup helper.
    """

    def __init__(self, process: subprocess.Popen, *, start_identity: str,
                 terminate_job: Callable[[], None]):
        if process.stdin is None or process.stdout is None or type(process.pid) is not int:
            raise AdapterFault("unavailable")
        self.process, self.pid = process, process.pid
        self.start_identity = start_identity
        self._terminate_job = terminate_job

    def _bounded(self, operation, timeout: float):
        if timeout <= 0:
            raise AdapterFault("unavailable")
        result = Queue(maxsize=1)
        def perform():
            try:
                result.put((True, operation()))
            except BaseException:
                result.put((False, None))
        # One outstanding operation under the session lock. A timeout retires the
        # session and kills its owned job, unblocking the pipe; no watcher/poll loop.
        Thread(target=perform, daemon=True).start()
        try:
            success, value = result.get(timeout=timeout)
        except Empty:
            raise AdapterFault("unavailable") from None
        if not success:
            raise AdapterFault("backend_failure")
        return value

    def send(self, raw: bytes, timeout: float) -> None:
        def write():
            written = self.process.stdin.write(raw)
            self.process.stdin.flush()
            if written != len(raw):
                raise ValueError("short_worker_write")
        self._bounded(write, timeout)

    def receive(self, limit: int, timeout: float) -> bytes:
        raw = self._bounded(lambda: self.process.stdout.readline(limit + 1), timeout)
        if not raw or len(raw) > limit:
            raise AdapterFault("invalid_output")
        return raw

    def terminate(self) -> None:
        self._terminate_job()

    def wait(self, timeout: float) -> None:
        self._bounded(lambda: self.process.wait(timeout=timeout), timeout)
