"""Hand-derived union-renderer cases (plan: RenderResult/v1; Packages W3).

Expected strings and offsets are counted by hand in comments from the original
decoded message (Python code points, start inclusive, end exclusive). Placeholders
are `[LABEL_n]`, or `[REDACTED_n]` for a cross-label union; n numbers replacement
intervals in first-appearance order within the record.
"""
import json
from pathlib import Path

from m7.contracts import Prediction, Span, make_record
from m7.render import render

FIXTURE = Path(__file__).resolve().parents[2] / "data-development" / "public-fictional.json"


def ok(record, *spans, **overrides):
    fields = dict(run_id="run-1", record_id=record.record_id, content_sha256=record.content_sha256,
                  arm="regex", model_id="regex-v1", attempt_id="attempt-1", status="ok", spans=tuple(spans))
    fields.update(overrides)
    return Prediction(**fields)


def fixture_message(record_id):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return next(r["log"]["message"] for r in data["records"] if r["record_id"] == record_id)


def bounds(result):
    return [(i.start, i.end, i.placeholder) for i in result.intervals]


# --- Unicode / original-string mapping -----------------------------------------------

def test_astral_prefix_counts_one_code_point():
    # 0 emoji, 1 sp, 2..7 "name: ", "Ana Ruiz" = [8,16); len 16 (UTF-16 would put it at 9).
    record = make_record("\U0001F600 name: Ana Ruiz", "r-astral")
    result = render(record, ok(record, Span(start=8, end=16, label="NAME")))
    assert result.schema_valid and result.error_code is None
    assert result.safe_log.message == "\U0001F600 name: [NAME_1]"
    assert bounds(result) == [(8, 16, "[NAME_1]")]


def test_combining_sequence_inside_span_and_untouched_outside():
    # "user René Doe; café ok": "user " 0..4, R5 e6 n7 e8 U+0301@9 sp10 D11 o12 e13,
    # ';'14 sp15 c16 a17 f18 e19 U+0301@20 sp21 o22 k23 -> len 24, name [5,14).
    record = make_record("user René Doe; café ok", "r-comb")
    result = render(record, ok(record, Span(start=5, end=14, label="NAME")))
    assert result.safe_log.message == "user [NAME_1]; café ok"
    # No NFC normalization of benign text: precomposed U+00E9 must not appear.
    assert "é" not in result.safe_log.message


def test_span_ending_before_combining_mark_is_replaced_exactly():
    # Span [5,9) stops before U+0301 at index 9; the renderer neither widens nor drops it.
    # Whole-grapheme span policy belongs to the annotation guide/detectors, not the renderer.
    record = make_record("user René Doe; café ok", "r-comb")
    result = render(record, ok(record, Span(start=5, end=9, label="NAME")))
    assert result.safe_log.message == "user [NAME_1]́ Doe; café ok"


def test_crlf_and_json_escapes_index_decoded_message():
    # JSON text "line1\r\nperson: Kai Moss \"x\"" decodes to 'line1' 0..4, CR 5, LF 6,
    # "person: " 7..14, "Kai Moss" [15,23), sp 23, '"' 24, 'x' 25, '"' 26 -> len 27.
    # In the JSON text the name starts at 18 (quote + two 2-char escapes); 18 is wrong here.
    message = json.loads('"line1\\r\\nperson: Kai Moss \\"x\\""')
    assert len(message) == 27
    record = make_record(message, "r-crlf", level="ERROR", event="contact")
    result = render(record, ok(record, Span(start=15, end=23, label="NAME")))
    assert result.safe_log.message == 'line1\r\nperson: [NAME_1] "x"'
    # Safe fields are preserved byte-for-byte; the log stays a valid single-message JSON object.
    assert (result.safe_log.timestamp, result.safe_log.level, result.safe_log.event) == \
        ("2026-01-01T00:00:00Z", "ERROR", "contact")
    assert json.loads(result.safe_log.model_dump_json())["message"] == 'line1\r\nperson: [NAME_1] "x"'


def test_fixture_unicode_record_renders_both_spans():
    # dev-002: NAME [12,21) "Nola Reed", ACCOUNT_ID [32,38) "CU_902" (see tests/contracts).
    record = make_record(fixture_message("dev-002"), "dev-002")
    result = render(record, ok(record, Span(start=32, end=38, label="ACCOUNT_ID"), Span(start=12, end=21, label="NAME")))
    assert result.safe_log.message == "\U0001F600 é\r\nname: [NAME_1]; customer=[ACCOUNT_ID_2]"


