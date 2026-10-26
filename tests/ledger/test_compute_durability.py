"""Measured local time survives reopen/reconciliation; it never becomes invoice cash."""

import pytest

from m7.ledger import BudgetExceeded, ReservationLedger


def test_cancelled_unknown_liability_keeps_compute_when_receipt_arrives(tmp_path):
    # what_bug_this_catches: later cash evidence must not erase measured compute
    # or let an unresolved cancelled reservation free the spending cap.
    path = tmp_path / "m7-compute.sqlite3"
    ledger = ReservationLedger(path, cap_micros=10, authorization_id="m7-auth")
    ledger.initialize()
    ledger.reserve("m7-attempt", 7, category="inference")
    ledger.reconcile("m7-attempt", actual_micros=None, state="cancelled", compute_seconds=1.25)
    restarted = ReservationLedger(path, cap_micros=10, authorization_id="m7-auth")
    before = restarted.summary()
    assert before["remaining_micros"] == 3
    assert before["by_category"]["inference"]["known_compute_seconds"] == 1.25
    with pytest.raises(BudgetExceeded):
        restarted.reserve("m7-next", 4, category="retry")
    restarted.reconcile("m7-attempt", actual_micros=0, state="cancelled", receipt_id="m7-zero-cash")
    after = ReservationLedger(path, cap_micros=10, authorization_id="m7-auth").summary()
    assert after["by_category"]["inference"]["known_compute_seconds"] == 1.25
    assert after["states"]["cancelled"] == 1
    assert after["remaining_micros"] == 10
    assert after["known_provider_cash_micros"] == 0
    assert after["economic_total"] is None


def test_conflicting_terminal_compute_cannot_rewrite_durable_evidence(tmp_path):
    ledger = ReservationLedger(tmp_path / "m7-conflict.sqlite3", cap_micros=10, authorization_id="m7-auth")
    ledger.initialize()
    ledger.reserve("m7-attempt", 7, category="failed_trial")
    ledger.reconcile("m7-attempt", actual_micros=None, state="failed", compute_seconds=2.5)
    with pytest.raises(ValueError, match="terminal_state_conflict"):
        ledger.reconcile("m7-attempt", actual_micros=None, state="failed", compute_seconds=0.0)
    assert ledger.summary()["by_category"]["failed_trial"]["known_compute_seconds"] == 2.5
