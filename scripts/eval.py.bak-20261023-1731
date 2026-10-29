"""Offline development evaluation. Sealed editions require a future custody entrypoint."""

import argparse
from pathlib import Path

from _common import emit, guarded
from demo import development_records
from m7.detectors.regex import detect_regex
from m7.publish import gate_record, write_report
from m7.runner import run_offline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", choices=("development",), required=True)
    parser.add_argument("--arms", choices=("regex", "none"), default="none")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    records = development_records()
    adapters = {"regex": lambda record: detect_regex(record, run_id="development")} if args.arms == "regex" else {}
    bundle = run_offline(records, adapters, publication_gate=lambda r, g, v: gate_record(r, g, v).as_dict())
    write_report(bundle, args.out)
    emit({"status": "development_report_written", "corpus_N": len(records), "held_out_result": False})
    return 0


if __name__ == "__main__":
    guarded(main)
