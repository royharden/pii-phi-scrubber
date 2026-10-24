"""Runner aggregate -> public projection -> static HTML report (W6 -> W7).

Each assertion checks the reader-visible interpretation in the rendered HTML, not
a schema round trip. Hand derivations use the literals in scenario.py
(NAME 13 code points on rec-001, EMAIL 21 on rec-002, 34 gold code points total).
Row shapes follow render_report: coverage columns are corpus, eligible, attempted,
answered, error, unattempted, publication_suppressed; quality columns are
precision, recall, f1, tp, fp, fn, support.
"""
import copy
import json

import pytest

from m7.contracts import Span, make_record
from m7.experiment.costing import cost_report
from m7.experiment.executor import aggregate_edition
from m7.experiment.journal import AttemptSummary, CellResult
from m7.experiment.result import public_aggregate
from m7.publish import gate_record, render_report, write_locked_artifacts
from m7.render import render

from .scenario import (EMAIL_VALUE, GOLD, MESSAGES, NAME_SPAN, NAME_VALUE, arm, bundle, edition, gold_channel,
                       mixed_cells, prediction, record, records, regex_only_cells)

NM = '<td>not measured</td>'
# Plan: a zero denominator is N/A with numerator/denominator, distinct from never-run cells.
NA = '<td>N/A (0/0)</td>'
INSUFFICIENT = 'insufficient: fewer than 20 effective blocks'


def html(cells=None, decisions=()):
    return render_report(public_aggregate(bundle(cells or mixed_cells())), decisions=decisions)


def cells(*values) -> str:
    return ''.join(f'<td>{value}</td>' for value in values)


def test_partially_failed_arm_shows_failures_inside_full_denominator():
    document = html()
    # frontier: corpus 2, eligible 2, attempted 2, answered 1, error 1, unattempted 0, suppressed 0.
    assert '<tr><th>frontier</th><td>measured_incomplete</td>' + cells(2, 2, 2, 1, 1, 0, 0) + '</tr>' in document
    # The unavailable record's 21 EMAIL code points stay residual: 21 of 34.
    assert ('<tr><th>frontier</th><td>residual_sensitive_codepoints</td>'
            + cells(21 / 34, 21, 34) + '</tr>') in document


def test_zero_denominator_and_empty_class_render_as_na_never_zero():
    document = html()
    # PHONE has no gold or predictions: precision 0/(0+0), recall 0/(0+0), f1 0/(0+0+0).
    assert ('<tr><th>regex</th><td>total</td><td>PHONE</td>' + NA * 3 + cells(0, 0, 0, 0) + '</tr>') in document
    # Macro needs all four classes; regex defines NAME and EMAIL only (2 of 4). Macro has no counts.
    assert ('<tr><th>regex</th><td>total</td><td>macro</td>' + '<td>N/A (2/4 classes defined)</td>' * 3
            + NM * 4 + '</tr>') in document
    # No benign-only records exist: overredaction rate 0/0.
    assert '<tr><th>regex</th><td>benign_record_overredaction</td>' + NA + cells(0, 0) + '</tr>' in document
    # Successful-only diagnostics (both regex records answered) use the same wording.
    assert '<tr><th>regex</th><th>macro</th>' + '<td>N/A (2/4 classes defined)</td>' * 3 + '</tr>' in document
    assert 'Not measured marks a value that is unavailable' in document


def test_unrun_arm_renders_not_measured_and_keeps_its_records():
    document = html(regex_only_cells())
    # frontier never attempted: attempted 0, answered 0, error 0, unattempted 2.
    assert '<tr><th>frontier</th><td>not_measured</td>' + cells(2, 2, 0, 0, 0, 2, 0) + '</tr>' in document
    assert '<tr><th>frontier</th><td>total</td><td>NAME</td>' + NM * 7 + '</tr>' in document


def test_arm_losing_to_regex_is_shown_with_no_deployment():
    document = html()
    # regex NAME: tp 1 -> precision 1/1, recall 1/1, f1 2/2.
    assert '<tr><th>regex</th><td>total</td><td>NAME</td>' + cells(1.0, 1.0, 1.0, 1, 0, 0, 1) + '</tr>' in document
    # finetuned NAME: tp 0, fp 0, fn 1 -> precision 0/0 = N/A, recall 0/1 = 0.0, f1 0/1 = 0.0.
    assert ('<tr><th>finetuned</th><td>total</td><td>NAME</td>' + NA + cells(0.0, 0.0, 0, 0, 1, 1)
            + '</tr>') in document
    assert 'Retain the benchmark and recommend no deployment' in document
    assert 'Candidate for independent review.' not in document
    assert 'Negative results and failures are valid outcomes.' in document


