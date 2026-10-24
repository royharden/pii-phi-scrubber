"""Hand-derived wire-contract cases (plan: Architecture and data contracts, DEC-021).

Offsets are Python code points of the original decoded message: start inclusive,
end exclusive, no normalization. Every expected offset below is counted by hand in
a comment; the code under test is never used to compute an expected value.
"""
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from m7.contracts import LogFields, LogRecord, Prediction, Span, failure, message_hash, make_record, validate_prediction

FIXTURE = Path(__file__).resolve().parents[2] / "data-development" / "public-fictional.json"
ZERO_DIGEST = "0" * 64


def ok_prediction(record, spans=(), **overrides):
    fields = dict(run_id="run-1", record_id=record.record_id, content_sha256=record.content_sha256,
                  arm="regex", model_id="regex-v1", attempt_id="attempt-1", status="ok", spans=tuple(spans))
    fields.update(overrides)
    return Prediction(**fields)


# --- content hash ---------------------------------------------------------------

def test_message_hash_is_sha256_of_utf8_message():
    # Published SHA-256 test vector for "abc".
    assert message_hash("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    # U+1F600 is the 4-byte UTF-8 sequence F0 9F 98 80 (not UTF-16 D83D DE00).
    assert message_hash("\U0001F600") == hashlib.sha256(b"\xf0\x9f\x98\x80").hexdigest()


def test_hash_mismatch_rejected_without_echoing_message():
    with pytest.raises(ValidationError) as exc:
        LogRecord(record_id="r-1", split_id="development", content_sha256=ZERO_DIGEST,
                  log=LogFields(timestamp="2026-01-01T00:00:00Z", level="INFO", event="diagnostic",
                                message="person: Tova Quill"))
    text = str(exc.value)
    assert "content_hash_mismatch" in text
    # hide_input_in_errors: the fictional value must not appear in the error string.
    assert "Tova Quill" not in text


def test_prediction_hash_disagreement_is_terminal_identity_mismatch():
    record = make_record("person: Tova Quill", "r-1")
    prediction = ok_prediction(record, [Span(start=8, end=18, label="NAME")], content_sha256=ZERO_DIGEST)
    result = validate_prediction(record, prediction)
    assert (result.status, result.error_code, result.spans) == ("invalid_output", "identity_mismatch", ())


# --- terminal failures keep measured timing/usage (R2) ----------------------------------

def test_failure_defaults_leave_timing_and_usage_null():
    record = make_record("person: Tova Quill", "r-1")
    result = failure(record, run_id="run-1", arm="base", model_id="base-v1")
    # Unmeasured timing is null, never 0.
    assert (result.status, result.error_code, result.duration_ms, result.usage_ref) == \
        ("invalid_output", "invalid_output", None, None)


def test_failure_carries_caller_supplied_duration_and_usage():
    record = make_record("person: Tova Quill", "r-1")
    result = failure(record, run_id="run-1", arm="frontier", model_id="frontier-v1", status="failed",
                     error_code="backend_failure", attempt_id="attempt-2", duration_ms=412.5, usage_ref="usage-77")
    assert (result.status, result.error_code, result.attempt_id, result.duration_ms, result.usage_ref, result.spans) == \
        ("failed", "backend_failure", "attempt-2", 412.5, "usage-77", ())


def test_failure_still_rejects_negative_or_nonfinite_duration():
    record = make_record("x", "r-1")
    for bad in (-1.0, float("inf"), float("nan")):
        with pytest.raises(ValidationError):
            failure(record, run_id="run-1", arm="base", model_id="base-v1", duration_ms=bad)


def test_terminal_rejection_preserves_measured_duration_and_usage():
    # Out-of-range end 19 on an 18 cp message: spans dropped, but the attempt really ran for 37.25 ms.
    record = make_record("person: Tova Quill", "r-1")
    prediction = ok_prediction(record, [Span(start=8, end=19, label="NAME")], duration_ms=37.25, usage_ref="usage-9")
    result = validate_prediction(record, prediction)
    assert (result.error_code, result.spans, result.duration_ms, result.usage_ref, result.attempt_id) == \
        ("invalid_bounds", (), 37.25, "usage-9", "attempt-1")


def test_identity_mismatch_rejection_also_preserves_measured_duration_and_usage():
    # The call consumed 5.5 ms/usage-3 even though its hash disagrees; the cost stays with this attempt.
    record = make_record("person: Tova Quill", "r-1")
    prediction = ok_prediction(record, content_sha256=ZERO_DIGEST, duration_ms=5.5, usage_ref="usage-3")
    result = validate_prediction(record, prediction)
    assert (result.error_code, result.duration_ms, result.usage_ref) == ("identity_mismatch", 5.5, "usage-3")


# --- span bounds -------------------------------------------------------------------

@pytest.mark.parametrize("start,end", [(5, 5), (6, 5)])
def test_start_not_before_end_rejected(start, end):
    with pytest.raises(ValidationError) as exc:
        Span(start=start, end=end, label="NAME")
    assert "invalid_span_bounds" in str(exc.value)


def test_negative_start_rejected():
    with pytest.raises(ValidationError):
        Span(start=-1, end=3, label="NAME")


def test_end_equal_to_length_is_valid_and_one_past_is_terminal():
    # "person: Tova Quill": "person: " is 8 cp, "Tova Quill" is 10 cp -> [8,18), len 18.
    record = make_record("person: Tova Quill", "r-1")
    assert len(record.log.message) == 18
    exact = validate_prediction(record, ok_prediction(record, [Span(start=8, end=18, label="NAME")]))
    assert exact.status == "ok" and exact.spans == (Span(start=8, end=18, label="NAME"),)
    past = validate_prediction(record, ok_prediction(record, [Span(start=8, end=19, label="NAME")]))
    # Whole record becomes terminal; no clipping to 18.
    assert (past.status, past.error_code, past.spans) == ("invalid_output", "invalid_bounds", ())


def test_astral_counts_as_one_code_point_for_bounds():
    # "\U0001F600 Ana Ruiz": emoji 0, space 1, "Ana Ruiz" [2,10) -> len 10 code points.
    # UTF-16 length would be 11 and UTF-8 byte length 13; a UTF-16 end of 11 must be rejected.
    message = "\U0001F600 Ana Ruiz"
    record = make_record(message, "r-astral")
    assert len(message) == 10 and len(message.encode("utf-16-le")) // 2 == 11
    good = validate_prediction(record, ok_prediction(record, [Span(start=2, end=10, label="NAME")]))
    assert good.status == "ok"
    utf16 = validate_prediction(record, ok_prediction(record, [Span(start=3, end=11, label="NAME")]))
    assert utf16.error_code == "invalid_bounds"


@pytest.mark.parametrize("bad", [{"label": "SSN"}, {"confidence": float("nan")}, {"confidence": float("inf")},
                                 {"confidence": 1.5}])
def test_unknown_label_and_nonfinite_or_out_of_range_confidence_rejected(bad):
    fields = {"start": 0, "end": 3, "label": "NAME"} | bad
    with pytest.raises(ValidationError):
        Span(**fields)


def test_spans_on_non_ok_prediction_rejected():
    record = make_record("person: Tova Quill", "r-1")
    with pytest.raises(ValidationError):
        ok_prediction(record, [Span(start=8, end=18, label="NAME")], status="failed", error_code="backend_failure")


def test_ok_with_error_code_and_failure_without_code_rejected():
    record = make_record("x", "r-1")
    with pytest.raises(ValidationError):
        ok_prediction(record, error_code="invalid_output")
    with pytest.raises(ValidationError):
        ok_prediction(record, status="failed")


def test_more_than_128_spans_rejected():
    # 129 distinct one-code-point spans over a 129-character message.
    record = make_record("a" * 129, "r-many")
    with pytest.raises(ValidationError):
        ok_prediction(record, [Span(start=i, end=i + 1, label="NAME") for i in range(129)])


def test_extra_field_forbidden_and_models_frozen():
    with pytest.raises(ValidationError):
        Span(start=0, end=1, label="NAME", value="leak")
    span = Span(start=0, end=1, label="NAME")
    with pytest.raises(ValidationError):
        span.start = 2


# --- duplicates ----------------------------------------------------------------------

def test_duplicate_triple_collapses_deterministically_regardless_of_order():
    record = make_record("person: Tova Quill", "r-1")
    low, high = Span(start=8, end=18, label="NAME", confidence=0.2), Span(start=8, end=18, label="NAME", confidence=0.9)
    forward, backward = ok_prediction(record, [low, high]), ok_prediction(record, [high, low])
    assert len(forward.spans) == 1
    assert forward.spans == backward.spans
    # Contract keeps the maximum optional confidence of an exact duplicate triple.
    assert forward.spans[0].confidence == 0.9


def test_same_bounds_different_labels_are_not_duplicates():
    record = make_record("person: Tova Quill", "r-1")
    prediction = ok_prediction(record, [Span(start=8, end=18, label="NAME"), Span(start=8, end=18, label="EMAIL")])
    assert len(prediction.spans) == 2


# --- unicode validity and message bound --------------------------------------------

def test_lone_surrogate_rejected():
    # A JSON "\ud800" escape decodes to a lone surrogate; the record must not validate.
    message = json.loads('"x \\ud800 y"')
    assert len(message) == 5
    # ValueError covers both the schema's invalid_unicode ValidationError and any
    # earlier pydantic-core string_unicode rejection; either way no LogFields exists.
    with pytest.raises(ValueError):
        LogFields(timestamp="2026-01-01T00:00:00Z", level="INFO", event="diagnostic", message=message)
    # Real JSON input path: the lone escape inside a full record must also be rejected.
    raw = ('{"record_id":"r-s","split_id":"development","content_sha256":"' + "0" * 64 + '",'
           '"log":{"timestamp":"2026-01-01T00:00:00Z","level":"INFO","event":"diagnostic","message":"x \\ud800 y"}}')
    with pytest.raises(ValueError):
        LogRecord.model_validate_json(raw)


def test_escaped_surrogate_pair_is_one_valid_astral_code_point():
    message = json.loads('"\\ud83d\\ude00 ok"')
    assert message == "\U0001F600 ok" and len(message) == 4
    LogFields(timestamp="2026-01-01T00:00:00Z", level="INFO", event="diagnostic", message=message)


def test_message_bound_is_1024_code_points_not_bytes():
    # 1024 astral emoji = 1024 code points (4096 UTF-8 bytes) is inside the bound; 1025 is not.
    LogFields(timestamp="2026-01-01T00:00:00Z", level="INFO", event="diagnostic", message="\U0001F600" * 1024)
    with pytest.raises(ValidationError):
        LogFields(timestamp="2026-01-01T00:00:00Z", level="INFO", event="diagnostic", message="a" * 1025)


# --- public fixture -------------------------------------------------------------------

def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_unicode_record_offsets_index_decoded_message():
    # dev-002 JSON text "😀 é\r\nname: Nola Reed; customer=CU_902" decodes to:
    # 0 emoji, 1 sp, 2 'e', 3 U+0301, 4 CR, 5 LF, 6..11 "name: ", 12..20 "Nola Reed" -> [12,21),
    # 21 ';', 22 sp, 23..31 "customer=", 32..37 "CU_902" -> [32,38); len 38.
    data = load_fixture()
    raw = next(r for r in data["records"] if r["record_id"] == "dev-002")
    record = LogRecord.model_validate_json(json.dumps(raw))
    message = record.log.message
    assert len(message) == 38
    assert message[12:21] == "Nola Reed" and message[32:38] == "CU_902"
    assert [(g["start"], g["end"], g["label"]) for g in data["gold"]["dev-002"]] == [(12, 21, "NAME"), (32, 38, "ACCOUNT_ID")]


def test_fixture_records_carry_correct_hashes():
    for raw in load_fixture()["records"]:
        LogRecord.model_validate_json(json.dumps(raw))
