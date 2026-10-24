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


# R2: terminal outcomes, amount source and compute-time proxy.

def test_failed_or_cancelled_outcome_cannot_be_rewritten_as_success(tmp_path):
    led = ledger(tmp_path)
    for attempt_id, state in (("x1", "failed"), ("x2", "cancelled")):
        led.reserve(attempt_id, 30, category="inference")
        led.reconcile(attempt_id, actual_micros=None, state=state)
        # A later zero-cost "success" would release the 30-micro liability: refused.
        with pytest.raises(ValueError, match="terminal_state_conflict"):
            led.reconcile(attempt_id, actual_micros=0, state="succeeded", receipt_id="rcpt-" + attempt_id)
        # Recovery marking it unknown without a receipt is a no-op (recovery.py:137 path):
        # no exception, outcome not relabelled.
        led.reconcile(attempt_id, actual_micros=None, state="unknown")
        # ...so a later receipt cannot launder failed -> unknown -> succeeded.
        with pytest.raises(ValueError, match="terminal_state_conflict"):
            led.reconcile(attempt_id, actual_micros=0, state="succeeded", receipt_id="rcpt2-" + attempt_id)
        # Exact replay is an idempotent no-op.
        led.reconcile(attempt_id, actual_micros=None, state=state)
    s = led.summary()
    # Both 30-micro reservations still count: 60 unresolved, states unchanged.
    assert s["unresolved_liability_micros"] == 60
    assert (s["states"]["failed"], s["states"]["cancelled"], s["states"]["succeeded"]) == (1, 1, 0)
    assert s["states"]["unknown"] == 0


def test_resolution_keeps_earlier_usage_and_compute(tmp_path):
    led = ledger(tmp_path)
    led.reserve("w1", 30, category="inference")
    led.reconcile("w1", actual_micros=None, state="failed", usage_units=4, compute_seconds=2.5)
    led.reconcile("w1", actual_micros=9, state="failed", receipt_id="rcpt-w1")  # usage/compute omitted
    inf = led.summary()["by_category"]["inference"]
    assert (inf["known_usage_units"], inf["known_compute_seconds"]) == (4, 2.5)
    led.reconcile("w1", actual_micros=9, state="failed", receipt_id="rcpt-w1")  # same replay: no-op
    with pytest.raises(ValueError, match="receipt_conflict"):
        led.reconcile("w1", actual_micros=9, state="failed", receipt_id="rcpt-w1", usage_units=5)


def test_migration_adds_columns_and_marks_existing_actuals(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    # Pre-R2 schema with one reconciled (actual 7) and one open row.
    con = sqlite3.connect(path)
    con.executescript("""CREATE TABLE authorization (id TEXT PRIMARY KEY, cap INTEGER NOT NULL);
        INSERT INTO authorization VALUES ('auth-1', 100);
        CREATE TABLE attempts (id TEXT PRIMARY KEY, reserved INTEGER NOT NULL CHECK(reserved>=0),
            actual INTEGER, state TEXT NOT NULL, category TEXT NOT NULL, usage_units INTEGER, receipt_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO attempts(id,reserved,actual,state,category,receipt_id) VALUES ('m1',10,7,'succeeded','inference','rcpt-m1');
        INSERT INTO attempts(id,reserved,state,category) VALUES ('m2',20,'reserved','inference');""")
    con.commit()
    con.close()
    led = ReservationLedger(path, cap_micros=100, authorization_id="auth-1")
    led.initialize()
    s = led.summary()
    assert s["amount_sources"] == {"estimated": 1, "actual": 1}
    assert s["by_category"]["inference"]["unknown_compute_attempts"] == 2
    assert (s["known_provider_cash_micros"], s["unresolved_liability_micros"]) == (7, 20)


def test_failed_outcome_may_later_receive_its_actual_charge(tmp_path):
    led = ledger(tmp_path)
    led.reserve("y1", 30, category="inference")
    led.reconcile("y1", actual_micros=None, state="failed")
    # Provider later bills 12 for the failed call; state stays failed.
    led.reconcile("y1", actual_micros=12, state="failed", receipt_id="rcpt-y1")
    s = led.summary()
    assert (s["known_provider_cash_micros"], s["unresolved_liability_micros"]) == (12, 0)
    assert s["states"]["failed"] == 1 and s["amount_sources"] == {"estimated": 0, "actual": 1}


def test_unknown_outcome_may_resolve_with_receipt(tmp_path):
    led = ledger(tmp_path)
    led.reserve("z1", 30, category="inference")
    led.reconcile("z1", actual_micros=None, state="unknown")
    led.reconcile("z1", actual_micros=20, state="succeeded", receipt_id="rcpt-z1")
    s = led.summary()
    assert s["states"]["succeeded"] == 1 and s["states"]["unknown"] == 0
    assert (s["known_provider_cash_micros"], s["unresolved_liability_micros"], s["remaining_micros"]) == (20, 0, 80)


def test_amount_source_and_compute_proxy_are_recorded_separately(tmp_path):
    led = ledger(tmp_path)
    led.reserve("p1", 40, category="training")
    led.reserve("p2", 40, category="training")
    led.reserve("p3", 10, category="inference")
    led.reconcile("p1", actual_micros=25, state="succeeded", receipt_id="rcpt-p1", compute_seconds=90.5)
    led.reconcile("p2", actual_micros=None, state="failed", compute_seconds=12)
    s = led.summary()
    # p1 actual; p2 (unresolved) and p3 (still reserved) are estimates.
    assert s["amount_sources"] == {"estimated": 2, "actual": 1}
    t = s["by_category"]["training"]
    # Training compute 90.5 + 12 = 102.5 s; no training attempt lacks a proxy.
    assert t["known_compute_seconds"] == 102.5 and t["unknown_compute_attempts"] == 0
    i = s["by_category"]["inference"]
    assert i["known_compute_seconds"] == 0.0 and i["unknown_compute_attempts"] == 1
    # The time proxy is never turned into money.
    assert s["economic_total"] is None and s["known_provider_cash_micros"] == 25


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), True, "5", 10**400])
def test_invalid_compute_seconds_refused(tmp_path, bad):
    led = ledger(tmp_path)
    led.reserve("q1", 10, category="inference")
    with pytest.raises(ValueError, match="invalid_compute_seconds"):
        led.reconcile("q1", actual_micros=None, state="unknown", compute_seconds=bad)


def test_same_outcome_replay_may_only_fill_missing_evidence(tmp_path):
    # Recovery replays a receipt's duration onto a row the executor recorded without it.
    led = ledger(tmp_path)
    led.reserve("v1", 30, category="training")
    led.reconcile("v1", actual_micros=None, state="succeeded", usage_units=10)
    led.reconcile("v1", actual_micros=None, state="succeeded", usage_units=10, compute_seconds=3.0)
    t = led.summary()["by_category"]["training"]
    assert (t["known_compute_seconds"], t["unknown_compute_attempts"], t["known_usage_units"]) == (3.0, 0, 10)
    with pytest.raises(ValueError, match="terminal_state_conflict"):
        led.reconcile("v1", actual_micros=None, state="succeeded", usage_units=10, compute_seconds=4.0)
    with pytest.raises(ValueError, match="terminal_state_conflict"):
        led.reconcile("v1", actual_micros=None, state="failed", compute_seconds=3.0)  # outcome change refused
    # Liability untouched by evidence fill: 30 still unresolved.
    assert led.summary()["unresolved_liability_micros"] == 30
