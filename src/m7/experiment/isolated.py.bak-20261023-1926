"""Campaign-owned lazy worker adapters. Definitions/validation never launch.

The evaluator alone holds gold/custody/ledgers. Native launch and exact-process
attestation are injected mandatory controls; no Popen-as-isolation fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Mapping

from m7.contracts import LogRecord, Prediction, failure
from m7.providers.contracts import AdapterFault, CashReceipt, config_digest
from time import perf_counter
from uuid import uuid4
from m7.providers.worker_profile import (
    WorkerLaunchPolicy, WorkerProfile, validate_worker_membership, worker_profile_digest,
)
from m7.providers.worker_wire import AttemptEvent, ReconcileRequest, WorkerBootstrap

from .executor import AdapterBinding
from .models import ARMS, ArmPin, LockedEdition

if TYPE_CHECKING:
    from m7.data.access import IsolationGuard
    from m7.data.filesystem import CustodyFilesystem
    from m7.ledger import ReservationLedger
    from m7.providers.worker import WorkerSessionProtocol
    from m7.providers.worker_transport import IsolatedLauncher, WorkerProcessVerifier
    from .costing import EconomicAllocation


@dataclass(frozen=True)
class WorkerDefinition:
    """Internal view of D5's canonical joined export, never a competing JSON wire."""
    bootstrap: WorkerBootstrap
    launch: WorkerLaunchPolicy


@dataclass(frozen=True)
class IsolatedCampaignHost:
    verify_receipt: Callable[[str, str], bool]
    custody_filesystem: CustodyFilesystem
    isolation_guard: IsolationGuard
    launcher: IsolatedLauncher
    process_verifier: WorkerProcessVerifier
    ledgers: Mapping[str, ReservationLedger]
    training_summary: Callable[[], dict]
    cancelled: Callable[[], bool] = lambda: False
    reconcile_verifier: Callable[[ReconcileRequest], CashReceipt | None] | None = None
    diagnostic_sink: Callable[[dict], None] | None = None
    economic_allocation: EconomicAllocation | None = None


def validate_definitions(edition: LockedEdition, profile: WorkerProfile,
                         definitions: Mapping[str, WorkerDefinition],
                         launch_digests: Mapping[str, str]) -> dict:
    """Pure source/pin checks via D6 helpers; no auth, paths, files or spawning."""
    from m7.providers.worker import validate_worker_spec
    if set(definitions) != set(ARMS) or set(profile.members) != set(ARMS) or set(launch_digests) != set(ARMS):
        raise ValueError('all_four_isolated_workers_required')
    pins = {pin.arm: pin for pin in edition.arm_pins}
    sessions = set()
    working = []
    memberships = {}
    for arm in ARMS:
        definition = definitions[arm]
        bootstrap, policy = definition.bootstrap, definition.launch
        member = validate_worker_membership(profile, policy)
        validate_worker_spec(bootstrap, policy, profile=profile)
        pin = ArmPin.model_validate(bootstrap.pin.model_dump(mode='python'))
        if (pin != pins[arm] or policy.arm != arm or bootstrap.run_id != edition.run_id
                or policy.edition_id != edition.edition_id
                or policy.corpus_manifest_sha256 != edition.corpus_manifest_sha256
                or member.launch_sha256 != launch_digests[arm]
                or bootstrap.limits.max_records < len(edition.population)
                or bootstrap.session_id in sessions):
            raise ValueError('campaign_worker_identity_mismatch')
        from pathlib import Path
        directory = Path(policy.working_directory)
        if '..' in directory.parts or any(directory == other or directory.is_relative_to(other)
                                          or other.is_relative_to(directory) for other in working):
            raise ValueError('worker_working_directories_must_be_disjoint')
        working.append(directory)
        sessions.add(bootstrap.session_id)
        memberships[arm] = member
    return {'profile_sha256': worker_profile_digest(profile),
            'launch_sha256': {arm: row.launch_sha256 for arm, row in memberships.items()},
            'spawned': False, 'isolation_verified': False}


