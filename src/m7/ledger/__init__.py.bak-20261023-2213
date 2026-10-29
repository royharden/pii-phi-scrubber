"""Atomic SQLite reservation source. Construction has not opened a database."""
from __future__ import annotations

import sqlite3
import re
from contextlib import contextmanager
from pathlib import Path


class BudgetExceeded(ValueError):
    pass


class ReservationLedger:
    """Integer microcurrency; unresolved/cancelled attempts retain full liability.

    Each operation owns a separate connection and BEGIN IMMEDIATE transaction.
    The cap belongs to one immutable authorization currency/edition.
    """
    def __init__(self, path: str | Path, *, cap_micros: int, authorization_id: str):
        if (type(cap_micros) is not int or not 0 <= cap_micros <= 2**63 - 1
                or not _identifier(authorization_id)):
            raise ValueError("invalid_authorization")
        self.path, self.cap, self.authorization_id = str(path), cap_micros, authorization_id

    @contextmanager
    def _transaction(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS authorization (id TEXT PRIMARY KEY, cap INTEGER NOT NULL)")
            existing = db.execute("SELECT id,cap FROM authorization").fetchall()
            if existing and existing != [(self.authorization_id, self.cap)]:
                raise ValueError("authorization_mismatch")
            db.execute("INSERT OR IGNORE INTO authorization VALUES (?,?)", (self.authorization_id, self.cap))
            db.execute("""CREATE TABLE IF NOT EXISTS attempts (
                id TEXT PRIMARY KEY, reserved INTEGER NOT NULL CHECK(reserved>=0),
                actual INTEGER, state TEXT NOT NULL, category TEXT NOT NULL,
                usage_units INTEGER, receipt_id TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")

    def reserve(self, attempt_id: str, worst_case_micros: int, *, category: str) -> None:
        if (type(worst_case_micros) is not int or not 0 <= worst_case_micros <= 2**63 - 1
                or not _identifier(attempt_id)):
            raise ValueError("invalid_reservation")
        if category not in ("training", "inference", "retry", "failed_trial"):
            raise ValueError("invalid_category")
        with self._transaction() as db:
            if db.execute("SELECT id,cap FROM authorization").fetchall() != [(self.authorization_id, self.cap)]:
                raise ValueError("authorization_mismatch")
            previous = db.execute("SELECT reserved,category FROM attempts WHERE id=?", (attempt_id,)).fetchone()
            if previous:
                if previous != (worst_case_micros, category):
                    raise ValueError("idempotency_conflict")
                return
            liability = db.execute("SELECT COALESCE(SUM(CASE WHEN actual IS NULL THEN reserved ELSE actual END),0) FROM attempts").fetchone()[0]
            if liability + worst_case_micros > self.cap:
                raise BudgetExceeded("authorization_cap")
            db.execute("INSERT INTO attempts(id,reserved,state,category) VALUES (?,?,'reserved',?)",
                       (attempt_id, worst_case_micros, category))

    def reconcile(self, attempt_id: str, *, actual_micros: int | None,
                  state: str, usage_units: int | None = None, receipt_id: str | None = None) -> None:
        if state not in ("succeeded", "failed", "cancelled", "unknown"):
            raise ValueError("invalid_state")
        if actual_micros is not None and (type(actual_micros) is not int or not 0 <= actual_micros <= 2**63 - 1
                                          or not _identifier(receipt_id)):
            raise ValueError("actual_requires_receipt")
        if usage_units is not None and (type(usage_units) is not int or usage_units < 0):
            raise ValueError("invalid_usage")
        if receipt_id is not None and not _identifier(receipt_id):
            raise ValueError('invalid_receipt_identifier')
        with self._transaction() as db:
            previous = db.execute("SELECT reserved,actual,state,usage_units,receipt_id FROM attempts WHERE id=?", (attempt_id,)).fetchone()
            if previous is None:
                raise ValueError("unknown_attempt")
            if previous[1] is not None:
                if previous[1:] != (actual_micros, state, usage_units, receipt_id):
                    raise ValueError("receipt_conflict")
                return
            # Overruns are recorded honestly, even when they exhaust authorization.
            db.execute("UPDATE attempts SET actual=?,state=?,usage_units=?,receipt_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (actual_micros, state, usage_units, receipt_id, attempt_id))

    def summary(self) -> dict:
        with self._transaction() as db:
            if db.execute("SELECT id,cap FROM authorization").fetchall() != [(self.authorization_id, self.cap)]:
                raise ValueError("authorization_mismatch")
            known, unresolved, count = db.execute("SELECT COALESCE(SUM(actual),0),COALESCE(SUM(CASE WHEN actual IS NULL THEN reserved ELSE 0 END),0),SUM(CASE WHEN actual IS NULL THEN 1 ELSE 0 END) FROM attempts").fetchone()
            categories = {}
            for category in ('training', 'inference', 'retry', 'failed_trial'):
                n, cash, liability, unknown, units, unknown_units = db.execute(
                    """SELECT COUNT(*),COALESCE(SUM(actual),0),
                    COALESCE(SUM(CASE WHEN actual IS NULL THEN reserved ELSE 0 END),0),
                    COALESCE(SUM(CASE WHEN actual IS NULL THEN 1 ELSE 0 END),0),
                    COALESCE(SUM(usage_units),0),
                    COALESCE(SUM(CASE WHEN usage_units IS NULL THEN 1 ELSE 0 END),0)
                    FROM attempts WHERE category=?""", (category,)).fetchone()
                categories[category] = {'attempts_N': n, 'known_provider_cash_micros': cash,
                    'unresolved_liability_micros': liability, 'unknown_attempts': unknown,
                    'known_usage_units': units, 'unknown_usage_attempts': unknown_units}
            states = {state: db.execute('SELECT COUNT(*) FROM attempts WHERE state=?', (state,)).fetchone()[0]
                      for state in ('reserved', 'succeeded', 'failed', 'cancelled', 'unknown')}
        return {"authorization_id": self.authorization_id, "cap_micros": self.cap,
                "known_provider_cash_micros": known, "unresolved_liability_micros": unresolved,
                "unknown_attempts": count or 0, "remaining_micros": max(0, self.cap-known-unresolved),
                "over_cap": known+unresolved > self.cap, "economic_total": None,
                "attempts_N": sum(row['attempts_N'] for row in categories.values()),
                "by_category": categories, "states": states,
                "economic_null_reason": "electricity_and_amortization_unmeasured"}


__all__ = ["ReservationLedger", "BudgetExceeded"]


def _identifier(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}', value) is not None