def test_unknown_cost_is_unknown_and_blocks_cost_claims():
    document = html()
    assert '<p>Cost status: unknown.</p>' in document
    assert 'no total or per-record cost claim is made' in document
    assert '<tr><th>economic_total_micros</th>' + NM + '</tr>' in document
    assert '<tr><th>provider_cash_total_micros</th>' + NM + '</tr>' in document
    assert 'Currency: unknown.' in document and 'Authorization overrun: unknown.' in document
    # Per-arm rows name the status instead of looking like a measured blank.
    assert '<tr><th>regex</th><th>unknown</th>' + NM in document
    assert '<tr><th>cost_reconciled</th><td>failed</td></tr>' in document


def test_known_status_without_reconciliation_still_blocks_cost_claims():
    projection = public_aggregate(bundle(mixed_cells()))
    # Status 'known' with zero unknown attempts, but training/inference scope incomplete.
    projection['cost'].update(status='known', unknown_attempts=0, over_cap=False, currency='USD',
                              scope_complete=False)
    document = render_report(projection)
    assert '<p>Cost status: known.</p>' in document
    assert 'no total or per-record cost claim is made' in document
    # Fully reconciled: the disclaimer disappears.
    projection['cost']['scope_complete'] = True
    assert 'no total or per-record cost claim is made' not in render_report(projection)


def test_insufficient_cluster_count_says_insufficient_instead_of_an_interval():
    document = html()
    # 2 blocks, 0 valid draws, no bounds.
    assert ('<tr><th>finetuned macro F1</th>' + cells(2, 0) + NM * 2
            + f'<td>{INSUFFICIENT}</td></tr>') in document
    assert ('<tr><th>finetuned minus base macro F1</th>' + cells(2, 0) + NM * 2
            + f'<td>{INSUFFICIENT}</td></tr>') in document
    # Locked table: blocks 2, executed 0, valid 0, undefined 0, no bounds.
    assert ('<tr><th>finetuned</th><th>total</th><th>macro</th><th>f1</th>' + cells(2, 0, 0, 0) + NM * 2
            + f'<td>{INSUFFICIENT}</td></tr>') in document
    # Undefined adoption gates read "not evaluated", never "passed".
    assert '<tr><th>positive_paired_macro_f1</th><td>not evaluated</td></tr>' in document


def test_leaked_record_is_suppressed_from_report_but_still_scored():
    leaked = render(record('rec-001'), prediction('finetuned', 'rec-001'))
    decision = gate_record(record('rec-001'), GOLD['rec-001'], leaked)
    assert (decision.approved, decision.reason, decision.safe_message) == (False, 'gold_coverage_incomplete', None)
    document = html(decisions=(decision,))
    assert '<h3>Output suppressed</h3>' in document
    assert NAME_VALUE not in document and 'Quandt' not in document
    # Suppression is counted (finetuned suppressed 1) but the record stays answered
    # with no error, and the NAME miss is still scored (fn 1).
    assert '<tr><th>finetuned</th><td>measured</td>' + cells(2, 2, 2, 2, 0, 0, 1) + '</tr>' in document
    assert ('<tr><th>finetuned</th><td>total</td><td>NAME</td>' + NA + cells(0.0, 0.0, 0, 0, 1, 1)
            + '</tr>') in document


def test_approved_card_shows_only_placeholders():
    clean = render(record('rec-001'), prediction('regex', 'rec-001', GOLD['rec-001']))
    decision = gate_record(record('rec-001'), GOLD['rec-001'], clean)
    # 'user ' + '[NAME_1]' + ' signed in'
    assert decision.safe_message == 'user [NAME_1] signed in'
    assert '<pre>user [NAME_1] signed in</pre>' in html(decisions=(decision,))


