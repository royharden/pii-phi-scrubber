"""Keyless public-fictional development journey; no model loading or network."""

import argparse
from pathlib import Path

from _common import ROOT, approved_result, copy_approved_report, emit, guarded, load_json
from m7.contracts import LogRecord, Span
from m7.detectors.regex import detect_regex
from m7.publish import artifact_is_safe, gate_record, write_report
from m7.runner import EvaluationRecord, run_offline


def development_records():
    fixture = load_json(ROOT / "data-development" / "public-fictional.json")
    if fixture.get("schema_version") != "PublicDevelopment/v1":
        raise ValueError("public_fixture_required")
    # One shared development block: these hand-authored examples do not establish
    # independent held-out family clusters or justify a scientific interval.
    return [EvaluationRecord(LogRecord.model_validate(row),
                             tuple(Span.model_validate(span) for span in fixture["gold"][row["record_id"]]),
                             "public-development-fixture", "challenge" if row["record_id"] == "dev-008" else "normal")
            for row in fixture["records"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument('--result', type=Path, help='previously approved four-arm aggregate; never executes models')
    parser.add_argument('--result-sha256')
    parser.add_argument('--approved-report', type=Path)
    parser.add_argument('--report-sha256')
    args = parser.parse_args()
    if args.result or args.approved_report:
        if not args.approved_report or not args.report_sha256:
            raise ValueError('approved_report_and_hash_required')
        if args.result:
            if not args.result_sha256:
                raise ValueError('approved_result_hash_required')
            approved_result(args.result, args.result_sha256)
        copy_approved_report(args.approved_report, args.report_sha256, args.out)
        emit({'status': 'offline_approved_aggregate_rendered', 'held_out_rerun': False,
              'product_acceptance': False})
        return 0
    records = development_records()
    decisions = []
    def gate(record, gold, rendering):
        decision = gate_record(record, gold, rendering)
        decisions.append(decision)
        return decision.as_dict()
    bundle = run_offline(records, {"regex": lambda record: detect_regex(record, run_id="development")},
                         publication_gate=gate)
    # dev-008 contains a documented uncued NAME miss. Its leak is scored by the
    # same runner before publication suppresses the card; no synthetic green result.
    approved = write_report(bundle, args.out, decisions=decisions, approve_artifact=lambda document: artifact_is_safe(
        document, tuple((row.record, row.gold) for row in records)))
    emit({"status": "development_report_written" if approved else 'artifacts_suppressed', "corpus_N": len(records),
          "suppressed_cards": sum(not decision.approved for decision in decisions),
          "held_out_result": False})
    return 0


if __name__ == "__main__":
    guarded(main)
