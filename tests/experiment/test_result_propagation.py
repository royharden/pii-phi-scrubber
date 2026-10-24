"""Runner aggregate -> closed public projection (W6 result schema).

Expected values come from the literals documented in scenario.py:
gold NAME [5,18) = 13 code points on rec-001, EMAIL [8,29) = 21 on rec-002, 34 total.
Message lengths: rec-001 5+13+10 = 28 (benign 15), rec-002 8+21+4 = 33 (benign 12); benign 27.
"""
import copy
import json

import pytest

from m7.experiment.result import public_aggregate

from .scenario import EMAIL_VALUE, MESSAGES, NAME_VALUE, arm, bundle, mixed_cells, regex_only_cells


def projected(cells=None):
    return public_aggregate(bundle(cells or mixed_cells()))


def test_partially_failed_arm_keeps_full_denominator():
    frontier = arm(projected(), 'frontier')
    # rec-001 answered, rec-002 backend failure: attempted 2, answered 1, error 1, nothing dropped.
    assert (frontier['corpus_N'], frontier['attempted_N'], frontier['answered_N'],
            frontier['error_N'], frontier['unattempted_N']) == (2, 2, 1, 1, 0)
    assert (frontier['measurement_status'], frontier['reason']) == ('measured_incomplete', 'incomplete_population')
    metrics = frontier['metrics']
    # The failed record still contributes its gold: EMAIL tp 0, fn 1; recall 0/1.
    assert (metrics['per_class']['EMAIL']['fn'], metrics['per_class']['EMAIL']['recall']['value']) == (1, 0.0)
    # Unavailable record leaves its 21 EMAIL code points residual: 21 of 34.
    assert (metrics['residual_sensitive_codepoints']['numerator'],
            metrics['residual_sensitive_codepoints']['denominator']) == (21, 34)
    assert (metrics['unavailable']['numerator'], metrics['unavailable']['denominator']) == (1, 2)


def test_empty_class_and_zero_denominators_stay_null_not_zero():
    regex = arm(projected(), 'regex')['metrics']
    phone = regex['per_class']['PHONE']
    # No PHONE gold or predictions: tp=fp=fn=0, so 0/0 for precision, recall and f1.
    for metric in ('precision', 'recall', 'f1'):
        assert phone[metric]['value'] is None
        assert phone[metric]['null_reason'] == 'zero_denominator'
    assert (phone['tp'], phone['fp'], phone['fn'], phone['support']) == (0, 0, 0, 0)
    # Macro needs all four classes; only NAME and EMAIL are defined (2 of 4).
    assert regex['macro']['f1']['value'] is None
    assert regex['macro']['f1']['null_reason'] == 'undefined_class'
    assert (regex['macro']['f1']['defined_classes'], regex['macro']['f1']['class_count']) == (2, 4)
    # Every record holds gold, so there are no benign-only records: 0/0, not 0%.
    assert regex['benign_record_overredaction']['value'] is None
    # A measured zero stays a real zero: base predicts nothing, NAME recall 0/1 = 0.0.
    assert arm(projected(), 'base')['metrics']['per_class']['NAME']['recall']['value'] == 0.0


def test_unrun_arm_has_null_metrics_not_zeros():
    frontier = arm(projected(regex_only_cells()), 'frontier')
    assert (frontier['measurement_status'], frontier['reason']) == ('not_measured', 'no_attempts')
    assert frontier['metrics'] is None and frontier['intervals'] is None
    # Both records stay in the denominator as unattempted, adapter unavailable.
    assert (frontier['attempted_N'], frontier['unattempted_N'], frontier['adapter_unavailable_N']) == (0, 2, 2)
    assert frontier['cost']['status'] == 'not_measured'


def test_negative_finding_is_retained():
    result = projected()
    regex, fine = arm(result, 'regex')['metrics'], arm(result, 'finetuned')['metrics']
    # regex NAME 1/1; finetuned misses the only NAME: recall 0/1.
    assert regex['per_class']['NAME']['recall']['value'] == 1.0
    assert fine['per_class']['NAME']['recall']['value'] == 0.0
    assert result['adoption']['status'] == 'no_deploy'
    assert result['adoption']['improvement_supported'] is False


