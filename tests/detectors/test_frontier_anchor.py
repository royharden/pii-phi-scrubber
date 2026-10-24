"""Frontier strict span wire: exact unique anchoring, terminal malformed output, no raw retention."""
import json

from m7.contracts import make_record, message_hash, validate_prediction
from m7.detectors.frontier import anchor_frontier

# "a: " occupies 0..2, first "Ann Lee" [3, 10); "; b: " occupies 10..14, second "Ann Lee" [15, 22).
REPEATED = "a: Ann Lee; b: Ann Lee"


def proposal(label, quote, left="", right=""):
    return {"label": label, "quote": quote, "left_ctx": left, "right_ctx": right}


def anchor(message, response):
    return anchor_frontier(make_record(message, "fr-1"), response, run_id="test-run",
                           model_id="frontier-test", attempt_id="attempt-1")


def assert_terminal_invalid(prediction, *leaked):
    assert prediction.status == "invalid_output"
    assert prediction.error_code == "invalid_output"
    assert prediction.spans == ()
    dumped = prediction.model_dump_json()
    for value in leaked:
        assert value not in dumped


def test_context_disambiguates_repeated_quote():
    # Combined "b: Ann Lee" occurs once, at index 12; start = 12 + len("b: ") = 15, end = 15 + 7 = 22.
    p = anchor(REPEATED, json.dumps([proposal("NAME", "Ann Lee", left="b: ")]))
    assert p.status == "ok" and p.unanchored_count == 0
    assert [(s.start, s.end, s.label) for s in p.spans] == [(15, 22, "NAME")]


def test_ambiguous_quote_without_context_is_unanchored_not_guessed():
    # "Ann Lee" occurs twice and has no context; no occurrence guessing -> 0 spans, 1 unanchored.
    p = anchor(REPEATED, json.dumps([proposal("NAME", "Ann Lee")]))
    assert p.status == "ok" and p.spans == () and p.unanchored_count == 1


def test_partial_anchoring_keeps_anchored_spans_and_counts_missing():
    # "Ann Lee" with left "a: " -> combined at 0, start 3, end 10. "Bo Diaz" is absent -> unanchored.
    response = json.dumps([proposal("NAME", "Ann Lee", left="a: "), proposal("NAME", "Bo Diaz")])
    p = anchor(REPEATED, response)
    assert [(s.start, s.end) for s in p.spans] == [(3, 10)] and p.unanchored_count == 1
    assert "Bo Diaz" not in p.model_dump_json()


def test_quote_context_mismatch_falls_back_only_to_a_unique_quote():
    # Combined "x Ann Lee" absent; quote alone not unique -> unanchored, never fuzzy matched.
    p = anchor(REPEATED, json.dumps([proposal("NAME", "Ann Lee", left="x ")]))
    assert p.spans == () and p.unanchored_count == 1


def test_astral_prefix_anchor_offsets_are_code_points():
    # U+1F600 + " mail " -> 1 + 6 = 7; "jo@ex.test" = 10 -> [7, 17). (UTF-16 would give 8.)
    message = "\U0001F600 mail jo@ex.test"
    p = anchor(message, json.dumps([proposal("EMAIL", "jo@ex.test")]))
    assert [(s.start, s.end) for s in p.spans] == [(7, 17)]


def test_malformed_json_is_terminal_and_retains_no_raw_output():
    p = anchor(REPEATED, '[{"label": "NAME", "quote": "Ann Lee"')
    assert_terminal_invalid(p, "Ann Lee", "quote")


def test_unknown_label_is_terminal():
    assert_terminal_invalid(anchor(REPEATED, json.dumps([proposal("SSN", "Ann Lee", left="a: ")])), "SSN")


def test_extra_field_is_terminal():
    item = proposal("NAME", "Ann Lee", left="a: ")
    item["value"] = "Ann Lee"
    assert_terminal_invalid(anchor(REPEATED, json.dumps([item])))


def test_duplicate_json_key_is_terminal():
    response = '[{"label":"NAME","label":"EMAIL","quote":"Ann Lee","left_ctx":"a: ","right_ctx":""}]'
    assert_terminal_invalid(anchor(REPEATED, response))


def test_non_list_and_nonfinite_constants_are_terminal():
    assert_terminal_invalid(anchor(REPEATED, json.dumps(proposal("NAME", "Ann Lee"))))
    assert_terminal_invalid(anchor(REPEATED, "NaN"))


def test_out_of_range_quote_and_context_lengths_are_terminal():
    # Limits from the plan: quote 1..1024 code points, each context at most 24.
    assert_terminal_invalid(anchor(REPEATED, json.dumps([proposal("NAME", "")])))
    assert_terminal_invalid(anchor(REPEATED, json.dumps([proposal("NAME", "A" * 1025)])))
    assert_terminal_invalid(anchor(REPEATED, json.dumps([proposal("NAME", "Ann Lee", left="x" * 25)])))


def test_more_than_128_proposals_is_terminal():
    assert_terminal_invalid(anchor(REPEATED, json.dumps([proposal("NAME", "Ann Lee", left="a: ")] * 129)))


def test_non_string_response_is_terminal():
    assert_terminal_invalid(anchor(REPEATED, b'[]'))


def test_wrong_input_hash_fails_identity_check():
    # A prediction anchored for one record cannot be accepted for another record's input.
    record = make_record(REPEATED, "fr-1")
    other = make_record("a: Ann Lee", "fr-1")
    p = anchor_frontier(other, json.dumps([proposal("NAME", "Ann Lee")]), run_id="test-run",
                        model_id="frontier-test", attempt_id="attempt-1")
    assert p.content_sha256 == message_hash("a: Ann Lee") != record.content_sha256
    checked = validate_prediction(record, p)
    assert checked.status == "invalid_output" and checked.error_code == "identity_mismatch"
    assert checked.spans == ()
