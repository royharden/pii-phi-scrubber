"""Authoritative retained-session timing continuation, explicit activation only."""
from __future__ import annotations

import os
from pathlib import Path
from time import perf_counter
from typing import Callable, TYPE_CHECKING

from m7.contracts import LogRecord, Prediction, validate_prediction
from m7.render import render
from m7.ledger import BudgetExceeded
from m7.providers.contracts import config_digest
from .executor import read_attempt_metadata
from .models import ARMS, LockedEdition, PopulationMember, canonical, commitment
from .timing import _statistics
from .timing_contracts import (IsolatedTimingPlan, PrimaryAccountingReceipt,
    TimingContinuationAuthority, TimingPhasePermit, TimingPhaseRequest, WarmBackendIdentity)

if TYPE_CHECKING:
    from .isolated import IsolatedRegistry
    from .journal import EditionJournal


def _timed_call(binding, record, run_id):
    prediction = binding.predict(LogRecord.model_validate_json(record.model_dump_json()))
    if not isinstance(prediction, Prediction):
        return False, None
    prediction = Prediction.model_validate_json(prediction.model_dump_json())
    if (prediction.run_id != run_id or prediction.arm != binding.pin.arm
            or prediction.model_id != binding.pin.model_id):
        return False, None
    prediction = validate_prediction(record, prediction)
    if prediction.status != 'ok':
        return False, prediction.attempt_id
    rendered = render(record, prediction)
    return rendered.schema_valid and rendered.safe_log is not None, prediction.attempt_id


def primary_accounting(edition: LockedEdition, journal: EditionJournal, quality: dict) -> PrimaryAccountingReceipt:
    """Caller holds the journal writer; negative terminal outcomes remain valid.

    The receipt commits all original predictions/accounting in the private
    journal, and the primary quality projection. No predictions enter workers.
    """
    if not journal.closed or journal.abandoned():
        raise ValueError('closed_primary_without_unresolved_begins_required')
    cells = journal.terminals()
    ordered = [cells[(arm, row.record_id)].model_dump(mode='json')
               for arm in ARMS for row in edition.population]
    return PrimaryAccountingReceipt(edition_sha256=edition.sha256,
        journal_head_sha256=journal.head_sha256,
        population_sha256=commitment([r.model_dump(mode='json') for r in edition.population]),
        terminal_cells_sha256=commitment(ordered), quality_sha256=commitment(quality),
        intended_cells=len(edition.population) * 4, terminal_cells=len(cells),
        uncertain_terminal_cells=sum(c.outcome == 'interrupted_unknown' or c.attempt_metadata_missing
                                     for c in cells.values()))


def validate_timing_plan(edition: LockedEdition, plan: IsolatedTimingPlan) -> None:
    if (plan.sha256 != edition.timing_plan_sha256 or plan.edition_id != edition.edition_id
            or plan.run_id != edition.run_id or plan.arm_pins != edition.arm_pins
            or sorted(plan.record_order, key=lambda row: row.record_id) != list(edition.population)):
        raise ValueError('isolated_timing_plan_not_preregistered')


def validate_timing_records(edition: LockedEdition, records: tuple[LogRecord, ...],
                            plan: IsolatedTimingPlan) -> None:
    validate_timing_plan(edition, plan)
    if (any(r.split_id != 'inference' for r in records) or
            tuple(PopulationMember(record_id=r.record_id, content_sha256=r.content_sha256)
                  for r in records) != plan.record_order):
        raise ValueError('timing_original_inference_population_and_order_required')


