"""Offline W8 preparation display; D11 owns the sole readiness assessment."""
from __future__ import annotations

import json
from html import escape
from pathlib import Path


def _canonical(readiness):
    # Importing this consumer does not assess, discover or activate anything.
    from m7.experiment.readiness import ExperimentReadiness

    try:
        if type(readiness) is ExperimentReadiness:
            # Serializer warnings can include source values from forged models.
            # Raise inside this boundary so only the fixed refusal escapes.
            encoded = readiness.model_dump_json(warnings='error')
        elif type(readiness) is dict:
            encoded = json.dumps(readiness, allow_nan=False)
        else:
            raise ValueError('canonical_readiness_required')
        # Revalidate even model_construct/model_copy instances. The canonical
        # model alone owns holds, enums, accounting and no-execution invariants.
        return ExperimentReadiness.model_validate_json(encoded)
    except Exception:
        raise ValueError('canonical_readiness_required') from None


def render_acceptance_packet(readiness) -> str:
    """Render only canonical enums/counts; never source-bearing diagnostics.

    This inventory is readiness/mock evidence. It cannot grant execution, release
    a hold, or constitute the future nonauthoring W8 review.
    """
    facts = _canonical(readiness)
    checks = ''.join('<tr><th>' + escape(row.name) + '</th><td>' + escape(row.state)
                     + '</td><td>' + escape(row.reason) + '</td></tr>' for row in facts.checks)
    holds = ''.join('<li>' + escape(hold) + ': held</li>' for hold in facts.held_decisions)
    blockers = ''.join('<li>' + escape(name) + '</li>' for name in facts.blockers)
    arms = ''.join('<tr><th>' + arm + '</th><td>NOT_MEASURED</td></tr>'
                   for arm in ('regex', 'frontier', 'base', 'finetuned'))
    accounting = []
    for row in facts.accounting:
        accounting.append('<tr><th>' + escape(row.arm) + '</th>'
                          + ''.join('<td>' + str(getattr(row, key)) + '</td>' for key in
                                    ('corpus_N', 'attempted_N', 'answered_N', 'error_N', 'unattempted_N'))
                          + '</tr>')

    def amount(value):
        return 'unknown' if value is None else str(value)

    cost_rows = ''.join('<tr><th>' + key + '</th><td>' + amount(getattr(facts.cost, key)) + '</td></tr>'
                        for key in ('provider_cash_total_micros', 'unresolved_liability_micros',
                                    'economic_total_micros'))
    return ("<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>M7 W8 acceptance preparation</title>"
            "<h1>NOT_READY — W8 acceptance preparation</h1>"
            "<p>Evidence kind: " + escape(facts.evidence_kind) + ". No actual model execution, "
            "execution permission or product acceptance. This is an inventory, not an independent verdict.</p>"
            "<h2>Canonical prerequisite checks</h2><table><tr><th>Check</th><th>State</th><th>Reason</th></tr>"
            + checks + "</table><h2>Held decisions</h2><ul>" + holds
            + "</ul><h2>Blockers</h2><ul>" + blockers + "</ul>"
            "<h2>Actual four-arm scientific results</h2><table><tr><th>Arm</th><th>Measurement</th></tr>"
            + arms + "</table><p>No quality chart or trained-model claim is supplied. "
            "The deterministic regex development demo is separate from a locked four-arm experiment.</p>"
            "<h2>Readiness/mock population accounting</h2>"
            "<p>These supplied counts preserve failures and unattempted records; they are not actual-model results.</p>"
            "<table><tr><th>Arm</th><th>Intended</th><th>Attempted</th><th>Answered</th>"
            "<th>Failed</th><th>Unattempted</th></tr>" + ''.join(accounting)
            + "</table>" + ("" if accounting else "<p>Population evidence missing; counts NOT_MEASURED.</p>")
            + "<h2>Readiness/mock costs</h2><p>Status: " + escape(facts.cost.status)
            + ". Supplied amounts are readiness/mock evidence, not authenticated invoices. "
            "Known zero provider cash does not establish zero economic cost.</p>"
            "<table><tr><th>Measure</th><th>Micro-units</th></tr>" + cost_rows + "</table>"
            "<h2>H6 staffing prerequisites</h2><p>Appoint a fresh nonauthoring final reviewer after actual "
            "model/scientific prerequisites exist. A development-blind custodian and separate nonauthoring "
            "label/provenance auditor are required. Disclose any custodian/reviewer overlap; never self-certify "
            "the custodian's work. Existing development-informed seats must not seal a supposedly blind test.</p>"
            "<p>Inspect exact licenses, model/data/checkpoint/input/config hashes, real training and four-arm "
            "receipts, independent family audit, metric counterexamples, cost reconciliation and a clean "
            "two-minute offline walkthrough before any independent verdict. Mocks and passing local tests "
            "do not close those gates. No privacy or compliance certification is issued.</p></html>")


def write_acceptance_packet(readiness, destination: str | Path) -> None:
    """Create a new, value-free preparation artifact; preserve existing files."""
    document = render_acceptance_packet(readiness)
    with Path(destination).open('x', encoding='utf-8') as handle:
        handle.write(document)


__all__ = ['render_acceptance_packet', 'write_acceptance_packet']
