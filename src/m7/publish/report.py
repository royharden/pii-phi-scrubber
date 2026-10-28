"""Static aggregate report; arbitrary result strings are never interpolated."""

from html import escape
from math import isfinite
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .gate import PublicationDecision

ARMS = ("regex", "frontier", "base", "finetuned")
COUNTS = ("corpus_N", "eligible_N", "attempted_N", "answered_N", "error_N", "unattempted_N", "publication_suppressed_N")
STATUSES = {"measured", "not_measured", "measured_incomplete"}
COST_STATES = ("known", "partially_known", "unknown", "not_measured")
INTERVAL_STATES = {"insufficient_units": "insufficient: fewer than 20 effective blocks",
                   "insufficient_valid_draws": "insufficient: fewer than 1,800 valid draws"}


def _number(value: object) -> str:
    if type(value) in (int, float) and isfinite(value):
        return escape(str(value))
    return "not measured"


def _metric(value: object) -> str:
    """A ratio cell. A zero denominator reads N/A with its fraction; a cell that
    never ran stays "not measured". Neither is ever shown as 0 or 1."""
    if not isinstance(value, Mapping):
        return _number(value)
    if type(value.get("value")) in (int, float) and isfinite(value["value"]):
        return _number(value["value"])
    reason = value.get("null_reason")
    numerator, denominator = value.get("numerator"), value.get("denominator")
    if (reason == "zero_denominator" and denominator == 0 and type(numerator) is int
            and type(denominator) is int):
        return f"N/A ({numerator}/{denominator})"
    defined, count = value.get("defined_classes"), value.get("class_count")
    if reason == "undefined_class" and type(defined) is int and type(count) is int:
        return f"N/A ({defined}/{count} classes defined)"
    return "not measured"


def _interval_state(interval: object) -> str:
    """Fixed wording; an undefined interval says why instead of looking unmeasured."""
    if not isinstance(interval, Mapping):
        return "not measured"
    bounds = interval.get("interval")
    if (isinstance(bounds, list) and len(bounds) == 2
            and all(type(v) in (int, float) and isfinite(v) for v in bounds)):
        return "defined"
    reason = interval.get("null_reason")
    return INTERVAL_STATES.get(reason, "not measured") if isinstance(reason, str) else "not measured"


