"""Explicit future three-pass timing; no calls, filesystem or clocks on import."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable, Literal, Mapping

from pydantic import model_validator

from m7.contracts import Boundary, Digest, Identifier, LogRecord, Prediction, validate_prediction
from m7.render import render

from .executor import AdapterBinding, read_attempt_metadata
from .models import ARMS, LockedEdition, PopulationMember, canonical, commitment
from .journal import EditionJournal


from .timing_contracts import HardwareContext, TimingLengthSlice as LengthSlice


class TimingPlan(Boundary):
    schema_version: Literal['TimingPlan/v1'] = 'TimingPlan/v1'
    edition_id: Identifier
    run_id: Identifier
    population_sha256: Digest
    record_order: tuple[PopulationMember, ...]
    warmup_content_sha256: Digest
    hardware: HardwareContext
    concurrency: Literal[1] = 1
    passes: Literal[3] = 3
    length_slices: tuple[LengthSlice, ...]

    @model_validator(mode='after')
    def partitions(self) -> TimingPlan:
        cursor = 0
        for item in self.length_slices:
            if item.minimum != cursor or item.maximum < item.minimum:
                raise ValueError('length_slices_must_partition_0_to_1024')
            cursor = item.maximum + 1
        if cursor != 1025 or not self.record_order:
            raise ValueError('complete_timing_population_and_slices_required')
        ids = [r.record_id for r in self.record_order]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate_timing_record')
        return self


@dataclass(frozen=True)
class TimingWorker:
    binding: AdapterBinding
    # Host implementation performs import/model load here, before warmup; client
    # initialization only for frontier. No provider-server startup claim is made.
    startup: Callable[[], None]
    # Distinct logical-call controller per pass, same warmed model backend. The
    # evaluator's replay-guarded controller must never supply cached timing calls.
    binding_for_pass: Callable[[int], AdapterBinding]


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _sample(binding: AdapterBinding, record: LogRecord, run_id: str) -> bool:
    prediction = binding.predict(LogRecord.model_validate(record.model_dump(mode='python')))
    if not isinstance(prediction, Prediction):
        return False
    prediction = Prediction.model_validate_json(prediction.model_dump_json())
    if (prediction.run_id != run_id or prediction.arm != binding.pin.arm
            or prediction.model_id != binding.pin.model_id):
        return False
    prediction = validate_prediction(record, prediction)
    if prediction.status != 'ok':
        return False
    output = render(record, prediction)
    return output.schema_valid and output.safe_log is not None


def _statistics(samples: list[dict], intended: int) -> dict:
    values = [s['duration_ms'] for s in samples if s['attempted']]
    successful = [s['duration_ms'] for s in samples if s['ok']]
    seconds = sum(s['duration_ms'] for s in samples) / 1000
    return {'intended_samples_N': intended, 'attempted_samples_N': len(values),
            'logical_calls_N': len(samples), 'physical_attempts_N': sum(s['physical_attempts_N'] for s in samples),
            'retry_attempts_N': sum(s['retry_attempts_N'] for s in samples),
            'attempt_metadata_missing_N': sum(s['metadata_missing'] for s in samples),
            'answered_samples_N': len(successful), 'failed_samples_N': len(values) - len(successful),
            'unattempted_samples_N': intended - len(values),
            'all_attempt_p50_ms': _percentile(values, .5), 'all_attempt_p95_ms': _percentile(values, .95),
            'successful_only_p50_ms': _percentile(successful, .5),
            'successful_only_p95_ms': _percentile(successful, .95),
            'elapsed_detector_seconds': seconds if values else None,
            'attempts_per_second': len(values) / seconds if seconds > 0 and values else None,
            'answered_per_second': len(successful) / seconds if seconds > 0 and values else None}


def run_timing(edition: LockedEdition, inference: tuple[LogRecord, ...], plan: TimingPlan,
               warmup_record: LogRecord, factories: Mapping[str, Callable[[], TimingWorker]],
               destination: str | Path, *, evaluation_journal: EditionJournal,
               authorize: Callable[[LockedEdition, bool], None],
               verify_timing_authority: Callable[[str], bool],
               cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Future explicit activation only, AFTER the primary evaluation has closed.

    `verify_timing_authority(plan_digest)` must authenticate permission for three
    fixed repeats plus warmup and their worst-case costs; edition permission alone
    is insufficient. It also authenticates hardware/environment declarations.
    D6 controllers own each invocation's reservations, retries and bill receipts.
    A run marker is exclusive: interrupted timing cannot silently restart/retune.
    Private samples contain ordinal/length/pass/outcome/time only, never text/gold.
    """
    expected = {r.record_id: r.content_sha256 for r in edition.population}
    supplied = {r.record_id: r.content_sha256 for r in inference}
    ordered = {r.record_id: r.content_sha256 for r in plan.record_order}
    digest = commitment(plan.model_dump(mode='json'))
    if (len(supplied) != len(inference) or expected != supplied or expected != ordered
            or plan.edition_id != edition.edition_id or plan.run_id != edition.run_id
            or plan.population_sha256 != commitment([r.model_dump(mode='json') for r in edition.population])
            or digest != edition.timing_plan_sha256 or set(factories) - set(ARMS)
            or warmup_record.content_sha256 != plan.warmup_content_sha256
            or warmup_record.record_id in expected or warmup_record.split_id not in ('development', 'public-development')):
        raise ValueError('timing_plan_or_population_mismatch')
    edition.require_current()
    authorize(edition, True)
    if verify_timing_authority(digest) is not True:
        raise ValueError('timing_execution_not_authorized')
    with evaluation_journal.writer():
        evaluation_journal.seal(edition)
        if not evaluation_journal.closed:
            raise ValueError('closed_primary_evaluation_required_for_timing')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / 'timing-started.json').open('xb') as handle:
        handle.write(canonical({'plan_sha256': digest, 'edition_sha256': edition.sha256}))
        handle.flush()
        os.fsync(handle.fileno())
    records = {r.record_id: r for r in inference}
    pins = {p.arm: p for p in edition.arm_pins}
    result = {'schema_version': 'TimingResult/v1', 'plan_sha256': digest,
              'edition_sha256': edition.sha256, 'passes': 3, 'concurrency': 1,
              'hardware': plan.hardware.model_dump(mode='json'), 'arms': [],
              'gold_safety_scoring_included': False, 'safety_scoring_overhead_ms': None}
    stop = False
    # Single serial arm/three-pass/record-order loop. No worker pool or batch tuning.
    for arm in ARMS:
        samples: list[dict] = []
        cold_ms = None
        error = None
        worker = None
        factory = factories.get(arm)
        try:
            if factory is None:
                error = 'adapter_unavailable'
            elif stop or cancelled():
                stop, error = True, 'cancelled'
            else:
                edition.require_current()
                authorize(edition, True)
                if verify_timing_authority(digest) is not True:
                    raise ValueError('timing_authority_revoked')
                start = perf_counter()
                worker = factory()
                if not isinstance(worker, TimingWorker) or worker.binding.pin != pins[arm]:
                    raise ValueError('timing_worker_pin_mismatch')
                worker.startup()
                cold_ms = (perf_counter() - start) * 1000
                worker.binding.preflight(inference)
                edition.require_current()
                authorize(edition, True)
                if verify_timing_authority(digest) is not True:
                    raise ValueError('timing_authority_revoked')
                # Exactly one declared public-dev warmup; neither quality nor time
                # is used to tune the locked model or choose records.
                with (destination / 'samples.jsonl').open('ab') as handle:
                    handle.write(canonical({'phase': 'warmup_begin', 'arm': arm}) + b'\n')
                    handle.flush()
                    os.fsync(handle.fileno())
                warmup_ok = _sample(worker.binding, warmup_record, edition.run_id)
                try:
                    warmup_attempts = read_attempt_metadata(worker.binding) if arm != 'regex' else ()
                except Exception:
                    warmup_attempts = ()
                with (destination / 'samples.jsonl').open('ab') as handle:
                    handle.write(canonical({'phase': 'warmup_terminal', 'arm': arm, 'ok': warmup_ok,
                        'attempts': [a.model_dump(mode='json') for a in warmup_attempts]}) + b'\n')
                    handle.flush()
                    os.fsync(handle.fileno())
                if not warmup_ok:
                    raise ValueError('warmup_failed')
                for pass_index in range(3):
                    pass_binding = worker.binding_for_pass(pass_index)
                    if pass_binding.pin != pins[arm]:
                        raise ValueError('timing_pass_pin_mismatch')
                    for ordinal, member in enumerate(plan.record_order):
                        if cancelled():
                            stop, error = True, 'cancelled'
                            break
                        edition.require_current()
                        authorize(edition, True)
                        if verify_timing_authority(digest) is not True:
                            raise ValueError('timing_authority_revoked')
                        record = records[member.record_id]
                        # Durable begin before any potentially billable call. A
                        # partial run is retained, never automatically reissued.
                        with (destination / 'samples.jsonl').open('ab') as handle:
                            handle.write(canonical({'phase': 'begin', 'arm': arm,
                                'pass': pass_index, 'ordinal': ordinal}) + b'\n')
                            handle.flush()
                            os.fsync(handle.fileno())
                        start = perf_counter()
                        try:
                            ok = _sample(pass_binding, record, edition.run_id)
                        except KeyboardInterrupt:
                            ok, stop, error = False, True, 'cancelled'
                        except Exception:
                            ok = False
                        elapsed = (perf_counter() - start) * 1000
                        if not math.isfinite(elapsed) or elapsed < 0:
                            raise ValueError('invalid_timing_clock')
                        try:
                            attempts = read_attempt_metadata(pass_binding) if arm != 'regex' else ()
                            missing = arm != 'regex' and not attempts
                        except Exception:
                            attempts, missing = (), True
                        physical = sum(a.physical_may_have_started for a in attempts)
                        attempted = arm == 'regex' or physical > 0 or missing
                        sample = {'arm': arm, 'pass': pass_index, 'ordinal': ordinal,
                                  'length': len(record.log.message), 'duration_ms': elapsed, 'ok': ok and attempted,
                                  'attempted': attempted, 'physical_attempts_N': physical,
                                  'retry_attempts_N': sum(a.ordinal == 2 for a in attempts),
                                  'metadata_missing': missing,
                                  'attempts': [a.model_dump(mode='json') for a in attempts]}
                        samples.append(sample)
                        with (destination / 'samples.jsonl').open('ab') as handle:
                            handle.write(canonical({'phase': 'terminal', **sample}) + b'\n')
                            handle.flush()
                            os.fsync(handle.fileno())
                        if stop:
                            break
                    if stop:
                        break
        except KeyboardInterrupt:
            stop, error = True, 'cancelled'
        except Exception:
            error = 'timing_failed'
            stop = True
        row = {'arm': arm, 'status': ('not_measured' if not any(s['attempted'] for s in samples) else
                 'measured' if len(samples) == len(inference) * 3 and all(s['ok'] and not s['metadata_missing'] for s in samples)
                 else 'measured_incomplete'), 'error_code': error,
               'execution_kind': 'network_frontier' if arm == 'frontier' else 'offline_local',
               'cold_kind': 'client_initialization' if arm == 'frontier' else 'import_and_model_load',
               'cold_startup_ms': cold_ms, **_statistics(samples, len(inference) * 3),
               'passes': [_statistics([s for s in samples if s['pass'] == index], len(inference))
                          for index in range(3)], 'length_slices': []}
        for length in plan.length_slices:
            intended = 3 * sum(length.minimum <= len(r.log.message) <= length.maximum for r in inference)
            row['length_slices'].append({'minimum': length.minimum, 'maximum': length.maximum,
                **_statistics([s for s in samples if length.minimum <= s['length'] <= length.maximum], intended)})
        result['arms'].append(row)
    with (destination / 'timing-result.json').open('xb') as handle:
        handle.write(canonical(result))
        handle.flush()
        os.fsync(handle.fileno())
    return result


__all__ = ['HardwareContext', 'LengthSlice', 'TimingPlan', 'TimingWorker', 'run_timing']
