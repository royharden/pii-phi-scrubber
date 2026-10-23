"""Fail-closed projection for aggregate JSON; never serialize an arbitrary bundle."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Callable

from .models import ARMS
from .costing import CATEGORIES, STATES, COUNT_KEYS

_COUNTS = ('corpus_N', 'eligible_N', 'attempted_N', 'answered_N', 'error_N', 'unattempted_N',
           'pending_N', 'budget_rejected_N', 'adapter_unavailable_N', 'interrupted_unknown_N',
           'cancelled_N', 'render_failed_N', 'publication_suppressed_N')
_COUNTS += ('preflight_rejected_N', 'physical_attempts_N', 'retry_attempts_N', 'attempt_metadata_missing_N')
_QUALITY = ('tp', 'fp', 'fn', 'support', 'predicted_count', 'precision', 'recall', 'f1')
_HARMS = ('residual_sensitive_codepoints', 'records_with_residual', 'benign_codepoints_redacted',
          'benign_record_overredaction', 'unavailable', 'unsafe_or_unavailable', 'structure_failures')
_NULL_REASONS = {'zero_denominator', 'undefined_class'}


def _numeric(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('non_numeric_aggregate')
    return value


def _ratio(value):
    if not isinstance(value, dict):
        return None
    result = {key: _numeric(value.get(key)) for key in
              ('value', 'numerator', 'denominator', 'defined_classes', 'class_count') if key in value}
    reason = value.get('null_reason')
    if reason is not None and reason not in _NULL_REASONS:
        raise ValueError('unknown_metric_null_reason')
    result['null_reason'] = reason
    return result


def _quality(value):
    value = value if isinstance(value, dict) else {}
    return {key: _ratio(value[key]) if isinstance(value.get(key), dict)
            else _numeric(value.get(key)) for key in _QUALITY}


def _metrics(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('invalid_metric_shape')
    per_class = value.get('per_class', {})
    result = {'per_class': {label: _quality(per_class.get(label)) for label in
                            ('NAME', 'EMAIL', 'PHONE', 'ACCOUNT_ID')},
              'micro': _quality(value.get('micro')), 'macro': _quality(value.get('macro'))}
    result.update({key: _numeric(value.get(key)) for key in ('corpus_N', 'eligible_N', 'answered_N', 'error_N')})
    for key in _HARMS:
        result[key] = _ratio(value[key]) if isinstance(value.get(key), dict) else _numeric(value.get(key))
    return result


def _interval(value):
    if value is None:
        return None
    if not isinstance(value, dict) or value.get('method') != 'paired_group_percentile' or value.get('level') != .95:
        raise ValueError('invalid_interval_method')
    output = {'method': 'paired_group_percentile', 'level': .95}
    for key in ('draws', 'seed', 'effective_blocks', 'executed_draws', 'valid_draws', 'undefined_draws'):
        number = value.get(key)
        if type(number) is not int or number < 0:
            raise ValueError('invalid_draw_counter')
        output[key] = number
    if (output['draws'] != 2000 or output['valid_draws'] + output['undefined_draws'] != output['executed_draws']
            or output['executed_draws'] not in (0, 2000)):
        raise ValueError('draw_accounting_mismatch')
    reason = value.get('null_reason')
    if reason not in (None, 'insufficient_units', 'insufficient_valid_draws'):
        raise ValueError('unknown_interval_null_reason')
    bounds = value.get('interval')
    if bounds is not None:
        if not isinstance(bounds, list) or len(bounds) != 2 or output['valid_draws'] < 1800 or output['effective_blocks'] < 20:
            raise ValueError('unsupported_interval_claim')
        bounds = [_numeric(v) for v in bounds]
        if None in bounds or bounds[0] > bounds[1] or reason is not None:
            raise ValueError('invalid_interval_bounds')
    digest = value.get('draw_digest')
    if digest is not None and (not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None):
        raise ValueError('invalid_draw_digest')
    output.update(interval=bounds, null_reason=reason, draw_digest=digest)
    return output


def _intervals(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('invalid_interval_shape')
    output = {'per_class': {label: {metric: _interval(value.get('per_class', {}).get(label, {}).get(metric))
                                   for metric in ('precision', 'recall', 'f1')}
                            for label in ('NAME', 'EMAIL', 'PHONE', 'ACCOUNT_ID')}}
    for group in ('micro', 'macro'):
        output[group] = {metric: _interval(value.get(group, {}).get(metric)) for metric in ('precision', 'recall', 'f1')}
    for key in _HARMS[:-1]:
        output[key] = _interval(value.get(key))
    output['macro_f1'] = _interval(value.get('macro_f1'))
    return output


def _cost_projection(cost):
    if cost is None:
        return None
    if cost.get('status') not in ('unknown', 'known', 'partially_known', 'not_measured'):
        raise ValueError('invalid_cost_status')
    keys = ('attempts_N', 'known_provider_cash_micros', 'provider_cash_total_micros',
            'unresolved_liability_micros', 'unknown_attempts', 'cap_micros', 'remaining_micros',
            'electricity_micros', 'hardware_amortization_micros', 'compute_seconds', 'economic_total_micros')
    output = {key: _numeric(cost.get(key)) for key in keys}
    output.update(status=cost['status'], over_cap=cost.get('over_cap') if type(cost.get('over_cap')) is bool else None,
                  scope_complete=cost.get('scope_complete') is True)
    currency = cost.get('currency')
    output['currency'] = currency if isinstance(currency, str) and re.fullmatch('[A-Z]{3}', currency) else None
    output['economic_null_reason'] = None if output['economic_total_micros'] is not None else 'unmeasured_or_unreconciled'
    output['by_category'] = ({c: {k: _numeric(cost['by_category'].get(c, {}).get(k)) for k in COUNT_KEYS}
                              for c in CATEGORIES} if isinstance(cost.get('by_category'), dict) else None)
    output['states'] = ({s: _numeric(cost['states'].get(s)) for s in STATES}
                        if isinstance(cost.get('states'), dict) else None)
    return output


def _adoption(value):
    if not isinstance(value, dict) or value.get('status') not in ('not_evaluated', 'candidate_only', 'no_deploy'):
        raise ValueError('invalid_adoption_status')
    output = {'status': value['status'], 'policy_scope': 'total_test_set_only',
              'recommendation': 'candidate_for_independent_review' if value['status'] == 'candidate_only'
              else 'retain_benchmark_no_deployment', 'product_acceptance': False,
              'improvement_supported': value.get('improvement_supported') is True,
              'per_class': [], 'gates': {}}
    supplied = value.get('per_class', [])
    if tuple(row.get('label') for row in supplied) != ('NAME', 'EMAIL', 'PHONE', 'ACCOUNT_ID'):
        raise ValueError('adoption_class_targets_required')
    for row in supplied:
        output['per_class'].append({'label': row['label'], 'passed': row.get('passed') if type(row.get('passed')) is bool else None,
            **{key: _numeric(row.get(key)) for key in ('recall', 'precision', 'recall_lower95',
               'recall_floor', 'precision_floor', 'recall_lower95_floor')}})
    for key in ('all_classes_meet_total_set_floors', 'positive_paired_macro_f1', 'no_increased_residual_leak',
                'zero_structure_failures', 'full_intended_accounting', 'all_four_arms_attempted_full_population',
                'closed_edition', 'cost_reconciled', 'attempt_lineage_complete'):
        output['gates'][key] = value.get('gates', {}).get(key) if type(value.get('gates', {}).get(key)) is bool else None
    for key in ('paired_macro_f1_lower95', 'fine_residual_rate', 'base_residual_rate'):
        output[key] = _numeric(value.get(key))
    if output['status'] == 'candidate_only' and not all(v is True for v in output['gates'].values()):
        raise ValueError('inconsistent_adoption_claim')
    return output


def _timing(value):
    if value is None:
        return None
    from .timing import HardwareContext
    hardware = HardwareContext.model_validate_json(json.dumps(value.get('hardware'), allow_nan=False))
    output = {'schema_version': 'TimingResult/v1', 'passes': 3, 'concurrency': 1,
              'hardware': hardware.model_dump(mode='json'), 'arms': [], 'gold_safety_scoring_included': False,
              'safety_scoring_overhead_ms': _numeric(value.get('safety_scoring_overhead_ms'))}
    for key in ('plan_sha256', 'edition_sha256'):
        digest = value.get(key)
        if not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None:
            raise ValueError('invalid_timing_commitment')
        output[key] = digest
    if value.get('passes') != 3 or value.get('concurrency') != 1:
        raise ValueError('invalid_timing_protocol')
    keys = ('intended_samples_N', 'attempted_samples_N', 'answered_samples_N', 'failed_samples_N',
            'logical_calls_N', 'physical_attempts_N', 'retry_attempts_N', 'attempt_metadata_missing_N',
            'unattempted_samples_N', 'all_attempt_p50_ms', 'all_attempt_p95_ms',
            'successful_only_p50_ms', 'successful_only_p95_ms', 'elapsed_detector_seconds',
            'attempts_per_second', 'answered_per_second')
    def numbers(row):
        return {key: _numeric(row.get(key)) for key in keys}
    rows = value.get('arms', [])
    if tuple(row.get('arm') for row in rows) != ARMS:
        raise ValueError('all_four_timing_arms_required')
    for row in rows:
        if row.get('status') not in ('measured', 'not_measured', 'measured_incomplete'):
            raise ValueError('invalid_timing_status')
        if row.get('error_code') not in (None, 'adapter_unavailable', 'cancelled', 'timing_failed'):
            raise ValueError('invalid_timing_error')
        item = {'arm': row['arm'], 'status': row['status'], 'error_code': row.get('error_code'),
                'execution_kind': 'network_frontier' if row['arm'] == 'frontier' else 'offline_local',
                'cold_kind': 'client_initialization' if row['arm'] == 'frontier' else 'import_and_model_load',
                'cold_startup_ms': _numeric(row.get('cold_startup_ms')), **numbers(row)}
        item['passes'] = [numbers(p) for p in row.get('passes', [])]
        if len(item['passes']) != 3:
            raise ValueError('three_timing_passes_required')
        item['length_slices'] = [{**numbers(s), 'minimum': _numeric(s.get('minimum')), 'maximum': _numeric(s.get('maximum'))}
                                 for s in row.get('length_slices', [])]
        output['arms'].append(item)
    return output


def public_aggregate(bundle: dict) -> dict:
    """Closed field projection. Source-bearing keys/strings are not copied."""
    if bundle.get('schema_version') != 'EvaluationBundle/v2':
        raise ValueError('locked_result_schema_required')
    output = {'schema_version': 'EvaluationBundle/v2', 'evidence_kind': 'locked_edition_execution',
              'product_acceptance': False, 'publication': [], 'timing': None,
              'paired_fine_minus_base': None}
    for key in ('edition_sha256', 'corpus_digest'):
        digest = bundle.get(key)
        if not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None:
            raise ValueError('invalid_result_commitment')
        output[key] = digest
    if bundle.get('edition_state') not in ('closed', 'open_incomplete'):
        raise ValueError('invalid_edition_state')
    output['edition_state'] = bundle['edition_state']
    output['corpus_N'] = _numeric(bundle.get('corpus_N'))
    cost = bundle.get('cost')
    output['cost'] = _cost_projection(cost)
    output['timing'] = _timing(bundle.get('timing'))
    output['adoption'] = _adoption(bundle.get('adoption'))
    output['safety_scoring_overhead_ms'] = _numeric(bundle.get('safety_scoring_overhead_ms'))
    output['paired'] = {scope: _intervals(bundle.get('paired', {}).get(scope)) for scope in ('total', 'normal', 'challenge')}
    output['paired_fine_minus_base'] = _interval(bundle.get('paired_fine_minus_base'))
    supplied = bundle.get('arms')
    if not isinstance(supplied, list) or tuple(row.get('arm') for row in supplied) != ARMS:
        raise ValueError('all_four_result_arms_required')
    rows = []
    for item in supplied:
        if item.get('measurement_status') not in ('measured', 'measured_incomplete', 'not_measured'):
            raise ValueError('invalid_measurement_status')
        reason = item.get('reason')
        if reason not in (None, 'no_attempts', 'incomplete_population'):
            raise ValueError('invalid_measurement_reason')
        row = {key: _numeric(item.get(key)) for key in _COUNTS}
        row.update(arm=item['arm'], measurement_status=item['measurement_status'], reason=reason,
                   metrics=_metrics(item.get('metrics')), successful_only=_metrics(item.get('successful_only')),
                   intervals=_intervals(item.get('intervals')), timing=None,
                   cost={'status': 'unknown'})
        arm_cost = item.get('cost') or {}
        if arm_cost.get('status') not in ('unknown', 'known', 'partially_known', 'not_measured'):
            raise ValueError('invalid_arm_cost_status')
        row['cost'] = {'status': arm_cost['status'], **{key: _numeric(arm_cost.get(key)) for key in
            ('known_provider_cash_micros', 'provider_cash_total_micros', 'unresolved_liability_micros',
             'unknown_attempts', 'training_allocation_micros', 'economic_total_micros')}}
        slices = item.get('slices', {})
        row['slices'] = {name: _metrics(slices.get(name)) for name in ('normal', 'challenge')}
        row['slice_intervals'] = {name: _intervals(item.get('slice_intervals', {}).get(name)) for name in ('normal', 'challenge')}
        if (row['corpus_N'] != output['corpus_N']
                or any(type(row[k]) is not int or row[k] < 0 for k in _COUNTS)
                or row['attempted_N'] + row['unattempted_N'] != row['corpus_N']
                or row['answered_N'] + row['error_N'] != row['attempted_N']):
            raise ValueError('result_denominator_mismatch')
        if row['measurement_status'] == 'not_measured' and row['metrics'] is not None:
            raise ValueError('unrun_metric_forbidden')
        rows.append(row)
    output['arms'] = rows
    return output


def write_aggregate_result(bundle: dict, destination: str | Path, *,
                           approve_artifact: Callable[[str], bool]) -> None:
    projected = public_aggregate(bundle)
    document = json.dumps(projected, allow_nan=False, sort_keys=True, separators=(',', ':')) + '\n'
    if approve_artifact(document) is not True:
        raise ValueError('assembled_artifact_not_approved')
    with Path(destination).open('x', encoding='utf-8') as handle:
        handle.write(document)


__all__ = ['public_aggregate', 'write_aggregate_result']
