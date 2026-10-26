"""Compute is a time proxy; child claims never establish authoritative cash."""

import io
import json

import pytest

from m7.providers.contracts import CashReceipt
from m7.providers.worker_service import RemoteLedger
from m7.providers.worker_wire import (
    MAX_REPLY_BYTES, BrokerReply, ReconcileRequest, Response, decode_line, encode_line,
)

from .test_worker_session import RECORD, ok_reply, reserve, session
from .worker_fixtures import SESSION, bootstrap


def request(**updates):
    fields = dict(session_id=SESSION, seq=3, rpc_seq=2, attempt_id="a-1",
                  arm="frontier", actual_micros=7, state="succeeded", usage_units=15)
    fields.update(updates)
    return ReconcileRequest(**fields)


@pytest.mark.parametrize("seconds", [None, 0.0, 1.25, 1_000_000_000.0])
def test_compute_wire_distinguishes_unknown_zero_and_positive(seconds):
    # Bug caught: absent compute and measured zero must not collapse together.
    original = request(compute_seconds=seconds)
    decoded = decode_line(encode_line(original, limit=MAX_REPLY_BYTES), Response, limit=MAX_REPLY_BYTES)
    assert decoded.compute_seconds == seconds


def test_legacy_wire_without_compute_remains_unknown():
    # Old worker frames remain readable without inventing measured zero.
    old = request().model_dump(mode="json")
    old.pop("compute_seconds", None)
    decoded = decode_line((json.dumps(old) + "\n").encode(), Response, limit=MAX_REPLY_BYTES)
    assert decoded.compute_seconds is None


@pytest.mark.parametrize("invalid", [True, -0.1, float("nan"), float("inf"), 1_000_000_001.0, "1.25"])
def test_compute_wire_refuses_invalid_proxy(invalid):
    # Strict finite numeric bounds match the parent ledger's supported range.
    with pytest.raises(ValueError):
        request(compute_seconds=invalid)


@pytest.mark.parametrize("seconds", [None, 0.0, 1.25])
def test_child_remote_ledger_transmits_compute(seconds):
    # Bug caught: RemoteLedger used to silently discard this optional argument.
    response = BrokerReply(session_id=SESSION, seq=3, rpc_seq=1, status="ok")
    output = io.BytesIO()
    remote = RemoteLedger(bootstrap(), "frontier", io.BytesIO(encode_line(response, limit=MAX_REPLY_BYTES)), output)
    remote.seq = 3
    remote.reconcile("a-1", actual_micros=None, state="succeeded", compute_seconds=seconds)
    outgoing = decode_line(output.getvalue(), Response, limit=MAX_REPLY_BYTES)
    assert outgoing.compute_seconds == seconds


@pytest.mark.parametrize("seconds", [None, 0.0, 1.25])
@pytest.mark.parametrize("verified_cash", [False, True])
def test_parent_records_proxy_but_requires_its_own_cash_receipt(tmp_path, seconds, verified_cash):
    # Independent oracle: child says 7 micros, trusted parent says 4 (or nothing).
    # Compute must survive either case without converting unknown cash to zero.
    worker, child, ledger = session(tmp_path, reserve(), request(compute_seconds=seconds), ok_reply())
    calls = []

    def record_reconcile(attempt_id, **fields):
        calls.append((attempt_id, fields))

    ledger.reconcile = record_reconcile
    if verified_cash:
        worker.reconcile_verifier = lambda req: CashReceipt(
            attempt_id=req.attempt_id, receipt_id="parent-receipt", actual_micros=4,
            receipt_sha256="a" * 64,
        )
    assert worker.predict(RECORD).status == "ok"
    assert len(calls) == 1 and calls[0][0] == "a-1"
    fields = calls[0][1]
    assert fields.get("compute_seconds") == seconds
    assert fields["actual_micros"] == (4 if verified_cash else None)
    assert fields["receipt_id"] == ("parent-receipt" if verified_cash else None)
    assert worker.last_attempts[0].attempt.actual_micros == (4 if verified_cash else None)
    assert worker.last_attempts[0].attempt.liability_status == ("known" if verified_cash else "unknown")
    assert child.terminated == 0