def test_published_artifacts_carry_no_message_or_gold_text(tmp_path):
    sources = tuple((row, GOLD[row.record_id]) for row in records())
    status = write_locked_artifacts(bundle(mixed_cells()), tmp_path / 'out', sources=sources)
    assert status == {'status': 'published_safe_artifacts', 'product_acceptance': False}
    for name in ('aggregate.json', 'index.html'):
        text = (tmp_path / 'out' / name).read_text(encoding='utf-8')
        for value in (*MESSAGES.values(), NAME_VALUE, EMAIL_VALUE, 'mirela', 'Quandt'):
            assert value not in text
    assert '<p>Cost status: unknown.</p>' in (tmp_path / 'out' / 'index.html').read_text(encoding='utf-8')


def attempt(attempt_id, reservation, actual):
    """One physical attempt; actual None means the billed amount is still unknown."""
    return AttemptSummary(attempt_id=attempt_id, ordinal=1, status='ok' if actual is not None else 'failed',
                          error_code=None if actual is not None else 'backend_failure', duration_ms=1.0,
                          input_tokens=None, output_tokens=None, reservation_micros=reservation,
                          actual_micros=actual, liability_status='known' if actual is not None else 'unknown',
                          retry_reason=None, physical_may_have_started=True)


def zeros():
    return {key: 0 for key in ('attempts_N', 'known_provider_cash_micros', 'unresolved_liability_micros',
                               'unknown_attempts', 'known_usage_units', 'unknown_usage_attempts')}


# Campaign ledger: 3 inference attempts, 2 succeeded with 200 known cash, 1 unknown
# holding a 50 liability. Remaining = 1000 - 200 - 50 = 750; 250 <= 1000 so no overrun.
PARTIAL_SUMMARY = {
    'cap_micros': 1000, 'known_provider_cash_micros': 200, 'unresolved_liability_micros': 50,
    'unknown_attempts': 1, 'remaining_micros': 750, 'attempts_N': 3, 'currency': 'USD',
    'by_category': {'training': zeros(), 'retry': zeros(), 'failed_trial': zeros(),
                    'inference': {**zeros(), 'attempts_N': 3, 'known_provider_cash_micros': 200,
                                  'unresolved_liability_micros': 50, 'unknown_attempts': 1}},
    'states': {'reserved': 0, 'succeeded': 2, 'failed': 0, 'cancelled': 0, 'unknown': 1}}


def test_partially_known_cost_stays_partial_and_blocks_cost_claims():
    grid = mixed_cells()
    # frontier: rec-001 billed 80 of a 100 reservation; rec-002 failed with its 100 still unresolved.
    grid[('frontier', 'rec-001')] = CellResult(
        arm='frontier', record_id='rec-001', content_sha256=record('rec-001').content_sha256, attempted=True,
        outcome='answered', prediction=prediction('frontier', 'rec-001', (NAME_SPAN,)),
        attempts=(attempt('f-1', 100, 80),))
    grid[('frontier', 'rec-002')] = CellResult(
        arm='frontier', record_id='rec-002', content_sha256=record('rec-002').content_sha256, attempted=True,
        outcome='backend_failure', attempts=(attempt('f-2', 100, None),))
    raw = aggregate_edition(edition(), records(), gold_channel(), grid, closed=True,
                            cost=cost_report(PARTIAL_SUMMARY))
    document = render_report(public_aggregate(raw))
    assert '<p>Cost status: partially_known.</p>' in document
    assert 'no total or per-record cost claim is made' in document
    assert '<tr><th>known_provider_cash_micros</th><td>200</td></tr>' in document
    assert '<tr><th>unresolved_liability_micros</th><td>50</td></tr>' in document
    assert '<tr><th>remaining_micros</th><td>750</td></tr>' in document
    # A partial ledger never gets a provider cash total.
    assert '<tr><th>provider_cash_total_micros</th>' + NM + '</tr>' in document
    assert 'Authorization overrun: no.' in document
    # Per-arm: known cash 80, no total, liability 100, 1 unknown attempt, no allocation or economic total.
    assert ('<tr><th>frontier</th><th>partially_known</th>' + cells(80) + NM + cells(100, 1) + NM * 2
            + '</tr>') in document
    assert '<tr><th>cost_reconciled</th><td>failed</td></tr>' in document


