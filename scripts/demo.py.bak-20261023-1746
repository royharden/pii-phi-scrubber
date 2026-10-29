"""Keyless public-fictional development journey; no model loading or network."""

import argparse
from pathlib import Path

from _common import ROOT, emit, guarded, load_json
from m7.contracts import LogRecord, Span
from m7.detectors.regex import detect_regex
from m7.publish import gate_record, write_report
from m7.render import render
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
    args = parser.parse_args()
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
    write_report(bundle, args.out, decisions=decisions)
    emit({"status": "development_report_written", "corpus_N": len(records),
          "suppressed_cards": sum(not decision.approved for decision in decisions),
          "held_out_result": False})
    return 0


if __name__ == "__main__":
    guarded(main)
