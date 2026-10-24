"""Retry controller and same-denominator registry, driven only by injected stub transports.

No network, credential, provider or database: the ledger is an in-memory recorder that
satisfies the controller's Ledger protocol, and the transport returns canned envelopes.
"""
import json

import pytest

from m7.contracts import make_record
from m7.detectors.registry import build_registry
from m7.providers.contracts import AdapterFault, AttemptPolicy, ExecutionPermit, FrontierConfig, config_digest
from m7.providers.frontier import PROMPT_SHA256, TransportFault, TransportResponse

RUN = "test-run"
# "contact " = 8; "jane.roe@example.test" = 21 -> EMAIL [8, 29).
EMAIL_MESSAGE = "contact jane.roe@example.test now"
EMAIL_CONTENT = json.dumps([{"label": "EMAIL", "quote": "jane.roe@example.test", "left_ctx": "", "right_ctx": ""}])


def frontier_config():
    return FrontierConfig(model_id="frontier-test", provider_model="stub-model", model_revision_sha256="5" * 64,
                          endpoint="https://example.invalid/v1/chat", provider_terms_sha256="6" * 64,
                          prompt_sha256=PROMPT_SHA256, token_counter_sha256="7" * 64,
                          max_input_tokens=1000, max_output_tokens=100, context_window_tokens=2000)


def attempt_policy(retries=1):
    # Zero quoted rates -> frontier bound ceil(0/1e6) + 0 = 0, so worst_case 10 is sufficient.
    return AttemptPolicy(policy_id="policy-1", authorization_id="auth-1", rate_receipt_sha256="8" * 64,
                         max_transient_retries=retries, authorization_cap_micros=100, worst_case_micros=10,
                         max_records=10, input_micros_per_million_tokens=0, output_micros_per_million_tokens=0)


def execution_permit(config, policy):
    return ExecutionPermit(permit_id="permit-1", run_id=RUN, model_id=config.model_id, scope="frontier_inference",
                           config_sha256=config_digest(config), authorization_sha256="9" * 64,
                           license_receipt_sha256="a" * 64, resource_receipt_sha256="b" * 64,
                           issued_at="2020-01-01T00:00:00Z", expires_at="2099-01-01T00:00:00Z", approved=True,
                           attempt_policy_sha256=None if policy is None else config_digest(policy))


class Counter:
    sha256 = "7" * 64

    def request_tokens(self, payload):
        return 10

    def completion_tokens(self, content):
        return 5


class RecordingLedger:
    authorization_id = "auth-1"
    cap = 100

    def __init__(self):
        self.reserved, self.reconciled, self.compute = [], [], []

    def reserve(self, attempt_id, worst_case_micros, *, category):
        self.reserved.append((attempt_id, worst_case_micros, category))

    def reconcile(self, attempt_id, *, actual_micros, state, usage_units=None, receipt_id=None,
                  compute_seconds=None):
        self.reconciled.append((attempt_id, actual_micros, state, usage_units))
        self.compute.append(compute_seconds)


def envelope(content, finish_reason="stop"):
    return TransportResponse(json.dumps({
        "model": "stub-model",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}).encode("utf-8"))


class ScriptedTransport:
    """Each physical call consumes the next scripted step: a response or an exception."""

    def __init__(self, *steps):
        self.steps, self.calls = list(steps), 0

    def __call__(self, config, payload):
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def frontier_adapter(transport, *, retries=1, allow_execution=True):
    config, policy, ledger = frontier_config(), attempt_policy(retries), RecordingLedger()
    registry = build_registry({"frontier": config}, {"frontier": execution_permit(config, policy)}, run_id=RUN,
                              transports={"frontier": transport}, counters={"frontier": Counter()},
                              allow_execution=allow_execution,
                              policies={"frontier": policy} if allow_execution else None,
                              ledgers={"frontier": ledger} if allow_execution else None)
    return registry, ledger


def test_one_transient_failure_then_success_records_two_physical_attempts():
    transport = ScriptedTransport(TransportFault(transient=True), envelope(EMAIL_CONTENT))
    registry, ledger = frontier_adapter(transport)
    adapter = registry["frontier"]
    p = adapter(make_record(EMAIL_MESSAGE, "r1"))
    assert p.status == "ok" and [(s.start, s.end, s.label) for s in p.spans] == [(8, 29, "EMAIL")]
    assert transport.calls == 2
    # Two reservations of worst case 10 each; the second is categorised as a retry.
    assert [(w, c) for _, w, c in ledger.reserved] == [(10, "inference"), (10, "retry")]
    first, second = adapter.last_attempts
    assert (first.ordinal, first.status, first.error_code, first.retry_reason) == (1, "failed", "backend_failure",
                                                                                  "transient_transport")
    assert first.physical_may_have_started is True and first.liability_status == "unknown"
    assert (second.ordinal, second.status, second.input_tokens, second.output_tokens) == (2, "ok", 10, 5)
    # Both attempts are reconciled and retained; usage units 10 + 5 = 15 only on the call that reported usage.
    assert [(state, units) for _, _, state, units in ledger.reconciled] == [("failed", None), ("succeeded", 15)]
    # Both attempts entered the operation, so each carries a measured, non-negative time proxy.
    assert len(ledger.compute) == 2 and all(type(s) is float and s >= 0 for s in ledger.compute)
    assert p.attempt_id == second.attempt_id == ledger.reserved[1][0]
    assert p.usage_ref == second.attempt_id


