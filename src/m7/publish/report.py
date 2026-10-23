"""Static aggregate report; arbitrary result strings are never interpolated."""

from html import escape
from math import isfinite
from pathlib import Path
from typing import Callable, Mapping, Sequence

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
    qualification = ("Locked-edition execution report. Independent product acceptance remains pending."
                     if bundle.get('schema_version') == 'EvaluationBundle/v2' else
                     "Development scaffold. Runtime unverified; no held-out scientific result is established.")
    document = ("<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>M7 synthetic redaction experiment</title><style>body{font:16px system-ui;"
            "max-width:1100px;margin:2rem auto;padding:1rem}table{border-collapse:collapse;"
            "display:block;overflow:auto}td,th{border:1px solid #bbb;padding:.5rem}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border:1px solid #aaa;padding:1rem}</style>"
            "<h1>Synthetic log redaction experiment</h1><p><strong>" + qualification + "</strong></p>"
            "<p>Missing measurements remain unavailable. No superiority, privacy guarantee or "
            "compliance certification is claimed. Negative results and failures are valid outcomes.</p>"
            "<h2>Coverage and failures</h2><table><tr><th>Arm</th><th>Status</th>"
            + "".join(f"<th>{key}</th>" for key in COUNTS) + "</tr>" + "".join(rows)
            + "</table><h2>Quality</h2><p>Null and absent values mean not measured, never zero.</p>"
            "<table><tr><th>Arm</th><th>Slice</th><th>Class</th>" + "".join(f"<th>{key}</th>" for key in keys)
            + "</tr>" + "".join(metrics) + "</table><h2>Leaks, overredaction and availability</h2>"
            "<table><tr><th>Arm</th><th>Measure</th><th>Value</th><th>Numerator</th><th>Denominator</th></tr>"
            + "".join(harms) + "</table><h2>Timing, cost and uncertainty</h2>"
            "<p>Only explicitly measured timing, reconciled costs and defined cluster intervals "
            "are evidence. Missing values remain unavailable. See detailed locked-edition tables below when supplied.</p>"
            "<p>Intervals below remain unavailable with fewer than 20 effective blocks or 1,800 valid draws. "
            "Development intervals are not held-out evidence.</p><table><tr><th>Measure</th><th>Blocks</th>"
            "<th>Valid draws</th><th>Lower</th><th>Upper</th></tr>" + "".join(uncertainty) + "</table>"
            "<h2>Safe development examples</h2>" + ("".join(cards) or "<p>No approved examples supplied.</p>")
            + "<h2>Limits</h2><p>English fictional logs only; NAME, EMAIL, PHONE and ACCOUNT_ID. "
            "Offsets address the original decoded Unicode message (maximum 1,024 codepoints). "
            "Only one message field is transformed. Gold-aware suppression detects annotated "
            "fixture leaks; it cannot establish safety on arbitrary real-world text.</p></html>")
    if bundle.get('schema_version') == 'EvaluationBundle/v2':
        document = document.replace('</html>', _locked_details(bundle) + '</html>')
    return document