def test_quotes_and_backslash_in_benign_text_preserved():
    # dev-006 'person: Kira-Sue Moss; user_id=USER_444; literal "quote" and \ path':
    # "person: " 0..7, "Kira-Sue Moss" [8,21), "; user_id=" 21..30, "USER_444" [31,39).
    record = make_record(fixture_message("dev-006"), "dev-006")
    result = render(record, ok(record, Span(start=8, end=21, label="NAME"), Span(start=31, end=39, label="ACCOUNT_ID")))
    assert result.safe_log.message == 'person: [NAME_1]; user_id=[ACCOUNT_ID_2]; literal "quote" and \\ path'


# --- occurrence and ordering --------------------------------------------------------------

def test_repeated_text_only_predicted_occurrence_replaced():
    # dev-004 "email: repeat@example.invalid; email: repeat@example.invalid":
    # "email: " 0..6, first [7,29) (22 cp), "; " 29..30, "email: " 31..37, second [38,60); len 60.
    record = make_record(fixture_message("dev-004"), "dev-004")
    result = render(record, ok(record, Span(start=38, end=60, label="EMAIL")))
    assert result.safe_log.message == "email: repeat@example.invalid; email: [EMAIL_1]"


def test_ordinals_follow_position_not_prediction_order():
    # dev-001 gold: NAME [8,17), EMAIL [26,51), ACCOUNT_ID [64,72), PHONE [81,93); supplied shuffled.
    record = make_record(fixture_message("dev-001"), "dev-001")
    result = render(record, ok(record, Span(start=81, end=93, label="PHONE"), Span(start=26, end=51, label="EMAIL"),
                               Span(start=64, end=72, label="ACCOUNT_ID"), Span(start=8, end=17, label="NAME")))
    assert result.safe_log.message == "person: [NAME_1]; email: [EMAIL_2]; account_id=[ACCOUNT_ID_3]; phone: [PHONE_4]"


def test_adjacent_spans_stay_separate():
    # "id:AB12CD34": "id:" 0..2, "AB12" [3,7), "CD34" [7,11) touch but do not intersect.
    record = make_record("id:AB12CD34", "r-adj")
    result = render(record, ok(record, Span(start=3, end=7, label="ACCOUNT_ID"), Span(start=7, end=11, label="ACCOUNT_ID")))
    assert result.safe_log.message == "id:[ACCOUNT_ID_1][ACCOUNT_ID_2]"
    assert [(i.same_label, i.cross_label) for i in result.intervals] == [(False, False), (False, False)]


# --- overlap union ----------------------------------------------------------------------
# M = "m: AAAABBBBCCCC end": 'm'0 ':'1 sp2, A 3..6, B 7..10, C 11..14, sp15, "end" 16..18; len 19.
M = "m: AAAABBBBCCCC end"


def test_cross_label_overlap_is_one_redacted_interval():
    # NAME [3,11) and EMAIL [7,15) intersect on [7,11) -> union [3,15), neither contains the other.
    record = make_record(M, "r-x")
    result = render(record, ok(record, Span(start=7, end=15, label="EMAIL"), Span(start=3, end=11, label="NAME")))
    assert result.safe_log.message == "m: [REDACTED_1] end"
    (interval,) = result.intervals
    assert (interval.start, interval.end) == (3, 15)
    assert (interval.cross_label, interval.same_label, interval.nested) == (True, False, False)
    # candidate_ids index the sorted deduplicated spans: (3,11,NAME)=0, (7,15,EMAIL)=1.
    assert interval.candidate_ids == (0, 1)


def test_same_label_overlap_keeps_label():
    record = make_record(M, "r-s")
    result = render(record, ok(record, Span(start=3, end=11, label="NAME"), Span(start=7, end=15, label="NAME")))
    assert result.safe_log.message == "m: [NAME_1] end"
    (interval,) = result.intervals
    assert (interval.cross_label, interval.same_label, interval.nested) == (False, True, False)


def test_nested_same_label_sets_nested_flag():
    # NAME [3,15) contains NAME [7,11).
    record = make_record(M, "r-n")
    result = render(record, ok(record, Span(start=3, end=15, label="NAME"), Span(start=7, end=11, label="NAME")))
    assert result.safe_log.message == "m: [NAME_1] end"
    (interval,) = result.intervals
    assert (interval.start, interval.end, interval.nested, interval.same_label) == (3, 15, True, True)


def test_union_tracks_group_maximum_end_not_previous_span():
    # Sorted: NAME [3,15), EMAIL [4,6), PHONE [10,12). PHONE misses EMAIL (10 >= 6) but lies
    # inside NAME, so all three form one interval [3,15); comparing only to the previous span would split it.
    record = make_record(M, "r-g")
    result = render(record, ok(record, Span(start=3, end=15, label="NAME"), Span(start=4, end=6, label="EMAIL"),
                               Span(start=10, end=12, label="PHONE")))
    assert result.safe_log.message == "m: [REDACTED_1] end"
    (interval,) = result.intervals
    assert (interval.start, interval.end, interval.cross_label, interval.nested) == (3, 15, True, True)


