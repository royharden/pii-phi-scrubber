"""Publication uses gold in memory; diagnostics never contain source values."""

from dataclasses import dataclass
from hashlib import sha256
from html import escape, unescape
import json
from urllib.parse import quote, unquote

from m7.contracts import LogRecord, RenderResult, Span


@dataclass(frozen=True)
class PublicationDecision:
    approved: bool
    reason: str
    safe_message: str | None = None

    def as_dict(self) -> dict:
        return {"approved": self.approved, "reason": self.reason,
                "safe_message": self.safe_message}


def gate_record(record: LogRecord, gold: tuple[Span, ...],
                rendering: RenderResult) -> PublicationDecision:
    """Reject incomplete coverage, altered structure, or assembled value variants.

    Gold and original strings are never returned, hashed individually, or logged.
    Conservative substring checks can suppress a benign coincidental occurrence.
    Suppression must not change the upstream detection metrics.
    """
    reject = lambda reason: PublicationDecision(False, reason)
    original = record.log.message
    if (sha256(original.encode("utf-8")).hexdigest() != record.content_sha256
            or rendering.content_sha256 != record.content_sha256
            or rendering.record_id != record.record_id):
        return reject("identity_mismatch")
    if not rendering.schema_valid or rendering.error_code or rendering.safe_log is None:
        return reject("invalid_render")
    safe = rendering.safe_log
    if any(getattr(record.log, key) != getattr(safe, key)
           for key in ("timestamp", "level", "event")):
        return reject("structure_changed")
    intervals = rendering.intervals
    previous = 0
    expected = []
    covered: set[int] = set()
    for ordinal, interval in enumerate(intervals, 1):
        if not (previous <= interval.start < interval.end <= len(original)):
            return reject("invalid_intervals")
        allowed = {f"[{label}_{ordinal}]" for label in
                   ("NAME", "EMAIL", "PHONE", "ACCOUNT_ID", "REDACTED")}
        if interval.placeholder not in allowed:
            return reject("invalid_placeholder")
        expected.extend((original[previous:interval.start], interval.placeholder))
        covered.update(range(interval.start, interval.end))
        previous = interval.end
    expected.append(original[previous:])
    if safe.message != "".join(expected):
        return reject("render_mismatch")
    for span in gold:
        if not (0 <= span.start < span.end <= len(original)):
            return reject("invalid_gold")
        if not set(range(span.start, span.end)).issubset(covered):
            return reject("gold_coverage_incomplete")
    assembled = json.dumps(safe.model_dump(mode="json"), ensure_ascii=False)
    surfaces = (assembled, escape(assembled, quote=True), quote(assembled, safe=""),
                unescape(assembled), unquote(assembled), safe.message)
    for span in gold:
        value = original[span.start:span.end]
        variants = {value, escape(value, quote=True), quote(value, safe=""),
                    json.dumps(value, ensure_ascii=True)[1:-1],
                    json.dumps(value, ensure_ascii=False)[1:-1]}
        if any(variant in surface for variant in variants for surface in surfaces):
            return reject("assembled_value_detected")
    return PublicationDecision(True, "approved", safe.message)
