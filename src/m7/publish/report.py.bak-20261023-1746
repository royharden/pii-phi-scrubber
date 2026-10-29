"""Static aggregate report; arbitrary result strings are never interpolated."""

from html import escape
from math import isfinite
from pathlib import Path
from typing import Mapping, Sequence

from .gate import PublicationDecision

ARMS = ("regex", "frontier", "base", "finetuned")
COUNTS = ("corpus_N", "eligible_N", "attempted_N", "answered_N", "error_N", "unattempted_N", "publication_suppressed_N")
STATUSES = {"measured", "not_measured", "measured_incomplete"}


def _number(value: object) -> str:
    if type(value) in (int, float) and isfinite(value):
        return escape(str(value))
    return "not measured"


def render_report(bundle: Mapping, *, decisions: Sequence[PublicationDecision] = ()) -> str:
    """Present numeric aggregates only. Missing/empty inputs stay visible.

    Safe demo cards must be actual gate decisions passed separately in memory;
    publication fields from a loaded JSON bundle are deliberately not trusted.
    """
    rows = []
    supplied = bundle.get("arms", [])
    supplied = supplied if isinstance(supplied, list) else []
    for arm in ARMS:
        item = next((row for row in supplied if isinstance(row, dict)
                     and row.get("arm") == arm), {})
        status = item.get("measurement_status")
        status = status if status in STATUSES else "not_measured"
        cells = "".join(f"<td>{_number(item.get(key))}</td>" for key in COUNTS)
        rows.append(f"<tr><th>{arm}</th><td>{status}</td>{cells}</tr>")
    cards = []
    for decision in decisions:
        if type(decision) is not PublicationDecision:
            raise TypeError("publication_decision_required")
        if decision.approved and decision.safe_message is not None:
            cards.append("<article><h3>Approved synthetic development rendering</h3><pre>"
                         + escape(decision.safe_message) + "</pre></article>")
        else:
            cards.append("<article><h3>Output suppressed</h3><p>Publication safety check "
                         "did not approve this rendering. The failure remains in upstream metrics."
                         "</p></article>")
    metrics = []
    # Explicit known metric names prevent source-bearing keys or values leaking.
    keys = ("precision", "recall", "f1", "tp", "fp", "fn", "support")
    def quality_rows(arm, values, scope):
        result = []
        per_class = values.get("per_class", {})
        per_class = per_class if isinstance(per_class, dict) else {}
        for group in ("NAME", "EMAIL", "PHONE", "ACCOUNT_ID", "micro", "macro"):
            quality = (per_class.get(group, {})
                       if group not in ("micro", "macro") else values.get(group, {}))
            quality = quality if isinstance(quality, dict) else {}
            result.append(f"<tr><th>{arm}</th><td>{scope}</td><td>{group}</td>" + "".join(
                f"<td>{_number(quality.get(key, {}).get('value') if isinstance(quality.get(key), dict) else quality.get(key))}</td>"
                for key in keys) + "</tr>")
        return result
    harms = []
    uncertainty = []
    def interval_row(label, interval):
        interval = interval if isinstance(interval, dict) else {}
        bounds = interval.get("interval")
        bounds = bounds if isinstance(bounds, list) and len(bounds) == 2 else [None, None]
        return (f"<tr><th>{label}</th><td>{_number(interval.get('effective_blocks'))}</td>"
                f"<td>{_number(interval.get('valid_draws'))}</td><td>{_number(bounds[0])}</td>"
                f"<td>{_number(bounds[1])}</td></tr>")
    harm_keys = ("residual_sensitive_codepoints", "records_with_residual", "benign_codepoints_redacted",
                 "benign_record_overredaction", "unavailable", "unsafe_or_unavailable")
    for arm in ARMS:
        item = next((row for row in supplied if isinstance(row, dict) and row.get("arm") == arm), {})
        values = item.get("metrics")
        values = values if isinstance(values, dict) else {}
        intervals = item.get("intervals", {})
        intervals = intervals if isinstance(intervals, dict) else {}
        uncertainty.append(interval_row(arm + " macro F1", intervals.get("macro_f1")))
        metrics.extend(quality_rows(arm, values, "total"))
        slices = item.get("slices", {})
        for name in ("normal", "challenge"):
            subset = slices.get(name, {}) if isinstance(slices, dict) else {}
            metrics.extend(quality_rows(arm, subset if isinstance(subset, dict) else {}, name))
        for key in harm_keys:
            value = values.get(key, {})
            value = value if isinstance(value, dict) else {}
            harms.append(f"<tr><th>{arm}</th><td>{key}</td><td>{_number(value.get('value'))}</td>"
                         f"<td>{_number(value.get('numerator'))}</td><td>{_number(value.get('denominator'))}</td></tr>")
    uncertainty.append(interval_row("finetuned minus base macro F1", bundle.get("paired_fine_minus_base")))
    return ("<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>M7 synthetic redaction experiment</title><style>body{font:16px system-ui;"
            "max-width:1100px;margin:2rem auto;padding:1rem}table{border-collapse:collapse;"
            "display:block;overflow:auto}td,th{border:1px solid #bbb;padding:.5rem}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border:1px solid #aaa;padding:1rem}</style>"
            "<h1>Synthetic log redaction experiment</h1><p><strong>Development scaffold. "
            "Runtime unverified; no held-out scientific result is established.</strong></p>"
            "<p>Missing measurements remain unavailable. No superiority, privacy guarantee or "
            "compliance certification is claimed. Negative results and failures are valid outcomes.</p>"
            "<h2>Coverage and failures</h2><table><tr><th>Arm</th><th>Status</th>"
            + "".join(f"<th>{key}</th>" for key in COUNTS) + "</tr>" + "".join(rows)
            + "</table><h2>Quality</h2><p>Null and absent values mean not measured, never zero.</p>"
            "<table><tr><th>Arm</th><th>Slice</th><th>Class</th>" + "".join(f"<th>{key}</th>" for key in keys)
            + "</tr>" + "".join(metrics) + "</table><h2>Leaks, overredaction and availability</h2>"
            "<table><tr><th>Arm</th><th>Measure</th><th>Value</th><th>Numerator</th><th>Denominator</th></tr>"
            + "".join(harms) + "</table><h2>Timing, cost and uncertainty</h2>"
            "<p>Controlled timing, reconciled cost and paired cluster confidence intervals are "
            "not established by this scaffold. They require an authorized, locked experiment.</p>"
            "<p>Intervals below remain unavailable with fewer than 20 effective blocks or 1,800 valid draws. "
            "Development intervals are not held-out evidence.</p><table><tr><th>Measure</th><th>Blocks</th>"
            "<th>Valid draws</th><th>Lower</th><th>Upper</th></tr>" + "".join(uncertainty) + "</table>"
            "<h2>Safe development examples</h2>" + ("".join(cards) or "<p>No approved examples supplied.</p>")
            + "<h2>Limits</h2><p>English fictional logs only; NAME, EMAIL, PHONE and ACCOUNT_ID. "
            "Offsets address the original decoded Unicode message (maximum 1,024 codepoints). "
            "Only one message field is transformed. Gold-aware suppression detects annotated "
            "fixture leaks; it cannot establish safety on arbitrary real-world text.</p></html>")


def write_report(bundle: Mapping, destination: Path, *,
                 decisions: Sequence[PublicationDecision] = ()) -> None:
    """Exclusive creation prevents silently replacing a prior experiment edition."""
    document = render_report(bundle, decisions=decisions)
    with destination.open("x", encoding="utf-8") as handle:
        handle.write(document)