def test_transitive_chain_unions_and_later_interval_numbered_two():
    # [3,8) NAME, [7,12) NAME, [11,15) NAME chain into [3,15); "end" [16,19) is a separate ACCOUNT_ID.
    record = make_record(M, "r-c")
    result = render(record, ok(record, Span(start=3, end=8, label="NAME"), Span(start=7, end=12, label="NAME"),
                               Span(start=11, end=15, label="NAME"), Span(start=16, end=19, label="ACCOUNT_ID")))
    assert result.safe_log.message == "m: [NAME_1] [ACCOUNT_ID_2]"
    assert bounds(result) == [(3, 15, "[NAME_1]"), (16, 19, "[ACCOUNT_ID_2]")]


def test_duplicate_prediction_yields_one_interval():
    record = make_record(fixture_message("dev-004"), "dev-004")
    result = render(record, ok(record, Span(start=7, end=29, label="EMAIL"), Span(start=7, end=29, label="EMAIL")))
    assert result.safe_log.message == "email: [EMAIL_1]; email: repeat@example.invalid"
    (interval,) = result.intervals
    assert (interval.candidate_ids, interval.same_label, interval.nested) == ((0,), False, False)


# --- validation failures and leak faults -----------------------------------------------

def assert_suppressed(result, *secrets):
    assert result.schema_valid is False and result.safe_log is None and result.intervals == ()
    dumped = result.model_dump_json()
    for secret in secrets:
        assert secret not in dumped


def test_out_of_range_prediction_renders_nothing():
    # "person: Tova Quill" has len 18; end 19 is out of range -> terminal, no clipping.
    record = make_record("person: Tova Quill", "r-oor")
    result = render(record, ok(record, Span(start=8, end=19, label="NAME")))
    assert result.error_code == "invalid_prediction"
    assert_suppressed(result, "Tova", "Quill")


def test_hash_mismatched_prediction_renders_nothing():
    record = make_record("person: Tova Quill", "r-hash")
    result = render(record, ok(record, Span(start=8, end=18, label="NAME"), content_sha256="0" * 64))
    assert result.error_code == "invalid_prediction"
    assert_suppressed(result, "Tova", "Quill")


def test_non_ok_prediction_yields_no_safe_log():
    record = make_record("person: Tova Quill", "r-fail")
    result = render(record, ok(record, status="failed", error_code="backend_failure"))
    assert result.error_code == "invalid_prediction"
    assert_suppressed(result, "Tova", "Quill")


def test_placeholder_expansion_past_bound_is_invalid_structure():
    # "Quill" + 1019 'x' = 1024 cp. Replacing [0,5) with "[NAME_1]" (8 cp) gives 1027 > 1024.
    record = make_record("Quill" + "x" * 1019, "r-big")
    result = render(record, ok(record, Span(start=0, end=5, label="NAME")))
    assert result.error_code == "invalid_structure"
    assert_suppressed(result, "Quill", "xxxx")


def test_placeholder_expansion_exactly_at_bound_is_valid():
    # "Quill" + 1016 'x' = 1021 cp; after replacement 8 + 1016 = 1024, exactly the bound.
    record = make_record("Quill" + "x" * 1016, "r-edge")
    result = render(record, ok(record, Span(start=0, end=5, label="NAME")))
    assert result.schema_valid and len(result.safe_log.message) == 1024


def test_empty_rendered_output_is_invalid_structure():
    # An empty message renders to "": never a successful scrub (plan failure table).
    record = make_record("", "r-empty")
    result = render(record, ok(record))
    assert result.error_code == "invalid_structure"
    assert_suppressed(result)


def test_whole_message_span_renders_placeholder_not_empty():
    # "Tova Quill" is [0,10) of a 10 cp message; output is the placeholder alone.
    record = make_record("Tova Quill", "r-whole")
    result = render(record, ok(record, Span(start=0, end=10, label="NAME")))
    assert result.safe_log.message == "[NAME_1]"


# --- idempotence --------------------------------------------------------------------------

def test_already_rendered_fixture_unchanged_with_no_spans():
    message = fixture_message("dev-007")
    assert message == "person: [NAME_1]; account_id=[ACCOUNT_ID_2]; mail [EMAIL_3]"
    record = make_record(message, "dev-007")
    result = render(record, ok(record))
    assert result.schema_valid and result.intervals == ()
    assert result.safe_log.message == message


def test_second_render_of_rendered_output_preserves_placeholders():
    record = make_record(M, "r-1st")
    first = render(record, ok(record, Span(start=3, end=11, label="NAME"), Span(start=7, end=15, label="EMAIL")))
    assert first.safe_log.message == "m: [REDACTED_1] end"
    second_record = make_record(first.safe_log.message, "r-2nd")
    second = render(second_record, ok(second_record))
    assert second.safe_log.message == "m: [REDACTED_1] end"
