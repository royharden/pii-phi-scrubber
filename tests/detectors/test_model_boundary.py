"""Permit-gated local model boundary with injected stub backends; no model is loaded."""
import pytest
from pydantic import ValidationError

from m7.contracts import Span, make_record, message_hash
from m7.detectors.model import ModelPermit, TokenSpan, detect_model

# "person: " = 8; "Maria Lopez" = 11 -> [8, 19); len(MESSAGE) = 19.
MESSAGE = "person: Maria Lopez"
RECORD = make_record(MESSAGE, "md-1")


def permit(model_id="gliner-base", **overrides):
    values = dict(permit_id="permit-1", model_id=model_id, weights_sha256="1" * 64,
                  tokenizer_sha256="2" * 64, license_receipt_sha256="3" * 64,
                  authorization_sha256="4" * 64, approved=True)
    values.update(overrides)
    return ModelPermit(**values)


def detect(**kwargs):
    kwargs.setdefault("arm", "base")
    kwargs.setdefault("model_id", "gliner-base")
    return detect_model(RECORD, run_id="test-run", **kwargs)


def ok_backend(spans=(Span(start=8, end=19, label="NAME"),), *, truncated=False, digest=None):
    calls = []

    def backend(message):
        calls.append(message)
        return TokenSpan(spans=spans, truncated=truncated, input_sha256=digest or message_hash(message),
                         offset_unit="unicode_codepoint")
    backend.calls = calls
    return backend


def assert_failure(prediction, status, code):
    assert prediction.status == status and prediction.error_code == code and prediction.spans == ()


def test_permitted_backend_spans_pass_through():
    backend = ok_backend()
    p = detect(permit=permit(), backend=backend)
    assert p.status == "ok" and [(s.start, s.end, s.label) for s in p.spans] == [(8, 19, "NAME")]
    assert backend.calls == [MESSAGE]


def test_missing_permit_is_unavailable_and_never_calls_backend():
    backend = ok_backend()
    assert_failure(detect(permit=None, backend=backend), "unavailable", "permit_required")
    assert backend.calls == []


def test_missing_backend_is_unavailable():
    assert_failure(detect(permit=permit(), backend=None), "unavailable", "permit_required")


def test_mismatched_permit_model_is_unavailable():
    backend = ok_backend()
    assert_failure(detect(permit=permit(model_id="gliner-other"), backend=backend),
                   "unavailable", "permit_required")
    assert backend.calls == []


def test_unapproved_permit_cannot_be_constructed():
    with pytest.raises(ValidationError):
        permit(approved=False)


def test_backend_exception_is_fixed_enum_without_exception_text():
    def boom(message):
        raise RuntimeError("provider leaked person: Maria Lopez")
    p = detect(permit=permit(), backend=boom)
    assert_failure(p, "failed", "backend_failure")
    assert "Maria" not in p.model_dump_json() and "provider" not in p.model_dump_json()


def test_wrong_input_hash_is_invalid_output():
    p = detect(permit=permit(), backend=ok_backend(digest=message_hash("something else")))
    assert_failure(p, "invalid_output", "invalid_output")


def test_truncated_backend_output_is_reported_truncated():
    assert_failure(detect(permit=permit(), backend=ok_backend(truncated=True)), "invalid_output", "truncated")


def test_span_past_message_end_is_invalid_bounds():
    # len(MESSAGE) = 19, so end 20 is out of range; no clipping.
    p = detect(permit=permit(), backend=ok_backend(spans=(Span(start=8, end=20, label="NAME"),)))
    assert_failure(p, "invalid_output", "invalid_bounds")


def test_non_codepoint_offset_unit_is_rejected():
    with pytest.raises(ValidationError):
        TokenSpan(spans=(), truncated=False, input_sha256=message_hash(MESSAGE), offset_unit="utf16_codeunit")

    class Utf16Result:  # duck-typed result claiming UTF-16 offsets is not a TokenSpan
        spans = ()
        truncated = False
        input_sha256 = message_hash(MESSAGE)
        offset_unit = "utf16_codeunit"
    assert_failure(detect(permit=permit(), backend=lambda message: Utf16Result()),
                   "invalid_output", "invalid_output")