def test_collision_with_report_text_suppresses_the_whole_artifact_set(tmp_path):
    # Fictional source whose NAME coincides with fixed report text.
    # 'user ' = 5; 'Locked-edition accounting' = 14 + 1 + 10 = 25 -> NAME [5, 30).
    source = make_record('user Locked-edition accounting signed in', 'rec-collide')
    sources = ((source, (Span(start=5, end=30, label='NAME'),)),)
    raw = bundle(mixed_cells())
    status = write_locked_artifacts(raw, tmp_path / 'out', sources=sources)
    assert status == {'status': 'artifacts_suppressed', 'product_acceptance': False}
    aggregate = json.loads((tmp_path / 'out' / 'aggregate.json').read_text(encoding='utf-8'))
    assert aggregate == {'schema_version': 'ArtifactSuppressed/v1', 'status': 'suppressed',
                         'reason': 'assembled_value_detected', 'artifact_assembly_failures_N': 1}
    index = (tmp_path / 'out' / 'index.html').read_text(encoding='utf-8')
    assert '<h1>Output suppressed</h1>' in index and 'Locked-edition accounting' not in index
    # Upstream measurements are not changed by suppression.
    assert arm(raw, 'base')['publication_suppressed_N'] == 2
    assert arm(raw, 'finetuned')['metrics']['per_class']['NAME']['fn'] == 1


def test_unsafe_suppression_card_writes_nothing(tmp_path):
    # 'Gold-aware' is fixed text in BOTH the main report Limits paragraph and the
    # suppression card, so the first scan rejects the report and the second the card.
    # 'user ' = 5; 'Gold-aware' = 4 + 1 + 5 = 10 -> NAME [5, 15).
    source = make_record('user Gold-aware here', 'rec-card')
    sources = ((source, (Span(start=5, end=15, label='NAME'),)),)
    with pytest.raises(ValueError, match='suppression_card_not_safe_to_publish'):
        write_locked_artifacts(bundle(mixed_cells()), tmp_path / 'out', sources=sources)
    assert not (tmp_path / 'out').exists()

def test_adoption_floor_table_shows_fractions_for_undefined_metrics():
    document = html()
    # finetuned NAME: precision 0/(0+0) -> N/A (0/0); recall 0/1 = 0.0; recall lower bound has no
    # interval (2 blocks) -> not measured. Floors from scenario.policy(): 0.5, 0.5, 0.4.
    assert ('<tr><th>NAME</th><td>N/A (0/0)</td><td>0.5</td><td>0.0</td><td>0.5</td>' + NM
            + '<td>0.4</td></tr>') in document
    # PHONE: no gold or predictions -> precision and recall both 0/0.
    assert ('<tr><th>PHONE</th><td>N/A (0/0)</td><td>0.5</td><td>N/A (0/0)</td><td>0.5</td>' + NM
            + '<td>0.4</td></tr>') in document


def test_amount_sources_and_compute_time_reach_the_report_without_a_cost_figure():
    summary = copy.deepcopy(PARTIAL_SUMMARY)
    # 3 attempts: 2 with receipt amounts (actual), 1 still at its reservation (estimated).
    summary['amount_sources'] = {'estimated': 1, 'actual': 2}
    for category in summary['by_category'].values():
        category.update(known_compute_seconds=0.0, unknown_compute_attempts=0)
    # Inference: 4.5 seconds recorded on two attempts; the third has none.
    summary['by_category']['inference'].update(known_compute_seconds=4.5, unknown_compute_attempts=1)
    raw = aggregate_edition(edition(), records(), gold_channel(), mixed_cells(), closed=True,
                            cost=cost_report(summary))
    document = render_report(public_aggregate(raw))
    assert ('Attempt amounts from authenticated receipts (actual): 2; reservation estimates still held '
            'as liability (estimated): 1.') in document
    assert 'Known compute seconds: 4.5; attempts without compute time: 1.' in document
    assert 'no cost figure is derived from it' in document
    # Compute time never turns into an economic or total cost.
    assert '<tr><th>economic_total_micros</th>' + NM + '</tr>' in document
    assert '<tr><th>provider_cash_total_micros</th>' + NM + '</tr>' in document


def test_ledger_without_sources_or_compute_reports_them_unknown():
    document = html()
    assert ('Attempt amounts from authenticated receipts (actual): not measured; reservation estimates '
            'still held as liability (estimated): not measured.') in document
    assert 'Known compute seconds: not measured; attempts without compute time: not measured.' in document