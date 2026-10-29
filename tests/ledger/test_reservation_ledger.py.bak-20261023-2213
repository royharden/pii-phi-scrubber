"""Atomic cost cap: reserve before attempt, race refusal, retained liability.

Plan (cost ledger): shared atomic reservation; no new paid attempt when the
remaining authorization cannot cover its worst case; cancellation retains
receipts and outstanding reservations rather than refunding blindly; unresolved
amounts stay unknown. Uses a throwaway SQLite file under pytest's tmp_path.
"""
import threading

import pytest

from m7.ledger import BudgetExceeded, ReservationLedger

CAP = 100  # micros


def ledger(tmp_path, cap=CAP):
    led = ReservationLedger(tmp_path / "cost.sqlite3", cap_micros=cap, authorization_id="auth-1")
    led.initialize()
    return led


def test_reconcile_requires_prior_reservation(tmp_path):
    led = ledger(tmp_path)
    with pytest.raises(ValueError, match="unknown_attempt"):
        led.reconcile("never-reserved", actual_micros=0, state="succeeded", receipt_id="rcpt-1")


def test_reservations_that_fit_alone_but_not_together_second_refused(tmp_path):
    led = ledger(tmp_path)
    led.reserve("a1", 60, category="inference")
    # 60 + 60 = 120 > 100 -> refused even though 60 <= 100 on its own.
    with pytest.raises(BudgetExceeded):
        led.reserve("a2", 60, category="inference")
    # 60 + 40 = 100 <= 100 -> exactly fits.
    led.reserve("a3", 40, category="inference")
    s = led.summary()
    assert s["unresolved_liability_micros"] == 100 and s["remaining_micros"] == 0
    assert s["attempts_N"] == 2 and s["over_cap"] is False
    # Cap fully committed: even a 1-micro reservation is refused.
    with pytest.raises(BudgetExceeded):
        led.reserve("a4", 1, category="retry")


def test_concurrent_reservations_race_only_one_wins(tmp_path):
    first = ledger(tmp_path)
    second = ReservationLedger(tmp_path / "cost.sqlite3", cap_micros=CAP, authorization_id="auth-1")
    barrier = threading.Barrier(2)
    outcomes = {}

    def attempt(led, attempt_id):
        barrier.wait()
        try:
            led.reserve(attempt_id, 60, category="training")
            outcomes[attempt_id] = "reserved"
        except BudgetExceeded:
            outcomes[attempt_id] = "refused"

    threads = [threading.Thread(target=attempt, args=(first, "t1")),
               threading.Thread(target=attempt, args=(second, "t2"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(outcomes.values()) == ["refused", "reserved"]
    # Exactly one 60-micro liability exists; never 120.
    assert first.summary()["unresolved_liability_micros"] == 60


def test_cancellation_retains_outstanding_reservation_as_unknown_liability(tmp_path):
    led = ledger(tmp_path)
    led.reserve("c1", 60, category="training")
    led.reconcile("c1", actual_micros=None, state="cancelled")
    s = led.summary()
    # Not refunded: 60 still counts against the cap, cost unknown, nothing claimed as known cash.
    assert s["unresolved_liability_micros"] == 60
    assert s["known_provider_cash_micros"] == 0
    assert s["unknown_attempts"] == 1 and s["remaining_micros"] == 40
    assert s["states"]["cancelled"] == 1
    assert s["by_category"]["training"]["unresolved_liability_micros"] == 60
    # 60 retained + 50 = 110 > 100 -> refused; a released-as-zero bug would allow it.
    with pytest.raises(BudgetExceeded):
        led.reserve("c2", 50, category="training")


def test_unknown_cost_propagates_as_unknown_not_zero(tmp_path):
    led = ledger(tmp_path)
    led.reserve("u1", 30, category="inference")
    led.reconcile("u1", actual_micros=None, state="unknown")
    led.reserve("k1", 20, category="inference")
    led.reconcile("k1", actual_micros=15, state="succeeded", usage_units=7, receipt_id="rcpt-k1")
    s = led.summary()
    # Known cash 15 (k1 actual); unresolved 30 (u1 reservation); remaining 100 - 15 - 30 = 55.
    assert (s["known_provider_cash_micros"], s["unresolved_liability_micros"], s["remaining_micros"]) == (15, 30, 55)
    assert s["economic_total"] is None and s["economic_null_reason"]
    inf = s["by_category"]["inference"]
    assert inf["unknown_attempts"] == 1
    # u1 has no usage units -> counted as unknown usage, not as 0 units silently summed.
    assert inf["known_usage_units"] == 7 and inf["unknown_usage_attempts"] == 1


def test_actual_cost_requires_receipt_and_overrun_is_recorded(tmp_path):
    led = ledger(tmp_path)
    led.reserve("o1", 60, category="inference")
    with pytest.raises(ValueError):
        led.reconcile("o1", actual_micros=10, state="succeeded")  # no receipt id
    led.reconcile("o1", actual_micros=120, state="succeeded", receipt_id="rcpt-o1")
    s = led.summary()
    # Overrun is honest: known 120 > cap 100, remaining clamps to 0, over_cap flagged.
    assert s["known_provider_cash_micros"] == 120 and s["over_cap"] is True and s["remaining_micros"] == 0
    with pytest.raises(BudgetExceeded):
        led.reserve("o2", 1, category="retry")  # 120 + 1 > 100


def test_idempotent_reserve_and_conflicts(tmp_path):
    led = ledger(tmp_path)
    led.reserve("i1", 50, category="inference")
    led.reserve("i1", 50, category="inference")  # replay: same key/amount -> no second liability
    assert led.summary()["unresolved_liability_micros"] == 50
    with pytest.raises(ValueError, match="idempotency_conflict"):
        led.reserve("i1", 40, category="inference")
    led.reconcile("i1", actual_micros=45, state="succeeded", receipt_id="rcpt-i1")
    with pytest.raises(ValueError, match="receipt_conflict"):
        led.reconcile("i1", actual_micros=10, state="succeeded", receipt_id="rcpt-i1")


def test_invalid_inputs_refused(tmp_path):
    with pytest.raises(ValueError):
        ReservationLedger(tmp_path / "x.sqlite3", cap_micros=-1, authorization_id="auth-1")
    led = ledger(tmp_path)
    with pytest.raises(ValueError):
        led.reserve("f1", 1.5, category="inference")  # float money refused
    with pytest.raises(ValueError):
        led.reserve("f1", 10, category="gift")
    other = ReservationLedger(tmp_path / "cost.sqlite3", cap_micros=500, authorization_id="auth-1")
    with pytest.raises(ValueError, match="authorization_mismatch"):
        other.reserve("f2", 10, category="inference")  # cannot widen the cap on the same store