def _locked_details(bundle: Mapping) -> str:
    """Only fixed scopes/keys/enum labels and numeric values reach HTML."""
    def table(headers, rows):
        return '<table><tr>' + ''.join('<th>' + escape(h) + '</th>' for h in headers) + '</tr>' + ''.join(rows) + '</table>'
    def tr(labels, numbers):
        return '<tr>' + ''.join('<th>' + escape(label) + '</th>' for label in labels) + ''.join('<td>' + _number(v) + '</td>' for v in numbers) + '</tr>'
    def state(value):
        return 'passed' if value is True else 'failed' if value is False else 'not evaluated'
    output = ['<h2>Locked-edition accounting</h2><p>Failures and unattempted cells remain in the same intended population. '
              'Successful-only diagnostics never replace unconditional quality. Renderer failures expose the full gold mask; '
              'benign-only failures are unavailable without being called gold leaks.</p>']
    extra = ('pending_N', 'budget_rejected_N', 'adapter_unavailable_N', 'interrupted_unknown_N',
             'cancelled_N', 'preflight_rejected_N', 'physical_attempts_N', 'retry_attempts_N',
             'attempt_metadata_missing_N', 'render_failed_N', 'publication_suppressed_N')
    rows = bundle.get('arms', [])
    output.append(table(('Arm', *extra), [tr((row['arm'],), [row.get(k) for k in extra]) for row in rows]))
    interval_rows = []
    for arm in ARMS:
        item = next((r for r in rows if r.get('arm') == arm), {})
        for scope in ('total', 'normal', 'challenge'):
            values = item.get('intervals') if scope == 'total' else (item.get('slice_intervals') or {}).get(scope)
            values = values or {}
            for group in ('NAME', 'EMAIL', 'PHONE', 'ACCOUNT_ID', 'micro', 'macro'):
                quality = (values.get('per_class', {}).get(group, {}) if group not in ('micro', 'macro') else values.get(group, {}))
                for metric in ('precision', 'recall', 'f1'):
                    interval = quality.get(metric) or {}
                    bounds = interval.get('interval') or (None, None)
                    interval_rows.append(tr((arm, scope, group, metric), [interval.get(k) for k in
                        ('effective_blocks', 'executed_draws', 'valid_draws', 'undefined_draws')] + list(bounds)))
    output.append('<h2>Absolute paired-block uncertainty</h2><p>2,000 predeclared draws; 95% percentile intervals. '
                  'Fewer than 20 blocks or 1,800 valid draws leaves the interval undefined. Undefined draws are counted.</p>')
    output.append(table(('Arm', 'Scope', 'Class', 'Metric', 'Blocks', 'Executed', 'Valid', 'Undefined', 'Lower', 'Upper'), interval_rows))
    pairs = []
    for scope in ('total', 'normal', 'challenge'):
        values = (bundle.get('paired') or {}).get(scope) or {}
        for metric in ('precision', 'recall', 'f1'):
            interval = values.get('macro', {}).get(metric) or {}
            bounds = interval.get('interval') or (None, None)
            pairs.append(tr((scope, 'macro ' + metric), [interval.get(k) for k in
                         ('effective_blocks', 'executed_draws', 'valid_draws', 'undefined_draws')] + list(bounds)))
    output.append('<h2>Fine minus base, same record/block draws</h2>' + table(
        ('Scope', 'Metric', 'Blocks', 'Executed', 'Valid', 'Undefined', 'Lower', 'Upper'), pairs))
    harm_keys = ('residual_sensitive_codepoints', 'records_with_residual', 'benign_codepoints_redacted',
                 'benign_record_overredaction', 'unavailable', 'unsafe_or_unavailable')
    harm_rows = []
    paired_quality = []
    for row in rows:
        for scope in ('total', 'normal', 'challenge'):
            metrics = (row.get('metrics') if scope == 'total' else (row.get('slices') or {}).get(scope)) or {}
            uncertainty = (row.get('intervals') if scope == 'total' else (row.get('slice_intervals') or {}).get(scope)) or {}
            for key in harm_keys:
                point = metrics.get(key) or {}
                ci = uncertainty.get(key) or {}
                harm_rows.append(tr((row['arm'], scope, key), [point.get(k) for k in ('value', 'numerator', 'denominator')]
                                   + list(ci.get('interval') or (None, None))))
    for scope in ('total', 'normal', 'challenge'):
        values = (bundle.get('paired') or {}).get(scope) or {}
        for group in ('NAME', 'EMAIL', 'PHONE', 'ACCOUNT_ID', 'micro'):
            quality = values.get('micro', {}) if group == 'micro' else values.get('per_class', {}).get(group, {})
            for key in ('precision', 'recall', 'f1'):
                ci = quality.get(key) or {}
                paired_quality.append(tr((scope, group, key), [ci.get(k) for k in ('valid_draws', 'undefined_draws')]
                                         + list(ci.get('interval') or (None, None))))
    output.append('<h2>Failure-aware harm rates by slice</h2>' + table(
        ('Arm', 'Scope', 'Measure', 'Value', 'Numerator', 'Denominator', 'Lower95', 'Upper95'), harm_rows))
    output.append('<h2>Paired class and micro differences</h2>' + table(
        ('Scope', 'Class', 'Metric', 'Valid', 'Undefined', 'Lower95', 'Upper95'), paired_quality))
    secondary = []
    for row in rows:
        diagnostic = row.get('successful_only') or {}
        for group in ('micro', 'macro'):
            quality = diagnostic.get(group) or {}
            secondary.append(tr((row['arm'], group), [quality.get(m, {}).get('value') for m in ('precision', 'recall', 'f1')]))
    output.append('<h2>Successful-only diagnostics (secondary)</h2>' + table(('Arm', 'Metric', 'Precision', 'Recall', 'F1'), secondary))
    cost = bundle.get('cost') or {}
    cost_keys = ('attempts_N', 'known_provider_cash_micros', 'provider_cash_total_micros',
                 'unresolved_liability_micros', 'unknown_attempts', 'cap_micros', 'remaining_micros',
                 'electricity_micros', 'hardware_amortization_micros', 'compute_seconds', 'economic_total_micros')
    output.append('<h2>Full experiment cost and unresolved liability</h2><p>Amounts are micro-units of the '
                  'authenticated common invoice currency. Remaining cap is informational; authorizations cannot borrow '
                  'each other\'s budget. Verified zero provider cash does not establish zero electricity, amortization '
                  'or total economic cost. Training and inference scopes must both be present.</p>')
    output.append(table(('Measure', 'Value'), [tr((key,), (cost.get(key),)) for key in cost_keys]))
    currency = cost.get('currency')
    output.append('<p>Currency: ' + (escape(currency) if isinstance(currency, str) and len(currency) == 3 else 'unknown')
                  + '. Complete training/inference scope: ' + state(cost.get('scope_complete'))
                  + '. Authorization overrun: ' + ('yes' if cost.get('over_cap') is True else
                     'no' if cost.get('over_cap') is False else 'unknown') + '.</p>')
    category_keys = ('attempts_N', 'known_provider_cash_micros', 'unresolved_liability_micros', 'unknown_attempts',
                     'known_usage_units', 'unknown_usage_attempts')
    output.append(table(('Category', *category_keys), [tr((category,), [(cost.get('by_category') or {}).get(category, {}).get(key)
                        for key in category_keys]) for category in ('training', 'inference', 'retry', 'failed_trial')]))
    output.append(table(('Attempt state', 'Count'), [tr((key,), ((cost.get('states') or {}).get(key),))
                  for key in ('reserved', 'succeeded', 'failed', 'cancelled', 'unknown')]))
    arm_cost_keys = ('known_provider_cash_micros', 'provider_cash_total_micros', 'unresolved_liability_micros',
                     'unknown_attempts', 'training_allocation_micros', 'economic_total_micros')
    output.append('<p>Per-arm inference cash below reflects immutable attempt-time receipts. Later global '
                  'invoice reconciliation can be known while an arm allocation remains unknown. No training '
                  'amortization is invented.</p>' + table(('Arm', *arm_cost_keys), [tr((row['arm'],),
                  [(row.get('cost') or {}).get(key) for key in arm_cost_keys]) for row in rows]))
    timing = bundle.get('timing') or {}
    timing_rows = []
    timing_keys = ('cold_startup_ms', 'intended_samples_N', 'attempted_samples_N', 'answered_samples_N',
                   'failed_samples_N', 'all_attempt_p50_ms', 'all_attempt_p95_ms', 'successful_only_p50_ms',
                   'successful_only_p95_ms', 'attempts_per_second', 'answered_per_second')
    for row in timing.get('arms', []):
        arm = row.get('arm')
        if arm not in ARMS:
            continue
        timing_rows.append(tr((arm, 'network frontier' if arm == 'frontier' else 'offline local'), [row.get(k) for k in timing_keys]))
    output.append('<h2>Controlled concurrency-1 timing</h2><p>Three fixed-order warmed passes; detector, validation '
                  'and renderer included. Gold safety/scoring/bootstrap overhead is separate. Frontier includes '
                  'network/provider latency; its cold figure is client initialization, not provider-server model load. '
                  'Local cold figures cover model initialization; OS/process cache effects require qualification.</p>')
    output.append(table(('Arm', 'Execution', *timing_keys), timing_rows))
    timing_slices = []
    subset_keys = ('intended_samples_N', 'attempted_samples_N', 'answered_samples_N', 'failed_samples_N',
                   'all_attempt_p50_ms', 'all_attempt_p95_ms', 'answered_per_second')
    for row in timing.get('arms', []):
        if row.get('arm') not in ARMS:
            continue
        for index, data in enumerate(row.get('passes', []), 1):
            timing_slices.append(tr((row['arm'], 'pass ' + str(index)), [data.get(k) for k in subset_keys]))
        for data in row.get('length_slices', []):
            low, high = data.get('minimum'), data.get('maximum')
            label = ('length ' + str(low) + '..' + str(high)) if type(low) is int and type(high) is int else 'undefined length'
            timing_slices.append(tr((row['arm'], label), [data.get(k) for k in subset_keys]))
    output.append(table(('Arm', 'Fixed pass/length slice', *subset_keys), timing_slices))
    hardware = timing.get('hardware') or {}
    output.append('<p>Hardware context: ' + '; '.join(escape(key) + '=' + escape(str(hardware[key]))
                   for key in ('cpu', 'gpu', 'ram_gib', 'driver', 'precision', 'batch_size',
                               'package_lock_sha256', 'environment_sha256') if key in hardware) + '</p>')
    output.append('<p>Evaluator safety/scoring/uncertainty overhead ms: ' + _number(bundle.get('safety_scoring_overhead_ms')) + '</p>')
    adoption = bundle.get('adoption') or {}
    gates = adoption.get('gates') or {}
    output.append('<h2>Pre-test locked adoption rule</h2><p>Floors apply to the total test set only. '
                  'A macro win cannot excuse a weak class. Passing remains a candidate for independent review; '
                  'this report never issues deployment or product acceptance.</p>')
    output.append('<p>' + ('Candidate for independent review.' if adoption.get('status') == 'candidate_only' else
                  'Retain the benchmark and recommend no deployment; missing or failed gates remain visible.') + '</p>')
    output.append(table(('Gate', 'Result'), ['<tr><th>' + escape(key) + '</th><td>' + state(gates.get(key)) + '</td></tr>'
                  for key in ('all_classes_meet_total_set_floors', 'positive_paired_macro_f1', 'no_increased_residual_leak',
                              'zero_structure_failures', 'full_intended_accounting', 'all_four_arms_attempted_full_population',
                              'closed_edition', 'cost_reconciled', 'attempt_lineage_complete')]))
    floor_keys = ('precision', 'precision_floor', 'recall', 'recall_floor', 'recall_lower95', 'recall_lower95_floor')
    output.append(table(('Class', *floor_keys), [tr((row['label'],), [row.get(k) for k in floor_keys])
                  for row in adoption.get('per_class', []) if row.get('label') in ('NAME', 'EMAIL', 'PHONE', 'ACCOUNT_ID')]))
    return ''.join(output)


def write_report(bundle: Mapping, destination: Path, *,
                 decisions: Sequence[PublicationDecision] = (),
                 approve_artifact: Callable[[str], bool]) -> bool:
    """Exclusive creation prevents silently replacing a prior experiment edition."""
    document = render_report(bundle, decisions=decisions)
    approved = approve_artifact(document) is True
    if not approved:
        document = ('<!doctype html><html lang="en"><meta charset="utf-8">'
                    '<title>Output suppressed</title><h1>Output suppressed</h1>'
                    '<p>Artifact validation rejected this document. Upstream failures remain scored.</p></html>')
        if approve_artifact(document) is not True:
            raise ValueError('suppression_card_not_safe_to_publish')
    with destination.open("x", encoding="utf-8") as handle:
        handle.write(document)
    return approved