def test_publication_suppression_is_counted_without_rescoring():
    result = projected()
    # Renders that keep annotated gold: base both records, finetuned rec-001 only.
    suppressed = {name: arm(result, name)['publication_suppressed_N']
                  for name in ('regex', 'frontier', 'base', 'finetuned')}
    assert suppressed == {'regex': 0, 'frontier': 0, 'base': 2, 'finetuned': 1}
    fine = arm(result, 'finetuned')
    # Suppression is not an error and does not repair the miss.
    assert (fine['answered_N'], fine['error_N']) == (2, 0)
    assert (fine['metrics']['per_class']['NAME']['tp'], fine['metrics']['per_class']['NAME']['fn']) == (0, 1)
    assert (fine['metrics']['residual_sensitive_codepoints']['numerator'],
            fine['metrics']['residual_sensitive_codepoints']['denominator']) == (13, 34)


def test_unknown_cost_stays_unknown():
    result = projected()
    cost = result['cost']
    assert cost['status'] == 'unknown'
    assert cost['economic_total_micros'] is None and cost['provider_cash_total_micros'] is None
    assert cost['economic_null_reason'] == 'unmeasured_or_unreconciled'
    # No attempt receipts were supplied for any arm.
    assert {arm(result, name)['cost']['status'] for name in ('regex', 'frontier', 'base', 'finetuned')} == {'unknown'}
    assert result['adoption']['gates']['cost_reconciled'] is False


def test_insufficient_cluster_count_has_no_interval():
    result = projected()
    macro = arm(result, 'finetuned')['intervals']['macro_f1']
    # 2 provenance blocks < 20: no draws are executed and no interval exists.
    assert (macro['effective_blocks'], macro['executed_draws'], macro['interval'], macro['null_reason']) == (
        2, 0, None, 'insufficient_units')
    paired = result['paired_fine_minus_base']
    assert (paired['interval'], paired['null_reason']) == (None, 'insufficient_units')
    # Each slice holds one block.
    assert arm(result, 'regex')['slice_intervals']['normal']['macro_f1']['effective_blocks'] == 1


def test_interval_cannot_be_claimed_with_too_few_blocks():
    raw = bundle(mixed_cells())
    tampered = copy.deepcopy(raw)
    arm(tampered, 'regex')['intervals']['macro_f1'].update(interval=[0.1, 0.2], null_reason=None)
    with pytest.raises(ValueError, match='unsupported_interval_claim'):
        public_aggregate(tampered)


def test_projection_refuses_shrunk_denominator_and_unrun_metrics():
    raw = bundle(mixed_cells())
    dropped = copy.deepcopy(raw)
    # Hiding the failed frontier record: attempted 1 + unattempted 0 != corpus 2.
    arm(dropped, 'frontier').update(attempted_N=1, error_N=0)
    with pytest.raises(ValueError, match='result_denominator_mismatch'):
        public_aggregate(dropped)
    unrun = copy.deepcopy(raw)
    arm(unrun, 'base')['measurement_status'] = 'not_measured'
    with pytest.raises(ValueError, match='unrun_metric_forbidden'):
        public_aggregate(unrun)


def test_aggregate_json_carries_no_source_or_gold_text():
    document = json.dumps(projected(), sort_keys=True)
    for text in (*MESSAGES.values(), NAME_VALUE, EMAIL_VALUE, 'Quandt', 'example.test'):
        assert text not in document


def test_planted_source_text_is_dropped_or_refused():
    raw = bundle(mixed_cells())
    planted = copy.deepcopy(raw)
    # Unknown keys at bundle, arm and metric level are not copied by the closed projection.
    planted['debug_message'] = MESSAGES['rec-001']
    arm(planted, 'finetuned')['example'] = NAME_VALUE
    arm(planted, 'finetuned')['metrics']['per_class']['NAME']['quote'] = NAME_VALUE
    document = json.dumps(public_aggregate(planted), sort_keys=True)
    assert NAME_VALUE not in document and MESSAGES['rec-001'] not in document
    # A source string in an enum slot is refused rather than copied.
    as_reason = copy.deepcopy(raw)
    arm(as_reason, 'frontier')['reason'] = NAME_VALUE
    with pytest.raises(ValueError, match='invalid_measurement_reason'):
        public_aggregate(as_reason)
    as_count = copy.deepcopy(raw)
    arm(as_count, 'frontier')['error_N'] = EMAIL_VALUE
    with pytest.raises(ValueError, match='non_numeric_aggregate'):
        public_aggregate(as_count)