def retained_timing_identities(registry: IsolatedRegistry, plan: IsolatedTimingPlan,
                               verify_receipt: Callable[[str, str], bool]) -> dict[str, WarmBackendIdentity]:
    """Post-primary host handoff only; unavailable arms have no invented identity."""
    output = {}
    for arm in ARMS:
        adapter = registry.adapters[arm]
        try:
            adapter._guard()
            if adapter.session is None or adapter.cleanup_status != 'open':
                continue
            row = WarmBackendIdentity.model_validate_json(adapter.session.timing_identity().model_dump_json())
            if (row.arm != arm or row.pin != adapter.pin
                    or row.session_id != adapter.definition.bootstrap.session_id
                    or row.bootstrap_sha256 != config_digest(adapter.definition.bootstrap)
                    or row.profile_sha256 != registry.profile_sha256
                    or row.launch_sha256 != registry.launch_digests[arm]
                    or row.primary_population_sha256 != plan.population_sha256
                    or row.primary_order_sha256 != plan.order_sha256
                    or verify_receipt('warm_backend_attestation', row.attestation_sha256) is not True):
                continue
            output[arm] = row
        except Exception:
            continue
    return output


def run_isolated_timing(edition: LockedEdition, records: tuple[LogRecord, ...],
                        plan: IsolatedTimingPlan, registry: IsolatedRegistry,
                        primary: PrimaryAccountingReceipt, *, journal: EditionJournal,
                        authority: TimingContinuationAuthority, destination: Path,
                        identities: dict[str, WarmBackendIdentity],
                        verify_receipt: Callable[[str, str], bool],
                        cancelled: Callable[[], bool]) -> dict:
    """Never creates a session, reopens custody or mutates primary accounting.

    Sessions are the exact registry objects retained from primary execution;
    unsupported/dead/unknown arms stay in the denominator. A consumed/uncertain
    timing journal cannot be replayed. Outer campaign owns finally cleanup.
    """
    validate_timing_records(edition, records, plan)
    by_id = {r.record_id: r for r in records}
    if (set(identities) - set(ARMS) or
            any(row.arm != arm for arm, row in identities.items()) or
            len({(row.process_id, row.process_start_identity) for row in identities.values()}) != len(identities)):
        raise ValueError('timing_survivor_identity_keys_or_processes_invalid')
    if journal.filesystem is None:
        raise ValueError('timing_private_filesystem_required')
    fs = journal.filesystem
    destination = fs.require_path('evaluator', destination, must_exist=False)
    authority.prepare(primary, plan)  # No heldout-open permission consumed here.
    for kind, digest in (('timing_plan', plan.sha256),
                         ('timing_hardware', plan.hardware_receipt_sha256),
                         ('primary_accounting', primary.sha256)):
        if verify_receipt(kind, digest) is not True:
            raise ValueError('timing_plan_or_primary_not_authenticated')
    output = {'schema_version': 'IsolatedTimingResult/v1', 'plan_sha256': plan.sha256,
              'edition_sha256': edition.sha256, 'primary_accounting_sha256': primary.sha256,
              'passes': 3, 'concurrency': 1, 'cache_replay': False,
              'process_replacement': False, 'primary_quality_changed': False,
              'gold_safety_scoring_included': False, 'safety_scoring_overhead_ms': None,
              'hardware_receipt_sha256': plan.hardware_receipt_sha256, 'arms': []}
    output['hardware'] = plan.hardware.model_dump(mode='json')
    with journal.writer():
        journal.seal(edition)
        if not journal.closed or journal.abandoned() or journal.head_sha256 != primary.journal_head_sha256:
            raise ValueError('primary_changed_or_uncertain')
        destination.mkdir(parents=True, exist_ok=False)
        marker = fs.require_path('evaluator', destination / 'timing-started.json', must_exist=False)
        # Atomic exclusive marker prevents resets after interruption, even if no
        # response or authority finish receipt was durably received.
        with marker.open('xb') as handle:
            handle.write(canonical({'primary_sha256': primary.sha256, 'plan_sha256': plan.sha256}))
            handle.flush()
            os.fsync(handle.fileno())
        events_path = fs.require_path('evaluator', destination / 'timing-events.jsonl', must_exist=False)
        previous = commitment({'primary': primary.sha256, 'plan': plan.sha256})
        sequence = 0
        attempt_ids = {attempt.attempt_id for cell in journal.terminals().values() for attempt in cell.attempts}

        def event(payload):
            nonlocal previous, sequence
            body = {'sequence': sequence, 'previous': previous, 'event': payload}
            digest = commitment(body)
            with events_path.open('ab') as handle:
                handle.write(canonical({**body, 'sha256': digest}) + b'\n')
                handle.flush()
                os.fsync(handle.fileno())
            previous, sequence = digest, sequence + 1

        for arm in ARMS:
            adapter = registry.adapters[arm]
            binding = registry.timing_binding(arm)
            session = adapter.session  # NO launch/preflight/factory in this scope.
            identity = identities.get(arm)
            unavailable = False
            all_samples = []
            passes = []

            def current_identity():
                if identity is None or session is None or adapter.session is not session or adapter.cleanup_status != 'open':
                    raise ValueError('original_warm_session_unavailable')
                adapter._guard()  # Current original campaign/P/L/native/cash rights.
                found = WarmBackendIdentity.model_validate_json(session.timing_identity().model_dump_json())
                membership = registry.launch_digests[arm]
                if (found.arm != arm or found.pin != adapter.pin
                        or found.session_id != adapter.definition.bootstrap.session_id
                        or found.bootstrap_sha256 != config_digest(adapter.definition.bootstrap)
                        or found.profile_sha256 != registry.profile_sha256
                        or found.launch_sha256 != membership
                        or found.primary_population_sha256 != plan.population_sha256
                        or found.primary_order_sha256 != plan.order_sha256
                        or verify_receipt('warm_backend_attestation', found.attestation_sha256) is not True
                        or found != identity):
                    raise ValueError('warm_identity_changed_or_unverified')
                return found

            try:
                identity = current_identity()
            except Exception:
                unavailable = True
            for ordinal in (1, 2, 3):
                phase_started = perf_counter()
                samples = []
                control_overhead_ms = 0.0
                request = None
                consumed = False
                complete = False
                failure = 'adapter_unavailable' if unavailable else None
                try:
                    if cancelled():
                        failure = 'cancelled'
                        unavailable = True
                    if unavailable:
                        raise ValueError('warm_session_unavailable')
                    current_identity()
                    namespace = commitment({'primary': primary.sha256, 'plan': plan.sha256,
                        'identity': identity.model_dump(mode='json'), 'ordinal': ordinal})
                    request = TimingPhaseRequest(edition_sha256=edition.sha256,
                        primary_accounting_sha256=primary.sha256, plan_sha256=plan.sha256,
                        population_sha256=plan.population_sha256, order_sha256=plan.order_sha256,
                        identity=identity, ordinal=ordinal, attempt_namespace=namespace)
                    event({'kind': 'phase_begin', 'arm': arm, 'ordinal': ordinal,
                           'request_sha256': commitment(request.model_dump(mode='json'))})
                    # Mark uncertainty BEFORE invoking a consuming external gate.
                    consumed = True
                    permit = TimingPhasePermit.model_validate_json(authority.authorize(request).model_dump_json())
                    request_digest = commitment(request.model_dump(mode='json'))
                    if (permit.request_sha256 != request_digest or
                            authority.verify_receipt('timing_custody_continuation', permit.custody_receipt_sha256) is not True or
                            authority.verify_receipt('timing_resource_receipt', permit.resource_receipt_sha256) is not True):
                        raise ValueError('timing_phase_permit_not_authenticated')
                    authority.current(request, permit)
                    current_identity()
                    session.begin_timing_phase(request, permit, verify_receipt=authority.verify_receipt)
                    for index, member in enumerate(plan.record_order):
                        if cancelled():
                            failure = 'cancelled'
                            raise ValueError('timing_cancelled')
                        control_started = perf_counter()
                        authority.current(request, permit)
                        current_identity()
                        control_overhead_ms += (perf_counter() - control_started) * 1000
                        row = by_id[member.record_id]
                        event({'kind': 'sample_begin', 'arm': arm, 'ordinal': ordinal, 'index': index})
                        started = perf_counter()
                        attempted, ok, metadata = True, False, ()
                        prediction_attempt_id = None
                        metadata_missing = False
                        try:
                            ok, prediction_attempt_id = _timed_call(binding, row, edition.run_id)
                        except BudgetExceeded:
                            attempted = False  # D6 first-reserve, zero physical only.
                        except Exception:
                            ok = False
                        elapsed = (perf_counter() - started) * 1000
                        try:
                            metadata = read_attempt_metadata(binding)
                            metadata_missing = not bool(metadata) and attempted
                            ids = [item.attempt_id for item in metadata]
                            if len(ids) != len(set(ids)) or any(value in attempt_ids for value in ids):
                                metadata_missing = True
                                attempted, metadata, ok = False, (), False
                            if ok and (not ids or prediction_attempt_id != ids[-1]):
                                metadata_missing, ok = True, False
                            attempt_ids.update(ids)
                        except Exception:
                            metadata_missing = True
                        if metadata_missing:
                            ok = False
                        if metadata and not any(a.physical_may_have_started for a in metadata) and not ok:
                            attempted = False
                        sample = {'duration_ms': elapsed if attempted else 0.0,
                            'attempted': attempted, 'ok': ok, 'length': len(row.log.message),
                            'physical_attempts_N': sum(a.physical_may_have_started for a in metadata),
                            'retry_attempts_N': sum(a.ordinal > 1 for a in metadata),
                            'metadata_missing': metadata_missing}
                        samples.append(sample)
                        event({'kind': 'sample_terminal', 'arm': arm, 'ordinal': ordinal,
                               'index': index, 'sample': sample})
                        # Failed output is accounted; missing diagnostics cannot
                        # be used to make more calls under an unknown cash scope.
                        if metadata_missing:
                            raise ValueError('timing_attempt_lineage_unknown')
                    authority.current(request, permit)
                    current_identity()
                    session.finish_timing_phase(request)
                    current_identity()
                    complete = True
                except Exception:
                    failure = failure or 'timing_failed'
                    unavailable = True  # Never reset/respawn after uncertainty.
                finally:
                    if consumed and request is not None:
                        try:
                            authority.finish(request, completed=complete)
                        except Exception:
                            failure, complete, unavailable = 'timing_failed', False, True
                status = ('measured' if complete and len(samples) == len(records) and all(s['ok'] for s in samples)
                          else 'partial' if any(s['attempted'] for s in samples) else 'unavailable')
                event({'kind': 'phase_terminal', 'arm': arm, 'ordinal': ordinal,
                       'status': status, 'error_code': failure})
                wall_seconds = (perf_counter() - phase_started) if any(s['attempted'] for s in samples) else None
                passes.append({'pass': ordinal, 'status': status, 'error_code': failure,
                               'parent_control_overhead_ms': control_overhead_ms if samples else None,
                               'protocol_elapsed_seconds': wall_seconds,
                               'protocol_answered_per_second': (sum(s['ok'] for s in samples) / wall_seconds
                                    if wall_seconds is not None and wall_seconds > 0 else None),
                               **_statistics(samples, len(records))})
                all_samples.extend(samples)
            output['arms'].append({'arm': arm,
                'status': 'measured' if all(p['status'] == 'measured' for p in passes) else 'unavailable_or_partial',
                'cold_startup_ms': adapter.launch_handshake_ms,
                'cold_kind': 'client_process_handshake' if arm == 'frontier' else 'process_backend_handshake',
                'provider_server_startup_ms': None, 'model_load_only_ms': None,
                'passes': passes, 'all_passes': _statistics(all_samples, len(records) * 3),
                'length_slices': [{'minimum': s.minimum, 'maximum': s.maximum,
                    **_statistics([row for row in all_samples if s.minimum <= row['length'] <= s.maximum],
                        3 * sum(s.minimum <= len(r.log.message) <= s.maximum for r in records))}
                    for s in plan.length_slices]})
        if journal.head_sha256 != primary.journal_head_sha256:
            raise ValueError('primary_accounting_mutated_during_timing')
        event({'kind': 'timing_closed', 'result_sha256': commitment(output)})
        output['journal_sha256'] = previous
    return output
