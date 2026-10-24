"""Context-rule regex baseline: hand-derived Python code-point spans (start inclusive, end exclusive)."""
from m7.contracts import make_record
from m7.detectors.regex import detect_regex


def spans(message: str) -> list[tuple[int, int, str]]:
    prediction = detect_regex(make_record(message, "rx-1"), run_id="test-run")
    assert prediction.status == "ok" and prediction.error_code is None
    return [(s.start, s.end, s.label) for s in prediction.spans]


def test_email_positive_exact_span():
    # "contact " = 8 code points; "jane.roe@example.test" = 4+1+3+1+7+1+4 = 21 -> [8, 29).
    assert spans("contact jane.roe@example.test now") == [(8, 29, "EMAIL")]


def test_email_before_sentence_period():
    # Surrounding-punctuation challenge slice: "mail " = 5; email 21 -> [5, 26); the
    # trailing "." is punctuation, not part of the domain, and must not hide the email.
    assert spans("mail jane.roe@example.test.") == [(5, 26, "EMAIL")]


def test_account_id_positive_exact_span():
    # "account_id=" = 10+1 = 11; "AC-48213" = 8 -> [11, 19).
    assert spans("account_id=AC-48213 updated") == [(11, 19, "ACCOUNT_ID")]


def test_name_positive_exact_span():
    # "person: " = 8; "Maria Lopez" = 5+1+5 = 11 -> [8, 19).
    assert spans("person: Maria Lopez logged in") == [(8, 19, "NAME")]


def test_name_with_middle_initial():
    # "name=" = 5; "Ana K. Silva" = 3+1+2+1+5 = 12 -> [5, 17).
    assert spans("name=Ana K. Silva ok") == [(5, 17, "NAME")]


def test_phone_e164_positive_exact_span():
    # "phone: " = 7; "+14155550123" = 1+11 = 12 -> [7, 19).
    assert spans("phone: +14155550123 call") == [(7, 19, "PHONE")]


def test_phone_national_with_extension():
    # "tel=" = 4; "(415) 555-0123 x12" = 5+1+8+1+3 = 18 -> [4, 22).
    assert spans("tel=(415) 555-0123 x12 done") == [(4, 22, "PHONE")]


def test_benign_numbers_without_account_context():
    # Latency, a bare integer and a trace ID carry no account/customer/user_id keyword.
    assert spans("latency=4821 ms request 99812 trace_id=AB12345") == []


def test_email_inside_account_context_is_email_only():
    # "customer_id: " = 11+1+1 = 13; "ann-lee@example.test" = 7+1+7+1+4 = 20 -> [13, 33).
    # The account rule would also match "ann-lee" [13, 20); a name/ID inside an email is EMAIL only.
    assert spans("customer_id: ann-lee@example.test") == [(13, 33, "EMAIL")]


def test_existing_placeholders_are_not_redetected():
    # Idempotence: a second scrub of rendered output must keep placeholders intact.
    message = "user_id=[ACCOUNT_ID_1] phone: [PHONE_2] person: [NAME_3] mail [EMAIL_4] [REDACTED_5]"
    assert spans(message) == []


def test_astral_prefix_shifts_by_one_code_point():
    # U+1F600 is ONE Python code point (two UTF-16 units). Without it the email is [8, 29);
    # with it directly prepended, every offset shifts by exactly 1 -> [9, 30).
    message = "\U0001F600contact jane.roe@example.test now"
    assert spans(message) == [(9, 30, "EMAIL")]
    assert message[9:30] == "jane.roe@example.test"


def test_combining_mark_prefix_counts_as_its_own_code_point():
    # "e" (0) + U+0301 (1) + " " (2) -> email starts at 3; 3 + 21 = 24. No NFC normalization.
    assert spans("é jane.roe@example.test") == [(3, 24, "EMAIL")]


def test_two_classes_in_one_message_sorted():
    # "account_id=" 11 + "AC-100" 6 -> [11, 17); " phone: " is 8 more -> value at 25,
    # "+14155550123" 12 -> [25, 37).
    assert spans("account_id=AC-100 phone: +14155550123") == [(11, 17, "ACCOUNT_ID"), (25, 37, "PHONE")]
