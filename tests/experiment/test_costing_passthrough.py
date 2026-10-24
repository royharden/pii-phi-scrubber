"""cost_report carries ledger amount sources and compute time without turning time into cost.

Summaries are hand-built in the ReservationLedger.summary shape. Expected numbers are
summed by hand in the comments.
"""
import pytest

from m7.experiment.costing import cost_report, merge_cost_authorizations

CATEGORIES = ('training', 'inference', 'retry', 'failed_trial')


def category(attempts=0, cash=0, liability=0, unknown=0, seconds=None, unknown_seconds=None):
    row = {'attempts_N': attempts, 'known_provider_cash_micros': cash, 'unresolved_liability_micros': liability,
           'unknown_attempts': unknown, 'known_usage_units': 0, 'unknown_usage_attempts': 0}
    if seconds is not None:
        row.update(known_compute_seconds=seconds, unknown_compute_attempts=unknown_seconds)
    return row


def summary(authorization_id='auth-1', *, with_compute=True, sources=None):
    """Training: 2 attempts, both actual receipts (300 cash), 10.0 compute seconds.
    Inference: 2 attempts, 1 actual (100 cash) + 1 estimated (50 liability, no compute time), 1.5 s.
    Totals: 4 attempts, cash 400, liability 50, 1 unknown; remaining 1000 - 400 - 50 = 550."""
    compute = {'training': (10.0, 0), 'inference': (1.5, 1), 'retry': (0.0, 0), 'failed_trial': (0.0, 0)}
    counts = {'training': (2, 300, 0, 0), 'inference': (2, 100, 50, 1), 'retry': (0, 0, 0, 0),
              'failed_trial': (0, 0, 0, 0)}
    rows = {c: category(*counts[c], *(compute[c] if with_compute else (None, None))) for c in CATEGORIES}
    result = {'authorization_id': authorization_id, 'cap_micros': 1000, 'known_provider_cash_micros': 400,
              'unresolved_liability_micros': 50, 'unknown_attempts': 1, 'remaining_micros': 550,
              'attempts_N': 4, 'currency': 'USD', 'by_category': rows,
              'states': {'reserved': 0, 'succeeded': 3, 'failed': 0, 'cancelled': 0, 'unknown': 1}}
    if sources is not False:
        result['amount_sources'] = sources or {'estimated': 1, 'actual': 3}
    return result


def test_sources_and_compute_pass_through_without_a_cost_figure():
    report = cost_report(summary())
    assert report['amount_sources'] == {'estimated': 1, 'actual': 3}
    # 10.0 + 1.5 + 0 + 0 = 11.5 known seconds; 1 attempt without compute time.
    assert (report['known_compute_seconds'], report['unknown_compute_attempts']) == (11.5, 1)
    assert report['by_category']['inference']['known_compute_seconds'] == 1.5
    # One unknown attempt: partially known, and time never fills the cost gap.
    assert report['status'] == 'partially_known'
    assert (report['provider_cash_total_micros'], report['economic_total_micros']) == (None, None)


def test_old_summaries_without_the_new_fields_still_reconcile():
    report = cost_report(summary(with_compute=False, sources=False))
    assert (report['amount_sources'], report['known_compute_seconds'], report['unknown_compute_attempts']) == (
        None, None, None)
    assert report['known_provider_cash_micros'] == 400


def test_amount_sources_must_cover_every_attempt():
    # 1 + 2 = 3 sources for 4 attempts.
    with pytest.raises(ValueError, match='amount_source_denominator_mismatch'):
        cost_report(summary(sources={'estimated': 1, 'actual': 2}))


def test_invalid_compute_time_is_refused():
    bad = summary()
    bad['by_category']['training']['known_compute_seconds'] = float('nan')
    with pytest.raises(ValueError, match='invalid_compute_seconds'):
        cost_report(bad)
    more = summary()
    # 3 attempts without compute time in a category with only 2 attempts.
    more['by_category']['inference']['unknown_compute_attempts'] = 3
    with pytest.raises(ValueError, match='compute_attempt_count_mismatch'):
        cost_report(more)


def test_merge_sums_sources_and_compute_only_when_every_ledger_reports_them():
    combined = cost_report(merge_cost_authorizations((summary('auth-1'), summary('auth-2')), currency='USD'))
    # Two identical ledgers: sources 2 + 6, seconds 2 x 11.5 = 23.0, unknown compute 2.
    assert combined['amount_sources'] == {'estimated': 2, 'actual': 6}
    assert (combined['known_compute_seconds'], combined['unknown_compute_attempts']) == (23.0, 2)
    partial = cost_report(merge_cost_authorizations(
        (summary('auth-1'), summary('auth-2', with_compute=False, sources=False)), currency='USD'))
    assert (partial['amount_sources'], partial['known_compute_seconds']) == (None, None)