class _WorkerAdapter:
    def __init__(self, edition: LockedEdition, definition: WorkerDefinition,
                 profile: WorkerProfile, pin: ArmPin, host: IsolatedCampaignHost,
                 revalidate: Callable[[], None]):
        self.edition, self.definition, self.profile, self.pin = edition, definition, profile, pin
        self.host, self.revalidate = host, revalidate
        self.session: WorkerSessionProtocol | None = None
        self._last_identity: tuple[str, str] | None = None
        self._guard_events: tuple[AttemptEvent, ...] | None = None
        self.cleanup_status = 'not_started'

    def _guard(self):
        self.edition.require_current()
        self.revalidate()
        membership = validate_worker_membership(self.profile, self.definition.launch)
        for kind, digest in (('worker_profile_approval', membership.profile_sha256),
                             ('worker_launch_approval', membership.launch_sha256),
                             ('worker_bootstrap', config_digest(self.definition.bootstrap)),
                             ('worker_application_manifest', self.definition.launch.application_manifest_sha256),
                             ('worker_runtime_environment', self.definition.launch.runtime_environment_sha256)):
            if self.host.verify_receipt(kind, digest) is not True:
                raise AdapterFault('permit_required')
        self.host.isolation_guard.require_current(self.edition.edition_id,
            self.edition.corpus_manifest_sha256,
            filesystem_policy_sha256=self.definition.launch.filesystem_policy_sha256,
            worker_policy_sha256=membership.profile_sha256)
        if self.host.cancelled():
            self.cancel()
            raise AdapterFault('cancelled')

    def preflight(self, records: tuple[LogRecord, ...]) -> None:
        self._guard()
        if self.session is None:
            from m7.providers.worker import launch_worker
            # No held-out directories, gold, provenance or ledger paths reach the
            # child bootstrap. Ledgers stay in this parent-side broker mapping.
            self.host.custody_filesystem.require_path('inference', self.definition.launch.working_directory)
            self.session = launch_worker(self.definition.bootstrap, self.definition.launch,
                profile=self.profile, isolation_guard=self.host.isolation_guard,
                launcher=self.host.launcher, process_verifier=self.host.process_verifier,
                ledgers=self.host.ledgers, allow_execution=True,
                reconcile_verifier=self.host.reconcile_verifier,
                diagnostic_sink=self.host.diagnostic_sink)
            self.cleanup_status = 'open'
        self.session.preflight(records)
        self._guard()

    def predict(self, record: LogRecord) -> Prediction:
        self._last_identity = (record.record_id, record.content_sha256)
        self._guard_events = None
        started = perf_counter()
        try:
            self._guard()
            if self.session is None or record.split_id != 'inference':
                raise AdapterFault('unavailable')
        except Exception as error:
            # Only this pre-dispatch guard is known to have sent NO request. Never
            # apply this normalization around session.predict (which may have sent).
            code = error.code if isinstance(error, AdapterFault) else 'permit_required'
            status = ('cancelled' if code == 'cancelled' else 'invalid_output'
                      if code in ('invalid_output', 'truncated') else 'unavailable')
            attempt_id = 'parent-guard-' + uuid4().hex
            event = AttemptEvent.model_validate({'run_id': self.edition.run_id,
                'arm': self.pin.arm, 'model_id': self.pin.model_id,
                'record_id': record.record_id, 'content_sha256': record.content_sha256,
                'attempt': {'attempt_id': attempt_id, 'ordinal': 1, 'status': status,
                    'error_code': code, 'duration_ms': (perf_counter() - started) * 1000,
                    'input_tokens': None, 'output_tokens': None, 'reservation_micros': None,
                    'actual_micros': None, 'liability_status': 'not_reserved',
                    'retry_reason': 'cancelled_before_reserve' if code == 'cancelled' else 'preflight_rejected',
                    'physical_may_have_started': False}})
            self._guard_events = (event,)
            return failure(record, run_id=self.edition.run_id, arm=self.pin.arm,
                           model_id=self.pin.model_id, attempt_id=attempt_id, status=status, error_code=code)
        return self.session.predict(record)

    def metadata(self) -> tuple[object, ...]:
        if self.session is None and self._guard_events is None:
            return ()
        output = []
        for source in self._guard_events if self._guard_events is not None else self.session.last_attempts:
            event = AttemptEvent.model_validate_json(source.model_dump_json())
            if (event.run_id != self.edition.run_id or event.arm != self.pin.arm
                    or event.model_id != self.pin.model_id
                    or (event.record_id, event.content_sha256) != self._last_identity):
                raise ValueError('worker_attempt_metadata_identity_mismatch')
            output.append(event.attempt.model_dump(mode='python'))
        # An uncertain worker crash can have known reservations but no trustworthy
        # retry reason. Preserve that as missing lineage rather than invent a cause.
        if len(output) > 2 or len(output) == 2 and output[0]['retry_reason'] != 'transient_transport':
            raise ValueError('worker_retry_lineage_unknown')
        return tuple(output)

    def cancel(self):
        if self.session is not None:
            self.session.cancel()  # ONLY this launch's owned process/job.
            self.cleanup_status = self.session.cleanup_status

    def close(self):
        if self.session is None:
            self.cleanup_status = 'not_started'
            return
        try:
            self.session.close()
            self.cleanup_status = self.session.cleanup_status
        except BaseException:
            self.cleanup_status = 'cleanup_unverified'


class IsolatedRegistry:
    """Owns only sessions it creates; construction/validation are inert."""
    def __init__(self, edition: LockedEdition, profile: WorkerProfile,
                 definitions: Mapping[str, WorkerDefinition], launch_digests: Mapping[str, str],
                 *, host: IsolatedCampaignHost, revalidate: Callable[[], None]):
        validate_definitions(edition, profile, definitions, launch_digests)
        self.adapters = {pin.arm: _WorkerAdapter(edition, definitions[pin.arm], profile, pin, host, revalidate)
                         for pin in edition.arm_pins}
        self.bindings = {arm: AdapterBinding(pin=adapter.pin, predict=adapter.predict,
                                             preflight=adapter.preflight, attempt_metadata=adapter.metadata)
                         for arm, adapter in self.adapters.items()}

    def cancel(self) -> None:
        for adapter in self.adapters.values():
            adapter.cancel()

    def close(self) -> dict[str, str]:
        for adapter in self.adapters.values():
            adapter.close()
        return {arm: adapter.cleanup_status for arm, adapter in self.adapters.items()}


__all__ = ['IsolatedCampaignHost', 'IsolatedRegistry', 'WorkerDefinition', 'validate_definitions']
