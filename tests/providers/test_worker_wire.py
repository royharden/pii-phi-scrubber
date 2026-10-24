"""Record-only worker wire: canonical round trips and strict rejection; bytes only, no process."""
import pytest

from m7.contracts import Prediction, Span, make_record
from m7.providers.worker_wire import (
    MAX_BOOTSTRAP_BYTES, MAX_RECORD_BYTES, MAX_REPLY_BYTES, AttemptEvent, BrokerReply, Command, ControlCommand,
    Diagnostic, InitCommand, ReconcileRequest, RecordCommand, ReserveRequest, Response, SealCommand,
    TimingCommand, WorkerReply, decode_line, encode_line,
)

from .worker_fixtures import RUN, SESSION, bootstrap

RECORD = make_record('contact jane.roe@example.test now', 'r1', 'inference')


def diagnostic(**overrides):
    values = dict(attempt_id='a-1', ordinal=1, status='ok', error_code=None, duration_ms=5.0, input_tokens=10,
                  output_tokens=5, reservation_micros=10, actual_micros=None, liability_status='unknown',
                  retry_reason=None, physical_may_have_started=True)
    values.update(overrides)
    return Diagnostic(**values)


def prediction():
    # "contact " = 8, email 21 -> [8, 29).
    return Prediction(run_id=RUN, record_id='r1', content_sha256=RECORD.content_sha256, arm='frontier',
                      model_id='frontier-test', attempt_id='a-1', status='ok',
                      spans=(Span(start=8, end=29, label='EMAIL'),))


COMMANDS = [
    lambda: InitCommand(session_id=SESSION, bootstrap=bootstrap()),
    lambda: RecordCommand(kind='preflight', session_id=SESSION, seq=1, record=RECORD),
    lambda: RecordCommand(kind='predict', session_id=SESSION, seq=3, record=RECORD),
    lambda: SealCommand(session_id=SESSION, seq=2, count=1, population_sha256='3' * 64),
    lambda: ControlCommand(kind='close', session_id=SESSION, seq=4),
    lambda: ControlCommand(kind='cancel', session_id=SESSION, seq=4),
    lambda: TimingCommand(kind='timing_identity', session_id=SESSION, seq=5),
]
RESPONSES = [
    lambda: WorkerReply(session_id=SESSION, seq=3, status='prediction', prediction=prediction(),
                        events=(AttemptEvent(run_id=RUN, arm='frontier', model_id='frontier-test', record_id='r1',
                                             content_sha256=RECORD.content_sha256, attempt=diagnostic()),)),
    lambda: WorkerReply(session_id=SESSION, seq=4, status='error', error_code='worker_failure'),
    lambda: ReserveRequest(session_id=SESSION, seq=3, rpc_seq=1, attempt_id='a-1', arm='frontier',
                           worst_case_micros=10, category='inference'),
    lambda: ReconcileRequest(session_id=SESSION, seq=3, rpc_seq=2, attempt_id='a-1', arm='frontier',
                             actual_micros=None, state='unknown'),
]


@pytest.mark.parametrize('build', COMMANDS)
def test_commands_round_trip_through_discriminated_union(build):
    message = build()
    raw = encode_line(message, limit=MAX_BOOTSTRAP_BYTES)
    assert raw.endswith(b'\n') and raw.count(b'\n') == 1
    decoded = decode_line(raw, Command, limit=MAX_BOOTSTRAP_BYTES)
    assert type(decoded) is type(message) and decoded == message
    assert encode_line(decoded, limit=MAX_BOOTSTRAP_BYTES) == raw  # canonical: re-encoding is byte-identical


@pytest.mark.parametrize('build', RESPONSES)
def test_responses_round_trip_through_discriminated_union(build):
    message = build()
    raw = encode_line(message, limit=MAX_REPLY_BYTES)
    decoded = decode_line(raw, Response, limit=MAX_REPLY_BYTES)
    assert type(decoded) is type(message) and decoded == message


def test_broker_reply_round_trips():
    message = BrokerReply(session_id=SESSION, seq=3, rpc_seq=1, status='reconciled_unknown')
    assert decode_line(encode_line(message, limit=MAX_RECORD_BYTES), BrokerReply, limit=MAX_RECORD_BYTES) == message


