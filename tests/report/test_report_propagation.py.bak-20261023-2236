"""Runner aggregate -> public projection -> static HTML report (W6 -> W7).

Each assertion checks the reader-visible interpretation in the rendered HTML, not
a schema round trip. Hand derivations use the literals in scenario.py
(NAME 13 code points on rec-001, EMAIL 21 on rec-002, 34 gold code points total).
Row shapes follow render_report: coverage columns are corpus, eligible, attempted,
answered, error, unattempted, publication_suppressed; quality columns are
precision, recall, f1, tp, fp, fn, support.
"""
from m7.experiment.result import public_aggregate
from m7.publish import gate_record, render_report, write_locked_artifacts
from m7.render import render

from .scenario import (EMAIL_VALUE, GOLD, MESSAGES, NAME_VALUE, bundle, mixed_cells, prediction, record,
                       records, regex_only_cells)

NM = '<td>not measured</td>'
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


def test_null_metrics_and_empty_class_render_as_not_measured_never_zero():
    document = html()
    # PHONE has no gold or predictions: 0/0 ratios; integer counts stay 0.
    assert ('<tr><th>regex</th><td>total</td><td>PHONE</td>' + NM * 3 + cells(0, 0, 0, 0) + '</tr>') in document
    # Macro is undefined while any class is undefined; it has no counts either.
    assert '<tr><th>regex</th><td>total</td><td>macro</td>' + NM * 7 + '</tr>' in document
    # No benign-only records exist: 0/0 overredaction rate.
    assert '<tr><th>regex</th><td>benign_record_overredaction</td>' + NM + cells(0, 0) + '</tr>' in document
    assert 'Null and absent values mean not measured, never zero.' in document


def test_unrun_arm_renders_not_measured_and_keeps_its_records():
    document = html(regex_only_cells())
    # frontier never attempted: attempted 0, answered 0, error 0, unattempted 2.
    assert '<tr><th>frontier</th><td>not_measured</td>' + cells(2, 2, 0, 0, 0, 2, 0) + '</tr>' in document
    assert '<tr><th>frontier</th><td>total</td><td>NAME</td>' + NM * 7 + '</tr>' in document


def test_arm_losing_to_regex_is_shown_with_no_deployment():
    document = html()
    # regex NAME: tp 1 -> precision 1/1, recall 1/1, f1 2/2.
    assert '<tr><th>regex</th><td>total</td><td>NAME</td>' + cells(1.0, 1.0, 1.0, 1, 0, 0, 1) + '</tr>' in document
    # finetuned NAME: tp 0, fp 0, fn 1 -> precision 0/0 null, recall 0/1 = 0.0, f1 0/1 = 0.0.
    assert ('<tr><th>finetuned</th><td>total</td><td>NAME</td>' + NM + cells(0.0, 0.0, 0, 0, 1, 1)
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
    assert ('<tr><th>finetuned</th><td>total</td><td>NAME</td>' + NM + cells(0.0, 0.0, 0, 0, 1, 1)
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
