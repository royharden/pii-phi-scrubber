"""Validate by default; execute only after separate runtime/resource authorization."""

import argparse
from pathlib import Path

from _common import emit, guarded
from m7.training import execute_training, validate_training_plan
from m7.training.artifacts import inspect_artifacts, load_object


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--execute", action="store_true",
                      help="future authorized runtime only; forbidden during Dirty Mode")
    parser.add_argument("--staging-root", type=Path)
    args = parser.parse_args()
    plan, permit = load_object(args.plan), load_object(args.authorization)
    if args.execute:
        if args.staging_root is None:
            parser.error("--execute requires --staging-root")
        run = execute_training(plan, permit, root=args.staging_root)
        emit(run)
        return 0 if all(r["status"] == "completed" for r in run["receipts"]) and not run["unattempted_trial_ids"] else 3
    result = validate_training_plan(plan, permit)
    if args.staging_root is not None:
        if plan.get("schema_version") != "TrainingPlan/v2":
            raise ValueError("artifact_inspection_requires_v2")
        inspect_artifacts(plan, args.staging_root.resolve(strict=True))
        result["local_artifacts"] = "verified_not_executed"
    emit(result)
    return 0


if __name__ == "__main__":
    guarded(main)
