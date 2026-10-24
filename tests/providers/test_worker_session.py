"""Parent-side WorkerSession with a scripted in-memory child: broker liability, value-free diagnostics, close.

No process is spawned: ScriptedChild satisfies the OwnedWorker protocol with queued wire lines.
"""
import json

from m7.contracts import Prediction, Span, make_record
from m7.providers.contracts import AdapterFault
from m7.providers.worker import WorkerSession
from m7.providers.worker_wire import AttemptEvent, Diagnostic, ReconcileRequest, ReserveRequest

from .worker_fixtures import (
    RUN, SESSION, AllowGuard, AllowProcessVerifier, RecordingLedger, ScriptedChild, bootstrap, preflight_script,
    profile_and_policy, regex_bootstrap, reply,
)

PLANTED = 'jane.roe@example.test'
RECORD = make_record(f'contact {PLANTED} now', 'r1', 'inference')  # "contact " = 8, email 21 -> [8, 29)
PREDICT_SEQ = 3  # preflight r1 = seq 1, seal = seq 2, predict = seq 3


def session(tmp_path, *child_steps, sink=None, boot=None):
    boot = boot or bootstrap()
    profile, policy = profile_and_policy(tmp_path, boot)
    child = ScriptedChild(*preflight_script(1), *child_steps)
    ledger = RecordingLedger()
    worker = WorkerSession(boot, policy, profile, child, AllowGuard(), AllowProcessVerifier(),
                           {} if boot.pin.arm == 'regex' else {'frontier': ledger}, diagnostic_sink=sink)
    worker.preflight((RECORD,))
    return worker, child, ledger


def reserve(attempt_id='a-1', rpc_seq=1):
    return ReserveRequest(session_id=SESSION, seq=PREDICT_SEQ, rpc_seq=rpc_seq, attempt_id=attempt_id,
                          arm='frontier', worst_case_micros=10, category='inference')


def reconcile(attempt_id='a-1', rpc_seq=2, actual=None, state='succeeded'):
    return ReconcileRequest(session_id=SESSION, seq=PREDICT_SEQ, rpc_seq=rpc_seq, attempt_id=attempt_id,
                            arm='frontier', actual_micros=actual, state=state, usage_units=15)


def ok_reply(attempt_id='a-1', *, liability='known', actual=7, reservation=10):
    prediction = Prediction(run_id=RUN, record_id='r1', content_sha256=RECORD.content_sha256, arm='frontier',
                            model_id='frontier-test', attempt_id=attempt_id, status='ok',
                            spans=(Span(start=8, end=29, label='EMAIL'),))
    event = AttemptEvent(run_id=RUN, arm='frontier', model_id='frontier-test', record_id='r1',
                         content_sha256=RECORD.content_sha256,
                         attempt=Diagnostic(attempt_id=attempt_id, ordinal=1, status='ok', error_code=None,
                                            duration_ms=5.0, input_tokens=10, output_tokens=5,
                                            reservation_micros=reservation, actual_micros=actual,
                                            liability_status=liability, retry_reason=None,
                                            physical_may_have_started=True))
    return reply(PREDICT_SEQ, 'prediction', prediction=prediction, events=(event,))


def broker_replies(child):
    return [json.loads(raw) for raw in child.sent if json.loads(raw).get('kind') == 'broker_reply']


def test_brokered_attempt_keeps_child_cash_claims_unknown(tmp_path):
    events = []
    worker, child, ledger = session(tmp_path, reserve(), reconcile(actual=7), ok_reply(), sink=events.append)
    result = worker.predict(RECORD)
    assert result.status == 'ok' and [(s.start, s.end) for s in result.spans] == [(8, 29)]
    assert ledger.reserved == [('a-1', 10, 'inference')]
    # The child claimed 7 micros; without a verified receipt the parent reconciles actual=None.
    assert ledger.reconciled == [('a-1', None, 'succeeded', 15)]
    assert [r['status'] for r in broker_replies(child)] == ['ok', 'reconciled_unknown']
    assert worker.last_attempts[0].attempt.liability_status == 'unknown'
    assert worker.last_attempts[0].attempt.actual_micros is None
    # Parent-visible outputs never carry the record value.
    visible = [result.model_dump_json(), *(json.dumps(e) for e in events),
               *(a.model_dump_json() for a in worker.last_attempts), *(r.decode() for r in child.sent[-2:])]
    assert events and not any(PLANTED in text for text in visible)


def test_unbrokered_event_cannot_claim_cash(tmp_path):
    # No reserve happened, yet the child reports a 'known' 5-micro attempt alongside its reply.
    events = []
    claim = ok_reply('a-7', liability='known', actual=5, reservation=None)
    worker, child, ledger = session(tmp_path, reply(PREDICT_SEQ, 'budget_rejected', events=claim.events),
                                    sink=events.append)
    result = worker.predict(RECORD)
    assert result.status == 'failed' and ledger.reserved == [] and ledger.reconciled == []
    assert events == [] and worker.last_attempts == ()  # the claim never reaches parent-visible records


