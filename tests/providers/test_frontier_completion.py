"""Strict chat-completions envelope parsing with canned bytes; no transport is constructed."""
import json

import pytest

from m7.providers.contracts import AdapterFault, FrontierConfig
from m7.providers.frontier import PROMPT_SHA256, TransportResponse, parse_completion

CONFIG = FrontierConfig(model_id="frontier-test", provider_model="stub-model", model_revision_sha256="5" * 64,
                        endpoint="https://example.invalid/v1/chat", provider_terms_sha256="6" * 64,
                        prompt_sha256=PROMPT_SHA256, token_counter_sha256="7" * 64,
                        max_input_tokens=1000, max_output_tokens=100, context_window_tokens=2000)


class Counter:
    sha256 = "7" * 64

    def __init__(self, completion=5):
        self.completion = completion

    def request_tokens(self, payload):
        return 10

    def completion_tokens(self, content):
        return self.completion


def body(content="[]", *, finish_reason="stop", model="stub-model", usage=(10, 5, 15), **extra):
    data = {"model": model, "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                                         "finish_reason": finish_reason}]}
    if usage is not None:
        data["usage"] = dict(zip(("prompt_tokens", "completion_tokens", "total_tokens"), usage))
    data.update(extra)
    return TransportResponse(json.dumps(data).encode("utf-8"))


def code_of(response, counter=None):
    with pytest.raises(AdapterFault) as caught:
        parse_completion(response, CONFIG, counter or Counter())
    return caught.value.code


def test_valid_envelope_returns_content_and_usage():
    completion = parse_completion(body("[]"), CONFIG, Counter())
    assert (completion.content, completion.input_tokens, completion.output_tokens) == ("[]", 10, 5)


def test_length_finish_reason_is_truncated():
    assert code_of(body(finish_reason="length")) == "truncated"


def test_completion_over_output_cap_is_truncated():
    # max_output_tokens = 100; a counted 101-token completion cannot be accepted.
    assert code_of(body(), Counter(completion=101)) == "truncated"


def test_model_drift_is_invalid():
    assert code_of(body(model="other-model")) == "invalid_output"


def test_inconsistent_usage_is_invalid():
    # 10 + 5 != 16.
    assert code_of(body(usage=(10, 5, 16))) == "invalid_output"


def test_unknown_envelope_field_is_invalid():
    assert code_of(body(tools=[])) == "invalid_output"


def test_malformed_and_non_utf8_bytes_are_invalid():
    assert code_of(TransportResponse(b'{"model": "stub-model", "choices": [')) == "invalid_output"
    assert code_of(TransportResponse(b'\xff\xfe')) == "invalid_output"


def test_refusal_is_invalid():
    data = json.loads(body().payload)
    data["choices"][0]["message"]["refusal"] = "no"
    assert code_of(TransportResponse(json.dumps(data).encode("utf-8"))) == "invalid_output"
