"""Operator-supplied host inputs for the composition root. No defaults verify anything.

Every trust service here is either a genuinely external input (receipt verifier,
launch host, warm attestor, cash snapshots, reconcile receipts, training summary)
or an existing source adapter the operator constructs over approved records
(custody filesystem, isolation guard, native process verifier). This module never
implements, relaxes or substitutes any of them.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from m7.data.access import IsolationGuard
    from m7.data.filesystem import CustodyFilesystem
    from m7.data.native_windows import WindowsWorkerProcessVerifier
    from m7.experiment.costing import EconomicAllocation
    from m7.ledger import ReservationLedger
    from m7.providers.native_launcher import PreprovisionedWindowsContext, WindowsLaunchHost
    from m7.providers.worker_timing import WarmBackendAttestor

MODEL_ARMS = frozenset({'base', 'finetuned', 'frontier'})


class HostServiceMissing(ValueError):
    """Names only the missing/invalid field, never a value."""


@dataclass(frozen=True)
class HostServices:
    verify_receipt: Callable[[str, str], bool]
    custody_filesystem: CustodyFilesystem
    isolation_guard: IsolationGuard
    # Must be built by the operator over THIS custody_filesystem instance.
    process_verifier: WindowsWorkerProcessVerifier
    launch_host: WindowsLaunchHost
    launch_contexts: Mapping[str, PreprovisionedWindowsContext] = field(repr=False)
    ledgers: Mapping[str, ReservationLedger]
    training_summary: Callable[[], dict]
    cancelled: Callable[[], bool] = lambda: False
    # Absent keeps child-reported cash untrusted and liability unknown (fail closed).
    reconcile_verifier: Callable | None = None
    diagnostic_sink: Callable[[dict], None] | None = None
    economic_allocation: EconomicAllocation | None = None
    # Timing-only inputs; required when timing is requested.
    warm_attestor: WarmBackendAttestor | None = None
    timing_snapshot_provider: Callable[[], object] | None = None
    timing_clock: Callable[[], object] | None = None

    def require_core(self) -> None:
        from m7.data.access import IsolationGuard
        from m7.data.filesystem import CustodyFilesystem
        if not callable(self.verify_receipt):
            raise HostServiceMissing('host_service_missing:verify_receipt')
        if not isinstance(self.custody_filesystem, CustodyFilesystem):
            raise HostServiceMissing('host_service_missing:custody_filesystem')
        if not isinstance(self.isolation_guard, IsolationGuard):
            raise HostServiceMissing('host_service_missing:isolation_guard')
        if not callable(self.cancelled):
            raise HostServiceMissing('host_service_missing:cancelled')

    def require_campaign(self, *, timing: bool) -> None:
        from m7.data.native_windows import WindowsWorkerProcessVerifier
        self.require_core()
        # The only source process verifier; timing additionally requires this exact class
        # (timing_native.py), so it is required for every campaign host.
        if not isinstance(self.process_verifier, WindowsWorkerProcessVerifier):
            raise HostServiceMissing('host_service_missing:process_verifier')
        # WindowsTimingProcessGuard refuses unless these are one object; check before any edition opens.
        if self.process_verifier.filesystem is not self.custody_filesystem:
            raise HostServiceMissing('host_service_mismatch:process_verifier.filesystem')
        if self.launch_host is None:
            raise HostServiceMissing('host_service_missing:launch_host')
        if not isinstance(self.launch_contexts, Mapping) or not self.launch_contexts:
            raise HostServiceMissing('host_service_missing:launch_contexts')
        if not isinstance(self.ledgers, Mapping) or set(self.ledgers) != MODEL_ARMS:
            raise HostServiceMissing('host_service_missing:ledgers')
        if not callable(self.training_summary):
            raise HostServiceMissing('host_service_missing:training_summary')
        if timing:
            for name in ('warm_attestor', 'timing_snapshot_provider'):
                if not callable(getattr(self, name)):
                    raise HostServiceMissing('host_service_missing:' + name)