def ledger_free_event(arm):
    # What the regex child emits for its own timed call: unknown liability, no reservation, no cash.
    return AttemptEvent(run_id=RUN, arm=arm, model_id='context-regex-v1' if arm == 'regex' else 'frontier-test',
                        record_id='r1', content_sha256=RECORD.content_sha256,
                        attempt=Diagnostic(attempt_id='t-1', ordinal=1, status='ok', error_code=None,
                                           duration_ms=1.0, input_tokens=None, output_tokens=None,
                                           reservation_micros=None, actual_micros=None,
                                           liability_status='unknown', retry_reason=None,
                                           physical_may_have_started=True))


def test_regex_arm_ledger_free_event_is_accepted(tmp_path):
    prediction = Prediction(run_id=RUN, record_id='r1', content_sha256=RECORD.content_sha256, arm='regex',
                            model_id='context-regex-v1', attempt_id='t-1', status='ok',
                            spans=(Span(start=8, end=29, label='EMAIL'),))
    worker, child, _ = session(tmp_path, reply(PREDICT_SEQ, 'prediction', prediction=prediction,
                                               events=(ledger_free_event('regex'),)), boot=regex_bootstrap())
    assert worker.predict(RECORD).status == 'ok' and child.terminated == 0
    assert [e.attempt.attempt_id for e in worker.last_attempts] == ['t-1']


def test_paid_arm_unbrokered_unknown_event_is_refused(tmp_path):
    worker, child, _ = session(tmp_path, reply(PREDICT_SEQ, 'prediction', prediction=ok_reply().prediction,
                                               events=(ledger_free_event('frontier'),)))
    assert worker.predict(RECORD).status == 'failed' and child.terminated == 1


def test_reconcile_for_never_reserved_attempt_is_refused(tmp_path):
    worker, child, ledger = session(tmp_path, reconcile(attempt_id='a-9', rpc_seq=1), ok_reply('a-9'))
    result = worker.predict(RECORD)
    assert result.status == 'failed' and result.error_code == 'backend_failure' and result.spans == ()
    assert ledger.reserved == [] and ledger.reconciled == []  # nothing reconciled on the child's word
    assert child.terminated == 1 and worker.cleanup_status == 'closed'


def test_child_loss_after_reserve_preserves_unknown_liability(tmp_path):
    worker, child, ledger = session(tmp_path, reserve(), AdapterFault('backend_failure'))
    result = worker.predict(RECORD)
    assert result.status == 'failed' and result.error_code == 'backend_failure'
    # A terminal failure carries the parent's measured wall time, a real non-negative float.
    assert type(result.duration_ms) is float and result.duration_ms >= 0
    # The outstanding reservation is settled as unknown (full liability kept), never released.
    assert ledger.reconciled == [('a-1', None, 'unknown', None)]
    (event,) = worker.last_attempts
    assert (event.attempt.attempt_id, event.attempt.reservation_micros, event.attempt.actual_micros,
            event.attempt.liability_status, event.attempt.physical_may_have_started) == \
        ('a-1', 10, None, 'unknown', True)
    assert child.terminated == 1


def test_child_reply_carrying_a_value_is_refused_without_echo(tmp_path):
    planted = (b'{"kind":"reply","session_id":"' + SESSION.encode() + b'","seq":3,"status":"closed",'
               b'"debug":"' + PLANTED.encode() + b'"}\n')
    events = []
    worker, child, _ = session(tmp_path, planted, sink=events.append)
    result = worker.predict(RECORD)
    assert result.status == 'failed' and child.terminated == 1
    assert PLANTED not in result.model_dump_json() and not events and worker.last_attempts == ()


def test_child_identity_mismatch_is_refused(tmp_path):
    worker, child, _ = session(tmp_path, reply(PREDICT_SEQ + 1, 'prediction', prediction=ok_reply().prediction))
    assert worker.predict(RECORD).status == 'failed' and child.terminated == 1


def test_close_on_child_error_still_terminates_owned_child(tmp_path):
    worker, child, _ = session(tmp_path, reply(PREDICT_SEQ, 'error', error_code='worker_failure'))
    worker.close()  # close seq 3 answered with an error, not 'closed'
    assert child.terminated == 1 and child.waited == 1 and worker.cleanup_status == 'closed'
    sent = len(child.sent)
    # A closed session never talks to the child again: the guard refuses before any send.
    assert worker.predict(RECORD).status == 'failed' and len(child.sent) == sent
    worker.close()  # idempotent once closed
    assert len(child.sent) == sent


def test_close_when_child_pipe_breaks_terminates(tmp_path):
    worker, child, _ = session(tmp_path, AdapterFault('backend_failure'))
    worker.close()
    assert child.terminated == 1 and worker.cleanup_status == 'closed'


def test_clean_close_waits_without_terminating(tmp_path):
    worker, child, _ = session(tmp_path, reply(PREDICT_SEQ, 'closed'))
    worker.close()
    assert child.terminated == 0 and child.waited == 1 and worker.cleanup_status == 'closed'
