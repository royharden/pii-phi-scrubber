"""Gold-aware publication gate and whole-artifact scan (W7).

Plan: a rendered record that retains annotated sensitive characters is replaced by
an error card; the leak still counts upstream. Offsets are hand-counted code points.
"""
import pytest

from m7.contracts import Prediction, Span, make_record
from m7.publish import PublicationDecision, artifact_is_safe, gate_record, render_report, write_report
from m7.render import render

# 'user ' = 5, 'Ana O'Brien-Kade' = 3+1+12 = 16 -> NAME [5, 21)
MESSAGE = "user Ana O'Brien-Kade signed in"
VALUE = "Ana O'Brien-Kade"
NAME = Span(start=5, end=21, label='NAME')
# Same name twice; gold annotates both: [5, 21) and, after ' aka ' (5), [26, 42).
TWICE = "user Ana O'Brien-Kade aka Ana O'Brien-Kade"
SECOND = Span(start=26, end=42, label='NAME')


def record(message=MESSAGE, record_id='rec-pub-1'):
    return make_record(message, record_id)


def predict(row, spans=()):
    return Prediction(run_id='run-1', record_id=row.record_id, content_sha256=row.content_sha256,
                      arm='finetuned', model_id='model-finetuned', attempt_id='attempt-1', status='ok',
                      spans=tuple(spans))


def test_slice_bounds_are_hand_counted():
    # Guards the literals the other cases depend on.
    assert MESSAGE[5:21] == VALUE and TWICE[26:42] == VALUE


def test_complete_coverage_is_approved_with_placeholder_only():
    row = record()
    decision = gate_record(row, (NAME,), render(row, predict(row, (NAME,))))
    # 'user ' + '[NAME_1]' + ' signed in'
    assert decision == PublicationDecision(True, 'approved', 'user [NAME_1] signed in')


def test_missed_gold_is_rejected_without_exposing_text():
    row = record()
    decision = gate_record(row, (NAME,), render(row, predict(row)))
    assert decision == PublicationDecision(False, 'gold_coverage_incomplete', None)
    assert VALUE not in repr(decision.as_dict())


def test_partial_span_cover_is_rejected():
    row = record()
    # Covers 'Ana O' [5, 10) only; 'Brien-Kade' stays visible.
    partial = Span(start=5, end=10, label='NAME')
    assert gate_record(row, (NAME,), render(row, predict(row, (partial,)))).reason == 'gold_coverage_incomplete'


def test_one_occurrence_redacted_other_left_is_rejected():
    row = record(TWICE)
    decision = gate_record(row, (NAME, SECOND), render(row, predict(row, (NAME,))))
    assert (decision.approved, decision.safe_message) == (False, None)


def test_failed_render_is_rejected():
    row = record()
    failed = Prediction(run_id='run-1', record_id=row.record_id, content_sha256=row.content_sha256,
                        arm='finetuned', model_id='model-finetuned', attempt_id='attempt-1',
                        status='invalid_output', error_code='invalid_output')
    assert gate_record(row, (NAME,), render(row, failed)).reason == 'invalid_render'


def test_artifact_scan_finds_raw_and_encoded_values():
    sources = ((record(), (NAME,)),)
    assert artifact_is_safe('<p>user [NAME_1] signed in</p>', sources) is True
    # Raw, HTML-escaped (&#x27;), URL-encoded and case-shifted variants are all leaks.
    for leaked in (VALUE, 'Ana O&#x27;Brien-Kade', 'Ana%20O%27Brien-Kade', "ANA O'BRIEN-KADE"):
        assert artifact_is_safe(f'<p>{leaked}</p>', sources) is False, leaked


def test_report_with_a_faulty_approved_card_is_replaced_by_suppression(tmp_path):
    sources = ((record(), (NAME,)),)
    # Simulates a broken upstream gate that approved a leaking message.
    faulty = PublicationDecision(True, 'approved', MESSAGE)
    destination = tmp_path / 'report.html'
    approved = write_report({'arms': []}, destination, decisions=(faulty,),
                            approve_artifact=lambda document: artifact_is_safe(document, sources))
    assert approved is False
    text = destination.read_text(encoding='utf-8')
    assert '<h1>Output suppressed</h1>' in text
    assert 'Brien-Kade' not in text


def test_rejected_card_renders_suppression_text_only():
    document = render_report({'arms': []}, decisions=(PublicationDecision(False, 'gold_coverage_incomplete'),))
    assert '<h3>Output suppressed</h3>' in document
    assert 'The failure remains in upstream metrics.' in document
    assert 'Approved synthetic development rendering' not in document


def test_report_refuses_untyped_decisions():
    with pytest.raises(TypeError, match='publication_decision_required'):
        render_report({'arms': []}, decisions=({'approved': True, 'reason': 'approved', 'safe_message': VALUE},))