def _cost_state(cost: object) -> str:
    status = cost.get("status") if isinstance(cost, Mapping) else None
    return status if isinstance(status, str) and status in COST_STATES else "unknown"


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
                f"<td>{_metric(quality.get(key))}</td>"
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
                f"<td>{_number(bounds[1])}</td><td>{_interval_state(interval)}</td></tr>")
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
            harms.append(f"<tr><th>{arm}</th><td>{key}</td><td>{_metric(value)}</td>"
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
            + "</table><h2>Quality</h2><p>N/A (numerator/denominator) marks an undefined metric "
            "with a zero denominator; a macro N/A counts the classes that are defined. "
            "Not measured marks a value that is unavailable: never run, not reconciled "
            "or not computed. Neither is ever zero.</p>"
            "<table><tr><th>Arm</th><th>Slice</th><th>Class</th>" + "".join(f"<th>{key}</th>" for key in keys)
            + "</tr>" + "".join(metrics) + "</table><h2>Leaks, overredaction and availability</h2>"
            "<table><tr><th>Arm</th><th>Measure</th><th>Value</th><th>Numerator</th><th>Denominator</th></tr>"
            + "".join(harms) + "</table><h2>Timing, cost and uncertainty</h2>"
            "<p>Only explicitly measured timing, reconciled costs and defined cluster intervals "
            "are evidence. Missing values remain unavailable. See detailed locked-edition tables below when supplied.</p>"
            "<p>Intervals below remain unavailable with fewer than 20 effective blocks or 1,800 valid draws. "
            "Development intervals are not held-out evidence.</p><table><tr><th>Measure</th><th>Blocks</th>"
            "<th>Valid draws</th><th>Lower</th><th>Upper</th><th>Interval</th></tr>" + "".join(uncertainty) + "</table>"
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
    def tr_interval(labels, interval):
        row = tr(labels, [interval.get(k) for k in ('effective_blocks', 'executed_draws', 'valid_draws', 'undefined_draws')]
                 + list(interval.get('interval') or (None, None)))
        return row[:-len('</tr>')] + '<td>' + escape(_interval_state(interval)) + '</td></tr>'
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
                    interval_rows.append(tr_interval((arm, scope, group, metric), quality.get(metric) or {}))
    output.append('<h2>Absolute paired-block uncertainty</h2><p>2,000 predeclared draws; 95% percentile intervals. '
                  'Fewer than 20 blocks or 1,800 valid draws leaves the interval undefined. Undefined draws are counted.</p>')
    output.append(table(('Arm', 'Scope', 'Class', 'Metric', 'Blocks', 'Executed', 'Valid', 'Undefined', 'Lower', 'Upper', 'Interval'), interval_rows))
    pairs = []
    for scope in ('total', 'normal', 'challenge'):
        values = (bundle.get('paired') or {}).get(scope) or {}
        for metric in ('precision', 'recall', 'f1'):
            pairs.append(tr_interval((scope, 'macro ' + metric), values.get('macro', {}).get(metric) or {}))
    output.append('<h2>Fine minus base, same record/block draws</h2>' + table(
        ('Scope', 'Metric', 'Blocks', 'Executed', 'Valid', 'Undefined', 'Lower', 'Upper', 'Interval'), pairs))
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
                # The value cell may read N/A (0/0) rather than a number.
                harm_rows.append('<tr>' + ''.join('<th>' + escape(label) + '</th>' for label in (row['arm'], scope, key))
                                 + '<td>' + _metric(point) + '</td>'
                                 + ''.join('<td>' + _number(v) + '</td>' for v in
                                           [point.get('numerator'), point.get('denominator'),
                                            *(ci.get('interval') or (None, None))])
                                 + '<td>' + escape(_interval_state(ci)) + '</td></tr>')
    for scope in ('total', 'normal', 'challenge'):
        values = (bundle.get('paired') or {}).get(scope) or {}
        for group in ('NAME', 'EMAIL', 'PHONE', 'ACCOUNT_ID', 'micro'):
            quality = values.get('micro', {}) if group == 'micro' else values.get('per_class', {}).get(group, {})
            for key in ('precision', 'recall', 'f1'):
                ci = quality.get(key) or {}
                paired_quality.append(tr((scope, group, key), [ci.get(k) for k in ('valid_draws', 'undefined_draws')]
                                         + list(ci.get('interval') or (None, None)))[:-len('</tr>')]
                                      + '<td>' + escape(_interval_state(ci)) + '</td></tr>')
    output.append('<h2>Failure-aware harm rates by slice</h2>' + table(
        ('Arm', 'Scope', 'Measure', 'Value', 'Numerator', 'Denominator', 'Lower95', 'Upper95', 'Interval'), harm_rows))
    output.append('<h2>Paired class and micro differences</h2>' + table(
        ('Scope', 'Class', 'Metric', 'Valid', 'Undefined', 'Lower95', 'Upper95', 'Interval'), paired_quality))
    secondary = []
    for row in rows:
        diagnostic = row.get('successful_only') or {}
        for group in ('micro', 'macro'):
            quality = diagnostic.get(group) or {}
            secondary.append('<tr><th>' + escape(row['arm']) + '</th><th>' + group + '</th>'
                             + ''.join('<td>' + _metric(quality.get(m)) + '</td>' for m in ('precision', 'recall', 'f1'))
                             + '</tr>')
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
    output.append('<p>Cost status: ' + _cost_state(cost) + '.</p>')
    sources = cost.get('amount_sources') if isinstance(cost.get('amount_sources'), Mapping) else {}
    output.append('<p>Attempt amounts from authenticated receipts (actual): ' + _number(sources.get('actual'))
                  + '; reservation estimates still held as liability (estimated): ' + _number(sources.get('estimated'))
                  + '.</p><p>Known compute seconds: ' + _number(cost.get('known_compute_seconds'))
                  + '; attempts without compute time: ' + _number(cost.get('unknown_compute_attempts'))
                  + '. Compute time is a resource measure; no cost figure is derived from it.</p>')
    # Same reconciliation condition as the adoption cost gate, not status alone.
    if not (_cost_state(cost) == 'known' and cost.get('unknown_attempts') == 0 and cost.get('scope_complete') is True
            and cost.get('over_cap') is False and isinstance(cost.get('currency'), str)):
        output.append('<p>Cost is not fully known; no total or per-record cost claim is made.</p>')
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
                  'amortization is invented.</p>' + table(('Arm', 'Status', *arm_cost_keys), [tr((row['arm'], _cost_state(row.get('cost'))),
                  [(row.get('cost') or {}).get(key) for key in arm_cost_keys]) for row in rows]))
    timing = bundle.get('timing') or {}
    timing_rows = []
    timing_keys = ('cold_startup_ms', 'intended_samples_N', 'attempted_samples_N', 'answered_samples_N',
                   'failed_samples_N', 'unattempted_samples_N', 'attempt_metadata_missing_N',
                   'all_attempt_p50_ms', 'all_attempt_p95_ms', 'successful_only_p50_ms',
                   'successful_only_p95_ms', 'attempts_per_second', 'answered_per_second')
    for row in timing.get('arms', []):
        arm = row.get('arm')
        if arm not in ARMS:
            continue
        status = row.get('status')
        status = status if status in ('measured', 'not_measured', 'measured_incomplete', 'unavailable_or_partial') else 'not_measured'
        timing_rows.append(tr((arm, 'network frontier' if arm == 'frontier' else 'offline local', status), [row.get(k) for k in timing_keys]))
    output.append('<h2>Controlled concurrency-1 timing</h2><p>Three fixed-order warmed passes; detector, validation '
                  'and renderer included. Gold safety/scoring/bootstrap overhead is separate. Frontier includes '
                  'network/provider latency. Isolated cold figures measure process/init handshake; model-load-only '
                  'and provider-server startup remain unknown. Required parent transport/native guards remain in '
                  'the supervised end-to-end call boundary. Missing outputs are not performance wins.</p>')
    output.append(table(('Arm', 'Execution', 'Coverage', *timing_keys), timing_rows))
    if timing.get('schema_version') == 'IsolatedTimingResult/v1':
        output.append('<p>Campaign totals include primary and timing calls, retries and unresolved liabilities. '
                      'Per-arm cost rows describe primary inference only. Primary quality is unchanged; no '
                      'timing prediction enters quality/adoption scoring.</p>')
    timing_slices = []
    subset_keys = ('intended_samples_N', 'attempted_samples_N', 'answered_samples_N', 'failed_samples_N',
                   'unattempted_samples_N', 'attempt_metadata_missing_N',
                   'parent_control_overhead_ms',
                   'protocol_elapsed_seconds', 'protocol_answered_per_second',
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
    def floor_cell(row, key):
        # Observed precision/recall carry their fraction so 0/0 reads N/A, not "not measured".
        if key in ('precision', 'recall'):
            return _metric({'value': row.get(key), 'numerator': row.get(key + '_numerator'),
                            'denominator': row.get(key + '_denominator'), 'null_reason': row.get(key + '_null_reason')})
        return _number(row.get(key))
    output.append(table(('Class', *floor_keys), ['<tr><th>' + escape(row['label']) + '</th>'
                  + ''.join('<td>' + floor_cell(row, key) + '</td>' for key in floor_keys) + '</tr>'
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
