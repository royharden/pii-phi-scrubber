"""Validate by default; execute only after separate runtime/resource authorization."""

import argparse
from pathlib import Path
import sys

from _common import emit, guarded
from m7.training import execute_training, validate_training_plan
from m7.training.artifacts import inspect_artifacts, load_object


def _split_training_host(arguments):
    """Remove one explicit `--training-host module:factory`; campaign_main never sees it."""
    if any(a.startswith("--training-host=") for a in arguments):
        raise ValueError("training_host_requires_separate_value")
    if "--training-host" not in arguments:
        return arguments, None
    index = arguments.index("--training-host")
    if index + 1 >= len(arguments):
        raise ValueError("training_host_value_required")
    rest = arguments[:index] + arguments[index + 2:]
    if "--training-host" in rest:
        raise ValueError("training_host_specified_twice")
    return rest, arguments[index + 1]


def _load_training_host(spec):
    """Explicit operator-supplied trusted code, as eval.py --operator-host. None means refused."""
    import importlib
    import re
    from m7.training.campaign import CampaignHost
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*", spec):
        raise ValueError("trusted_training_host_module_required")
    module, factory = spec.split(":")
    try:
        host = getattr(importlib.import_module(module), factory)()
    except Exception:
        return None
    # Same contract prepare_campaign enforces (training/campaign.py:254), checked up front.
    if (not isinstance(host, CampaignHost) or host.isolation_guard is None
            or not callable(host.verify_receipt)):
        return None
    return host


def main(argv=None, *, campaign_host=None, timing_snapshot_provider=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["campaign"]:
        from m7.training.campaign_cli import campaign_main
        rest, spec = _split_training_host(arguments[1:])
        if spec is not None:
            if campaign_host is not None:
                raise ValueError("training_host_specified_twice")
            campaign_host = _load_training_host(spec)
            if campaign_host is None:
                emit({"status": "unavailable", "reason": "authenticated_training_host_unavailable",
                      "product_acceptance": False})
                return 3
        result = campaign_main(rest, host=campaign_host, timing_snapshot_provider=timing_snapshot_provider)
        emit(result)
        return 3 if result.get("status") == "unavailable" else 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--execute", action="store_true",
                      help="future authorized runtime only; forbidden during Dirty Mode")
    parser.add_argument("--staging-root", type=Path)
    args = parser.parse_args(arguments)
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
