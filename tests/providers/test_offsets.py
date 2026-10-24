"""Explicit offset conversion: backend UTF-8/UTF-16 offsets map to code points or are rejected."""
import pytest

from m7.providers.contracts import AdapterFault
from m7.providers.offsets import codepoint_boundary, token_span

# "a" + U+1F600 + "b": code points a=0, emoji=1, b=2, len 3.
# UTF-16 units: a=1, emoji=2 (surrogate pair), b=1 -> boundaries 0, 1, 3, 4.
# UTF-8 bytes:  a=1, emoji=4,                 b=1 -> boundaries 0, 1, 5, 6.
TEXT = "a\U0001F600b"


def rejected(*args):
    with pytest.raises(AdapterFault) as caught:
        codepoint_boundary(*args)
    assert caught.value.code == "invalid_output"


@pytest.mark.parametrize("offset, expected", [(0, 0), (1, 1), (3, 2), (4, 3)])
def test_utf16_boundaries_across_astral_char(offset, expected):
    assert codepoint_boundary(TEXT, offset, "utf16_codeunit") == expected


@pytest.mark.parametrize("offset, expected", [(0, 0), (1, 1), (5, 2), (6, 3)])
def test_utf8_boundaries_across_astral_char(offset, expected):
    assert codepoint_boundary(TEXT, offset, "utf8_byte") == expected


def test_offset_inside_surrogate_pair_is_rejected():
    rejected(TEXT, 2, "utf16_codeunit")  # between the two UTF-16 halves of U+1F600


@pytest.mark.parametrize("offset", [2, 3, 4])
def test_offset_inside_utf8_sequence_is_rejected(offset):
    rejected(TEXT, offset, "utf8_byte")


def test_offsets_past_end_are_rejected():
    rejected(TEXT, 5, "utf16_codeunit")
    rejected(TEXT, 7, "utf8_byte")
    rejected(TEXT, 4, "unicode_codepoint")


def test_codepoint_unit_is_identity_within_bounds():
    assert codepoint_boundary(TEXT, 2, "unicode_codepoint") == 2
    assert codepoint_boundary(TEXT, 3, "unicode_codepoint") == 3


def test_negative_bool_and_unknown_unit_are_rejected():
    rejected(TEXT, -1, "utf8_byte")
    rejected(TEXT, True, "unicode_codepoint")
    rejected(TEXT, 1, "utf32")


def test_combining_mark_is_its_own_code_point():
    # "e" + U+0301 + "x": UTF-16 units 1,1,1 so unit 2 -> code point 2; UTF-8 bytes 1,2,1 so byte 3 -> 2.
    text = "éx"
    assert codepoint_boundary(text, 2, "utf16_codeunit") == 2
    assert codepoint_boundary(text, 3, "utf8_byte") == 2
    rejected(text, 2, "utf8_byte")  # inside the 2-byte encoding of U+0301


# Fast-tokenizer style offset map for "Ann Lee": special token (0,0), "Ann" (0,3), "Lee" (4,7).
NAME_TEXT = "Ann Lee"
NAME_MAP = [(0, 0), (0, 3), (4, 7)]


def test_token_span_maps_token_range_to_original_text():
    span = token_span(NAME_TEXT, NAME_MAP, 1, 3, "NAME")
    assert (span.start, span.end, span.label) == (0, 7, "NAME")
    assert NAME_TEXT[span.start:span.end] == "Ann Lee"


@pytest.mark.parametrize("offsets, start, end", [
    (NAME_MAP, 0, 2),               # includes the (0,0) special token
    (NAME_MAP, 2, 2),               # empty token range
    (NAME_MAP, 1, 4),               # end token past the map
    ([(0, 0), (4, 7), (0, 3)], 1, 3),  # backward map
    ([(0, 0), (0, 3), (4, 8)], 1, 3),  # char end past len(text) = 7
])
def test_token_span_rejects_invalid_maps(offsets, start, end):
    with pytest.raises(AdapterFault) as caught:
        token_span(NAME_TEXT, offsets, start, end, "NAME")
    assert caught.value.code == "invalid_output"