def test_canonical_bytes_are_compact_ascii_in_field_order():
    # Fields in declaration order kind, session_id, seq; compact separators; one trailing newline.
    assert encode_line(ControlCommand(kind='close', session_id='s-1', seq=3), limit=100) == \
        b'{"kind":"close","session_id":"s-1","seq":3}\n'
    # Non-ASCII record text is escaped (ensure_ascii): U+00E9 becomes the 6-byte JSON escape, never raw UTF-8.
    raw = encode_line(RecordCommand(kind='preflight', session_id='s-1', seq=1,
                                    record=make_record('caf' + chr(0xE9), 'r1', 'inference')), limit=MAX_RECORD_BYTES)
    assert b'caf\\u00e9' in raw and all(byte < 128 for byte in raw)


CLOSE = b'{"kind":"close","session_id":"s-1","seq":1'


@pytest.mark.parametrize('raw', [
    CLOSE + b',"extra":1}\n',                                   # unknown field
    b'{"kind":"shutdown","session_id":"s-1","seq":1}\n',        # unknown message kind
    CLOSE + b',"seq":2}\n',                                     # duplicate key
    b'{"kind":"close","session_id":"s-1","seq":NaN}\n',         # nonfinite constant
    b'{"kind":"close","session_id":"s-1","seq":"1"}\n',         # string for int (strict)
    b'{"kind":"close","session_id":"s-1","seq":true}\n',        # bool for int (strict)
    b'{"kind":"close","session_id":"s-1","seq":0}\n',           # control seq must be >= 1
    b'{"kind":"close","session_id":"s\\ud800","seq":1}\n',      # lone surrogate escape
    b'{"kind":"close","session_id":"s\xff","seq":1}\n',         # not UTF-8
    CLOSE + b'}',                                               # no line terminator
])
def test_malformed_command_lines_are_rejected(raw):
    with pytest.raises(ValueError):
        decode_line(raw, Command, limit=MAX_RECORD_BYTES)


def test_oversize_frames_are_rejected_both_ways():
    # {=1 "kind"=6 :=1 "close"=7 ,=1 "session_id"=12 :=1 "s-1"=5 ,=1 "seq"=5 :=1 1=1 }=1 \n=1 -> 44 bytes
    raw = CLOSE + b'}\n'
    assert len(raw) == 44
    with pytest.raises(ValueError, match='wire_byte_limit'):
        decode_line(raw, Command, limit=43)
    with pytest.raises(ValueError, match='wire_byte_limit'):
        encode_line(ControlCommand(kind='close', session_id='s-1', seq=1), limit=43)
    assert decode_line(raw, Command, limit=44) == ControlCommand(kind='close', session_id='s-1', seq=1)


def test_response_shapes_and_bounds_are_enforced():
    with pytest.raises(ValueError):
        WorkerReply(session_id=SESSION, seq=3, status='prediction')  # prediction status without prediction
    with pytest.raises(ValueError):
        WorkerReply(session_id=SESSION, seq=3, status='error')  # error status without error code
    with pytest.raises(ValueError):
        ReserveRequest(session_id=SESSION, seq=3, rpc_seq=17, attempt_id='a-1', arm='frontier',
                       worst_case_micros=10, category='inference')  # at most 16 broker RPCs per request


def test_diagnostics_have_no_place_for_values_and_stay_coherent():
    # A child cannot attach free text: any extra field is refused at the boundary.
    with pytest.raises(ValueError):
        Diagnostic(**diagnostic().model_dump(), message='jane.roe@example.test')
    with pytest.raises(ValueError):
        diagnostic(liability_status='known_no_call', actual_micros=5, physical_may_have_started=False)
    with pytest.raises(ValueError):
        diagnostic(liability_status='not_reserved', reservation_micros=None,
                   physical_may_have_started=True)  # not reserved yet claims a physical call
    raw = encode_line(WorkerReply(session_id=SESSION, seq=3, status='prediction', prediction=prediction(),
                                  events=(AttemptEvent(run_id=RUN, arm='frontier', model_id='frontier-test',
                                                       record_id='r1', content_sha256=RECORD.content_sha256,
                                                       attempt=diagnostic()),)), limit=MAX_REPLY_BYTES)
    assert b'jane.roe' not in raw and b'example.test' not in raw
