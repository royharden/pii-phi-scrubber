"""Locked fictional-log engineering targets; never a production privacy claim."""
from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from m7.contracts import Boundary, Digest, Label

LABELS = ('NAME', 'EMAIL', 'PHONE', 'ACCOUNT_ID')
Fraction = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ClassFloor(Boundary):
    label: Label
    recall_minimum: Fraction
    precision_minimum: Fraction
    recall_lower95_minimum: Fraction


class AdoptionPolicy(Boundary):
    schema_version: Literal['AdoptionPolicy/v1'] = 'AdoptionPolicy/v1'
    # No defaults fabricate a dev-justified approved numerical target.
    per_class: tuple[ClassFloor, ...]
    development_justification_sha256: Digest
    zero_structure_failures: Literal[True] = True
    full_intended_accounting: Literal[True] = True
    positive_paired_f1_lower_bound: Literal[True] = True
    no_increased_residual_rate: Literal[True] = True

    @model_validator(mode='after')
    def all_classes(self) -> AdoptionPolicy:
        if tuple(row.label for row in self.per_class) != LABELS:
            raise ValueError('all_four_ordered_class_floors_required')
        return self


def _finite(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _fraction(ratio) -> dict:
    """Numerator/denominator/null reason of a scorer ratio, for N/A display only."""
    ratio = ratio if isinstance(ratio, dict) else {}
    counts = {key: ratio.get(key) if type(ratio.get(key)) is int and ratio.get(key) >= 0 else None
              for key in ('numerator', 'denominator')}
    reason = ratio.get('null_reason')
    return {**counts, 'null_reason': reason if reason in ('zero_denominator', 'undefined_class') else None}


def adoption_report(bundle: dict, policy: AdoptionPolicy) -> dict:
    arms = {row['arm']: row for row in bundle['arms']}
    fine, base = arms['finetuned'], arms['base']
    metrics = fine.get('metrics') or {}
    intervals = fine.get('intervals') or {}
    per_class = []
    for floor in policy.per_class:
        quality = metrics.get('per_class', {}).get(floor.label, {})
        uncertainty = intervals.get('per_class', {}).get(floor.label, {}).get('recall', {})
        recall = _finite(quality.get('recall', {}).get('value'))
        precision = _finite(quality.get('precision', {}).get('value'))
        bounds = uncertainty.get('interval')
        lower = _finite(bounds[0]) if isinstance(bounds, list) and len(bounds) == 2 else None
        recall_parts, precision_parts = _fraction(quality.get('recall')), _fraction(quality.get('precision'))
        values = (recall, precision, lower)
        passed = (all(v is not None for v in values) and recall >= floor.recall_minimum
                  and precision >= floor.precision_minimum and lower >= floor.recall_lower95_minimum)
        per_class.append({'label': floor.label, 'recall': recall, 'precision': precision,
                          'recall_lower95': lower, 'recall_floor': floor.recall_minimum,
                          'precision_floor': floor.precision_minimum,
                          'recall_lower95_floor': floor.recall_lower95_minimum,
                          'recall_numerator': recall_parts['numerator'],
                          'recall_denominator': recall_parts['denominator'],
                          'recall_null_reason': recall_parts['null_reason'],
                          'precision_numerator': precision_parts['numerator'],
                          'precision_denominator': precision_parts['denominator'],
                          'precision_null_reason': precision_parts['null_reason'],
                          'passed': passed if all(v is not None for v in values) else None})
    paired = bundle.get('paired_fine_minus_base') or {}
    ci = paired.get('interval')
    lower = _finite(ci[0]) if isinstance(ci, list) and len(ci) == 2 else None
    leak_fine = _finite(metrics.get('residual_sensitive_codepoints', {}).get('value'))
    leak_base = _finite((base.get('metrics') or {}).get('residual_sensitive_codepoints', {}).get('value'))
    n = bundle['corpus_N']
    cost = bundle.get('cost') or {}
    gates = {
        'all_classes_meet_total_set_floors': (all(row['passed'] is True for row in per_class)
                                             if all(row['passed'] is not None for row in per_class) else None),
        'positive_paired_macro_f1': lower > 0 if lower is not None else None,
        'no_increased_residual_leak': leak_fine <= leak_base if leak_fine is not None and leak_base is not None else None,
        'zero_structure_failures': metrics.get('structure_failures') == 0 if metrics else None,
        'full_intended_accounting': all(row['attempted_N'] + row['unattempted_N'] == n
                                       and row['answered_N'] + row['error_N'] == row['attempted_N']
                                       for row in arms.values()),
        'all_four_arms_attempted_full_population': all(row['attempted_N'] == n and row.get('pending_N', 0) == 0
                                                     for row in arms.values()),
        'closed_edition': bundle.get('edition_state') == 'closed',
        'attempt_lineage_complete': all(row.get('attempt_metadata_missing_N', 0) == 0
                                        and row.get('interrupted_unknown_N', 0) == 0 for row in arms.values()),
        'cost_reconciled': cost.get('status') == 'known' and cost.get('unknown_attempts') == 0
                           and cost.get('over_cap') is False and cost.get('scope_complete') is True
                           and cost.get('currency') is not None,
    }
    all_unrun = all(row['measurement_status'] == 'not_measured' for row in arms.values())
    passed = all(value is True for value in gates.values())
    # Even passing this scientific/engineering rule does not issue product acceptance.
    return {'status': 'not_evaluated' if all_unrun else 'candidate_only' if passed else 'no_deploy',
            'recommendation': 'candidate_for_independent_review' if passed else 'retain_benchmark_no_deployment',
            'policy_scope': 'total_test_set_only', 'per_class': per_class, 'gates': gates,
            'paired_macro_f1_lower95': lower, 'fine_residual_rate': leak_fine,
            'base_residual_rate': leak_base, 'improvement_supported': passed,
            'product_acceptance': False}


__all__ = ['AdoptionPolicy', 'ClassFloor', 'adoption_report']
