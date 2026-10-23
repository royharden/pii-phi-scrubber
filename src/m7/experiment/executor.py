"""Future authorized four-arm executor; inert until explicitly called by a host.

The trusted evaluator owns gold. Adapter callables receive a standalone LogRecord
only; a production custodian must enforce that boundary with OS/process isolation.
No retries here: the D6 attempt controller owns the single transient retry budget.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Mapping
from time import perf_counter

from m7.contracts import LogRecord, Prediction, validate_prediction
from m7.eval import Observation, score
from m7.eval.bootstrap import metric_intervals
from m7.ledger import BudgetExceeded
from m7.publish.gate import gate_record
from m7.render import render

from .journal import AttemptSummary, CellResult, EditionJournal
from .models import ARMS, ArmPin, CustodyGold, LockedEdition, check_channels, commitment
from .adoption import adoption_report
from .costing import EconomicAllocation, cost_report


@dataclass(frozen=True)
class AdapterBinding:
    """Host binds verified D6 configuration to its committed edition pin."""
    pin: ArmPin
    predict: Callable[[LogRecord], Prediction]
    preflight: Callable[[tuple[LogRecord, ...]], None]
    attempt_metadata: Callable[[], tuple[object, ...]] | None = None


def read_attempt_metadata(binding: AdapterBinding) -> tuple[AttemptSummary, ...]:
    """Closed shared projection used by quality and timing journal writers."""
    metadata = (binding.attempt_metadata() if binding.attempt_metadata is not None
                else getattr(binding.predict, 'last_attempts', ()))
    if len(metadata) > 2:
        raise ValueError('retry_cap_metadata')
    fields = tuple(AttemptSummary.model_fields)
    return tuple(AttemptSummary.model_validate({key: item.get(key) if isinstance(item, dict) else getattr(item, key)
                                                for key in fields}) for item in metadata)


def _cell(edition: LockedEdition, arm: str, record: LogRecord,
          binding: AdapterBinding) -> CellResult:
    outcome = 'backend_failure'
    prediction = None
    attempted = True
    attempts = ()
    metadata_missing = False
    try:
        # The detached wire contains no bundle, gold, block, family or slice.
        detached = LogRecord.model_validate(record.model_dump(mode='python'))
        candidate = binding.predict(detached)
        if not isinstance(candidate, Prediction):
            raise ValueError('prediction_wire_required')
        # model_copy can bypass Pydantic validators; revalidate the complete wire.
        candidate = Prediction.model_validate_json(candidate.model_dump_json())
        if (candidate.run_id != edition.run_id or candidate.arm != arm
                or candidate.model_id != binding.pin.model_id
                or candidate.record_id != record.record_id
                or candidate.content_sha256 != record.content_sha256):
            outcome = 'invalid_output'
        else:
            prediction = validate_prediction(record, candidate)
            outcome = ('answered' if prediction.status == 'ok' else
                       'cancelled' if prediction.status == 'cancelled' else
                       'invalid_output' if prediction.status == 'invalid_output' else
                       'backend_failure')
    except BudgetExceeded:
        # Controller promises this exception is raised before a billable request.
        attempted, outcome = False, 'budget_rejected'
    except KeyboardInterrupt:
        # Could have reached a provider. Its reservation stays unresolved.
        outcome = 'cancelled'
    except Exception:
        # Never inspect/stringify provider or validation exception bodies.
        outcome = 'backend_failure'
    if arm != 'regex':
        try:
            attempts = read_attempt_metadata(binding)
            metadata_missing = not attempts and attempted
            if attempts and not any(item.physical_may_have_started for item in attempts):
                attempted = False
                outcome = ('budget_rejected' if outcome == 'budget_rejected' else
                           'cancelled_before_start' if outcome == 'cancelled' else 'preflight_rejected')
                prediction = None
            elif not attempts and outcome == 'cancelled':
                if prediction is not None and prediction.attempt_id == 'before-start':
                    # D6's explicit cooperative cancellation marker is produced
                    # before reservation/operation; it is not a measured model call.
                    attempted, outcome, prediction, metadata_missing = False, 'cancelled_before_start', None, False
                else:
                    metadata_missing = True
        except Exception:
            attempts, metadata_missing = (), True
    return CellResult(arm=arm, record_id=record.record_id,
                      content_sha256=record.content_sha256, attempted=attempted,
                      outcome=outcome, prediction=prediction, attempts=attempts,
                      attempt_metadata_missing=metadata_missing)


def execute_edition(edition: LockedEdition, inference: tuple[LogRecord, ...],
                    gold_channel: tuple[CustodyGold, ...],
                    registry: Mapping[str, AdapterBinding], journal: EditionJournal, *,
                    authorize: Callable[[LockedEdition, bool], None],
                    cancelled: Callable[[], bool] = lambda: False,
                    cost_summary: Callable[[], dict] | None = None,
                    economic_allocation: EconomicAllocation | None = None,
                    verify_receipt: Callable[[str, str], bool] | None = None,
                    authorize_preflight: Callable[[LockedEdition, bool], None] | None = None) -> dict:
    """Open once, then resume only cells that have never begun.

    `authorize` must authenticate current custody/lock/license/resource receipts and
    revocation for the exact edition before ANY adapter preflight. No default permit.
    `preflight` must check every input against actual tokenizer/context limits without
    inference. A shared corpus incompatibility blocks the whole edition before open.
    Absence of an arm is measured as unavailable; it is never replaced by a mock.
    An uncertain started call is terminal on resume, to prevent invisible reruns.
    """
    check_channels(edition, inference, gold_channel)
    if economic_allocation is not None:
        if (verify_receipt is None
                or verify_receipt('economic_allocation', commitment(economic_allocation.model_dump(mode='json'))) is not True
                or verify_receipt('economic_allocation_source', economic_allocation.receipt_sha256) is not True):
            raise ValueError('economic_allocation_receipt_not_authenticated')
    if set(registry) - set(ARMS):
        raise ValueError('unknown_adapter_arm')
    records = {record.record_id: record for record in inference}
    pins = {pin.arm: pin for pin in edition.arm_pins}
    for arm, binding in registry.items():
        if binding.pin != pins[arm] or not callable(binding.predict) or not callable(binding.preflight):
            raise ValueError('adapter_pin_mismatch')
    with journal.writer():
        edition.require_current()
        # Sealing commits only public metadata and record/message commitments.
        journal.seal(edition)
        if journal.closed:
            authorize(edition, True)
            return aggregate_edition(edition, inference, gold_channel, journal.terminals(),
                                     closed=True, cost=_cost(cost_summary, economic_allocation))
        # D4's open is consumed once. Hosts provide a nonconsuming current release
        # check for preflight, then the consuming evaluation_gate only after it.
        (authorize_preflight or authorize)(edition, journal.opened)
        for binding in registry.values():
            binding.preflight(inference)
        if authorize_preflight is not None:
            authorize(edition, journal.opened)
        if not journal.opened:
            journal.append({'kind': 'opened'})
        # A prior begin may have caused real billing. Do not retry/release it.
        for arm, record_id in journal.abandoned():
            record = records[record_id]
            journal.append({'kind': 'terminal', 'result': CellResult(
                arm=arm, record_id=record_id, content_sha256=record.content_sha256,
                attempted=True, outcome='interrupted_unknown', attempt_metadata_missing=True).model_dump(mode='json')})
        terminal = journal.terminals()
        stop = False
        for member in edition.population:
            record = records[member.record_id]
            for arm in ARMS:
                if (arm, record.record_id) in terminal:
                    continue
                if cancelled():
                    stop = True
                    break
                # Expiry/revocation is also checked before each new logical call.
                edition.require_current()
                authorize(edition, True)
                binding = registry.get(arm)
                if binding is None:
                    cell = CellResult(arm=arm, record_id=record.record_id,
                                      content_sha256=record.content_sha256,
                                      attempted=False, outcome='adapter_unavailable')
                else:
                    journal.append({'kind': 'begin', 'arm': arm, 'record_id': record.record_id})
                    cell = _cell(edition, arm, record, binding)
                journal.append({'kind': 'terminal', 'result': cell.model_dump(mode='json')})
                terminal[(arm, record.record_id)] = cell
                if cell.outcome == 'cancelled':
                    stop = True
                    break
            if stop:
                break
        if len(terminal) == len(edition.population) * len(ARMS):
            journal.append({'kind': 'closed'})
        return aggregate_edition(edition, inference, gold_channel, terminal,
                                 closed=journal.closed, cost=_cost(cost_summary, economic_allocation))


def _cost(supplier: Callable[[], dict] | None, allocation: EconomicAllocation | None = None) -> dict | None:
    if supplier is None:
        return None
    try:
        # Complete reconciled categories/states; arbitrary source strings omitted.
        return cost_report(supplier(), allocation)
    except Exception:
        return None


def aggregate_edition(edition: LockedEdition, inference: tuple[LogRecord, ...],
                      gold_channel: tuple[CustodyGold, ...],
                      cells: Mapping[tuple[str, str], CellResult], *,
                      closed: bool, cost: dict | None = None) -> dict:
    """Gold-aware scoring in evaluator memory; persist only numeric aggregates.

    No held-out source, gold spans, predicted spans, block IDs, prompts, completions
    or rendered messages enter the result. Journal predictions remain private.
    """
    check_channels(edition, inference, gold_channel)
    profiling_started = perf_counter()
    records = {record.record_id: record for record in inference}
    gold = {row.record_id: row for row in gold_channel}
    n = len(edition.population)
    bundle = {'schema_version': 'EvaluationBundle/v2', 'evidence_kind': 'locked_edition_execution',
              'edition_sha256': edition.sha256, 'corpus_N': n,
              'corpus_digest': commitment([row.model_dump(mode='json') for row in edition.population]),
              'edition_state': 'closed' if closed else 'open_incomplete',
              'arms': [], 'publication': [], 'paired_fine_minus_base': None,
              'cost': cost if cost is not None else cost_report(None),
              'timing': None, 'product_acceptance': False}
    measured_observations = {}
    for arm in ARMS:
        observations = []
        counts: Counter = Counter()
        suppressed = 0
        for member in edition.population:
            record, truth = records[member.record_id], gold[member.record_id]
            cell = cells.get((arm, member.record_id))
            prediction = cell.prediction if cell is not None else None
            available = prediction is not None and prediction.status == 'ok'
            structure = False
            if cell is not None:
                counts[cell.outcome] += 1
                counts['attempted'] += cell.attempted
                counts['physical_attempts'] += sum(item.physical_may_have_started for item in cell.attempts)
                counts['attempt_metadata_missing'] += cell.attempt_metadata_missing
                counts['retry_attempts'] += sum(item.ordinal == 2 for item in cell.attempts)
                for item in cell.attempts:
                    if item.reservation_micros is not None:
                        counts['reserved_attempts'] += 1
                        if item.actual_micros is None:
                            counts['unknown_cash_attempts'] += 1
                            counts['cash_liability'] += item.reservation_micros
                    if item.actual_micros is not None:
                        counts['cash_receipts'] += 1
                        counts['known_cash'] += item.actual_micros
            else:
                counts['pending'] += 1
            if available:
                try:
                    rendering = render(record, prediction)
                    structure = rendering.schema_valid and rendering.safe_log is not None
                    # Gate even though only aggregate cards are exported. A fault
                    # never changes detector spans or repairs upstream quality.
                    approved = gate_record(record, truth.spans, rendering).approved
                except Exception:
                    approved = False
                suppressed += not approved
            counts['answered'] += available and structure
            counts['render_failed'] += available and not structure
            observations.append(Observation(record.record_id, truth.block_id, truth.slice_name,
                                            len(record.log.message), truth.spans,
                                            prediction.spans if available else (), available, structure))
        attempted, answered = counts['attempted'], counts['answered']
        measured = attempted > 0
        row = {
            'arm': arm, 'measurement_status': ('not_measured' if not measured else
                'measured' if answered == n else 'measured_incomplete'),
            'reason': ('no_attempts' if not measured else None if answered == n else 'incomplete_population'),
            'corpus_N': n, 'eligible_N': n, 'attempted_N': attempted,
            'answered_N': answered, 'error_N': attempted - answered,
            'unattempted_N': n - attempted, 'pending_N': counts['pending'],
            'budget_rejected_N': counts['budget_rejected'],
            'adapter_unavailable_N': counts['adapter_unavailable'],
            'interrupted_unknown_N': counts['interrupted_unknown'],
            'cancelled_N': counts['cancelled'] + counts['cancelled_before_start'],
            'preflight_rejected_N': counts['preflight_rejected'],
            'physical_attempts_N': counts['physical_attempts'], 'retry_attempts_N': counts['retry_attempts'],
            'attempt_metadata_missing_N': counts['attempt_metadata_missing'],
            'render_failed_N': counts['render_failed'],
            'publication_suppressed_N': suppressed, 'metrics': score(observations) if measured else None,
            'successful_only': score([r for r in observations if r.available and r.structure_valid]) if measured else None,
            'slices': {name: score([r for r in observations if r.slice_name == name]) if measured else None
                       for name in ('normal', 'challenge')},
            'intervals': metric_intervals(observations, seed=edition.bootstrap_seed) if measured else None,
            'slice_intervals': {name: metric_intervals([r for r in observations if r.slice_name == name],
                                                      seed=edition.bootstrap_seed) if measured else None
                                for name in ('normal', 'challenge')}, 'timing': None,
            'cost': {'status': 'not_measured' if not measured else
                     'unknown' if counts['attempt_metadata_missing'] or not counts['reserved_attempts'] else
                     'partially_known' if counts['unknown_cash_attempts'] else 'known',
                     'known_provider_cash_micros': counts['known_cash'] if counts['cash_receipts'] else None,
                     'provider_cash_total_micros': counts['known_cash'] if counts['reserved_attempts']
                         and not counts['unknown_cash_attempts'] and not counts['attempt_metadata_missing'] else None,
                     'unresolved_liability_micros': counts['cash_liability'] if counts['reserved_attempts'] else None,
                     'unknown_attempts': counts['unknown_cash_attempts'] if counts['reserved_attempts'] else None,
                     'training_allocation_micros': None, 'economic_total_micros': None},
        }
        bundle['arms'].append(row)
        if measured:
            measured_observations[arm] = observations
    bundle['paired'] = {scope: None for scope in ('total', 'normal', 'challenge')}
    if 'base' in measured_observations and 'finetuned' in measured_observations:
        fine, base = measured_observations['finetuned'], measured_observations['base']
        for scope in ('total', 'normal', 'challenge'):
            left = fine if scope == 'total' else [r for r in fine if r.slice_name == scope]
            right = base if scope == 'total' else [r for r in base if r.slice_name == scope]
            bundle['paired'][scope] = metric_intervals(left, right, seed=edition.bootstrap_seed)
        bundle['paired_fine_minus_base'] = bundle['paired']['total']['macro_f1']
        bundle['paired_fine_minus_base_slices'] = {
            scope: bundle['paired'][scope]['macro_f1'] for scope in ('normal', 'challenge')}
    bundle['adoption'] = adoption_report(bundle, edition.adoption_policy)
    # This measures evaluator render/gate/scoring/uncertainty assembly overhead on
    # this invocation, not model latency or stable benchmark performance.
    bundle['safety_scoring_overhead_ms'] = (perf_counter() - profiling_started) * 1000
    return bundle


__all__ = ['AdapterBinding', 'aggregate_edition', 'execute_edition']
