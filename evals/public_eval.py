"""Independent public-development controls; no sealed inputs or model execution.

Run with Python 3.12: python evals/public_eval.py --out <new-directory>.
Only fixed fictional development examples are used. Results contain check names,
counts and enums. Failed assertions never serialize source/exception bodies.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from m7.contracts import Prediction, Span, make_record  # noqa: E402
from m7.eval.bootstrap import metric_intervals  # noqa: E402
from m7.eval import Observation  # noqa: E402
from m7.ledger import BudgetExceeded, ReservationLedger  # noqa: E402
from m7.publish import artifact_is_safe, gate_record  # noqa: E402
from m7.runner import EvaluationRecord, run_offline  # noqa: E402


def require(condition: bool) -> None:
    if not condition:
        raise AssertionError("public_control_failed")


def fixtures() -> tuple[EvaluationRecord, ...]:
    # Hand-derived half-open offsets: 7+11, 6+18, 6+15, 8+8.
    definitions = (
        ("person=Fable Rowan", 7, 18, "NAME"),
        ("email=fable@example.test", 6, 24, "EMAIL"),
        ("phone=+1-202-555-0119", 6, 21, "PHONE"),
        ("account=ACCT-771", 8, 16, "ACCOUNT_ID"),
    )
    rows = [EvaluationRecord(make_record(message, f"public-control-{i}"),
                            (Span(start=start, end=end, label=label),),
                            "public-control-block", "normal")
            for i, (message, start, end, label) in enumerate(definitions)]
    rows.append(EvaluationRecord(make_record("latency=271ms", "public-benign"), (),
                                 "public-control-block", "challenge"))
    return tuple(rows)


def predict(record, spans):
    return Prediction(run_id="development", record_id=record.record_id,
                      content_sha256=record.content_sha256, arm="regex",
                      model_id="public-control-fake", attempt_id="public-attempt",
                      status="ok", spans=tuple(spans))


def controls() -> dict[str, bool]:
    rows = fixtures()
    gold = {row.record.record_id: row.gold for row in rows}
    results = {}

    def exercise(name, operation):
        try:
            operation()
        except Exception:
            results[name] = False
        else:
            results[name] = True

    def evaluate(adapter):
        return run_offline(rows, {"regex": adapter},
                           publication_gate=lambda r, g, v: gate_record(r, g, v).as_dict())

    def exact():
        bundle = evaluate(lambda record: predict(record, gold[record.record_id]))
        row = bundle["arms"][0]
        require((row["attempted_N"], row["answered_N"], row["error_N"]) == (5, 5, 0))
        require(row["metrics"]["micro"]["tp"] == 4)
        require(row["metrics"]["micro"]["f1"]["value"] == 1.0)
        require(row["metrics"]["residual_sensitive_codepoints"]["numerator"] == 0)
        require(row["publication_suppressed_N"] == 0)
        for unavailable in bundle["arms"][1:]:
            require(unavailable["measurement_status"] == "not_measured")
            require(unavailable["metrics"] is None and unavailable["timing"] is None)

    def partial():
        def adapter(record):
            spans = gold[record.record_id]
            if record.record_id == "public-control-0":
                spans = (Span(start=7, end=17, label="NAME"),)
            return predict(record, spans)
        row = evaluate(adapter)["arms"][0]
        require(tuple(row["metrics"]["micro"][key] for key in ("tp", "fp", "fn")) == (3, 1, 1))
        require(row["metrics"]["residual_sensitive_codepoints"]["numerator"] == 1)
        require(row["publication_suppressed_N"] == 1)

    def wrong_label():
        def adapter(record):
            spans = gold[record.record_id]
            if record.record_id == "public-control-0":
                spans = (Span(start=7, end=18, label="EMAIL"),)
            return predict(record, spans)
        row = evaluate(adapter)["arms"][0]
        require(tuple(row["metrics"]["micro"][key] for key in ("tp", "fp", "fn")) == (3, 1, 1))
        require(row["metrics"]["residual_sensitive_codepoints"]["numerator"] == 0)

    def failure():
        def adapter(record):
            if record.record_id in ("public-control-0", "public-benign"):
                raise RuntimeError("discard-this-provider-body")
            return predict(record, gold[record.record_id])
        bundle = evaluate(adapter)
        row = bundle["arms"][0]
        require((row["corpus_N"], row["answered_N"], row["error_N"]) == (5, 3, 2))
        require(row["measurement_status"] == "measured_incomplete")
        require(row["metrics"]["records_with_residual"]["numerator"] == 1)
        require(row["metrics"]["unavailable"]["numerator"] == 2)
        require(row["metrics"]["micro"]["recall"]["value"] == 0.75)
        require("discard-this-provider-body" not in json.dumps(bundle))

    def insufficient_clusters():
        observations = [Observation(row.record.record_id, row.block_id, row.slice_name,
                                    len(row.record.log.message), row.gold, row.gold, True, True)
                        for row in rows]
        interval = metric_intervals(observations)["micro"]["f1"]
        require(interval["interval"] is None and interval["null_reason"] == "insufficient_units")
        require(interval["executed_draws"] == 0 and interval["effective_blocks"] == 1)

    def leak_scan():
        sources = tuple((row.record, row.gold) for row in rows)
        require(not artifact_is_safe("fable%40example.test", sources))
        require(artifact_is_safe("<p>public control: suppressed</p>", sources))

    for name, operation in (("exact_and_unrun", exact), ("partial_no_overlap_credit", partial),
                            ("wrong_label_no_exact_credit", wrong_label),
                            ("fixed_population_failures", failure),
                            ("insufficient_independent_blocks", insufficient_clusters),
                            ("escaped_leak_negative_control", leak_scan)):
        exercise(name, operation)
    return results


def sqlite_journey(directory: Path) -> bool:
    """Two independent connections race; only one 7-micro reservation fits cap 10."""
    path = directory / "m7-public-ledger.sqlite3"
    ledger = ReservationLedger(path, cap_micros=10, authorization_id="m7-public-cap")
    ledger.initialize()

    def reserve(attempt):
        try:
            ReservationLedger(path, cap_micros=10, authorization_id="m7-public-cap").reserve(
                attempt, 7, category="inference")
            return attempt
        except BudgetExceeded:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = [result for result in pool.map(reserve, ("m7-a", "m7-b")) if result]
    require(len(winners) == 1)
    ledger.reconcile(winners[0], actual_micros=None, state="cancelled", compute_seconds=1.25)
    reopened = ReservationLedger(path, cap_micros=10, authorization_id="m7-public-cap").summary()
    require((reopened["remaining_micros"], reopened["unresolved_liability_micros"]) == (3, 7))
    require(reopened["economic_total"] is None)
    require(reopened["by_category"]["inference"]["known_compute_seconds"] == 1.25)
    return True


def cli_journey(directory: Path) -> bool:
    for name, arguments in (("demo", ("--offline",)),
                            ("eval", ("--edition", "development", "--arms", "regex"))):
        target = directory / f"{name}.html"
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / f"{name}.py"),
                                 *arguments, "--out", str(target)], capture_output=True, timeout=90)
        require(result.returncode == 0)
        require(json.loads(result.stdout)["held_out_result"] is False)
        require(target.is_file() and target.read_text(encoding="utf-8").startswith("<!doctype html>"))
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    results = controls()
    for name, operation in (("sqlite_durable_cap_race", sqlite_journey), ("public_cli_e2e", cli_journey)):
        try:
            results[name] = operation(args.out)
        except Exception:
            results[name] = False
    summary = {"schema_version": "PublicEval/v1", "evidence_kind": "public_development_controls",
               "model_execution": False, "held_out_result": False, "product_acceptance": False,
               "passed": sum(results.values()), "failed": sum(not value for value in results.values()),
               "checks": results}
    encoded = json.dumps(summary, sort_keys=True)
    (args.out / "summary.json").write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