def test_malformed_content_is_never_retried():
    transport = ScriptedTransport(envelope("this is not json"), envelope(EMAIL_CONTENT))
    registry, ledger = frontier_adapter(transport)
    p = registry["frontier"](make_record(EMAIL_MESSAGE, "r1"))
    assert p.status == "invalid_output" and p.error_code == "invalid_output" and p.spans == ()
    assert transport.calls == 1 and len(ledger.reserved) == 1


def test_second_transient_failure_fails_without_a_third_attempt():
    transport = ScriptedTransport(TransportFault(transient=True), TransportFault(transient=True),
                                  envelope(EMAIL_CONTENT))
    registry, ledger = frontier_adapter(transport)
    adapter = registry["frontier"]
    p = adapter(make_record(EMAIL_MESSAGE, "r1"))
    assert p.status == "failed" and p.error_code == "backend_failure"
    assert transport.calls == 2 and len(ledger.reserved) == 2 and len(adapter.last_attempts) == 2


def test_non_transient_transport_failure_is_not_retried():
    transport = ScriptedTransport(TransportFault(transient=False), envelope(EMAIL_CONTENT))
    registry, ledger = frontier_adapter(transport)
    p = registry["frontier"](make_record(EMAIL_MESSAGE, "r1"))
    assert p.status == "failed" and transport.calls == 1 and len(ledger.reserved) == 1


def test_truncated_completion_is_terminal_truncated():
    transport = ScriptedTransport(envelope(EMAIL_CONTENT, finish_reason="length"), envelope(EMAIL_CONTENT))
    registry, _ = frontier_adapter(transport)
    p = registry["frontier"](make_record(EMAIL_MESSAGE, "r1"))
    assert p.status == "invalid_output" and p.error_code == "truncated" and p.spans == ()
    assert transport.calls == 1


def test_one_prediction_per_input_record_including_failures():
    # Fixed denominator: 3 inputs -> 3 predictions per arm, in input order, failures included.
    records = [make_record(EMAIL_MESSAGE, "r1"), make_record("account_id=AC-48213", "r2"),
               make_record("phone: +14155550123", "r3")]
    transport = ScriptedTransport(envelope(EMAIL_CONTENT), TransportFault(transient=False), envelope("{oops"))
    registry, _ = frontier_adapter(transport, retries=0)
    assert set(registry) == {"regex", "frontier"}
    for arm, adapter in registry.items():
        predictions = [adapter(record) for record in records]
        assert [p.record_id for p in predictions] == ["r1", "r2", "r3"]
        assert [p.content_sha256 for p in predictions] == [r.content_sha256 for r in records]
        assert {p.arm for p in predictions} == {arm}
        if arm == "frontier":
            assert [p.status for p in predictions] == ["ok", "failed", "invalid_output"]


def test_registry_without_execution_authority_fails_closed_without_calling_transport():
    transport = ScriptedTransport(envelope(EMAIL_CONTENT))
    registry, _ = frontier_adapter(transport, allow_execution=False)
    p = registry["frontier"](make_record(EMAIL_MESSAGE, "r1"))
    assert p.status == "unavailable" and p.error_code == "permit_required" and transport.calls == 0
    with pytest.raises(AdapterFault) as caught:
        registry["frontier"].preflight((make_record(EMAIL_MESSAGE, "r1"),))
    assert caught.value.code == "permit_required"


def test_policy_digest_not_bound_by_permit_is_rejected_at_build():
    config, policy = frontier_config(), attempt_policy()
    with pytest.raises(ValueError, match="attempt_policy_mismatch"):
        build_registry({"frontier": config}, {"frontier": execution_permit(config, None)}, run_id=RUN,
                       transports={"frontier": ScriptedTransport()}, counters={"frontier": Counter()},
                       allow_execution=True, policies={"frontier": policy},
                       ledgers={"frontier": RecordingLedger()})


def test_finetuned_arm_requires_base_pair():
    config = frontier_config()
    with pytest.raises(ValueError, match="base_fine_pair_required"):
        build_registry({"finetuned": config}, {"finetuned": execution_permit(config, None)}, run_id=RUN)
