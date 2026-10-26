"""Future authorized training orchestration. Importing this module does no work."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
import os
from pathlib import Path
import time
from typing import Callable, Protocol

from .artifacts import inspect_artifacts, load_object, load_training_data, no_links, tree_sha256
from .validation import digest, integer, now_utc, training_attempt_id, validate_training_plan, validate_training_outcome


class TrainingCancelled(Exception):
    """Cooperative cancellation; contains no source or provider response."""


class TrainingOOM(Exception):
    """Typed engine failure, never a zero-loss successful batch."""


@dataclass(frozen=True)
class EngineResult:
    optimizer_steps: int
    epochs: float
    actual_micros: int | None = None
    billing_receipt_id: str | None = None


@dataclass(frozen=True)
class TrialContext:
    trial: dict
    plan: dict
    paths: dict[str, Path]
    config: dict
    environment: dict
    train_rows: list[dict]
    dev_rows: list[dict]
    output_dir: Path
    heartbeat: Callable[[], None]


class TrainingEngine(Protocol):
    """Trusted injected engine must obey context caps and poll heartbeat each step.

    It writes its final, local-only checkpoint into output_dir / 'checkpoint'.
    No backend exception message may be copied into a receipt.
    """
    def run(self, context: TrialContext) -> EngineResult: ...


def _write_json(path: Path, value: dict) -> None:
    # Immutable event/receipt create: no replace and no successful overwrite.
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def execute_training(plan: dict, permit: dict, *, root: Path | str,
                     engine: TrainingEngine | None = None,
                     cancel: Callable[[], bool] | None = None,
                     clock: Callable[[], datetime] = now_utc,
                     environment_check: Callable[[dict], None] | None = None) -> dict:
    """Execute only when separately authorized after Dirty Mode closes.

    Root must be a dedicated OS-isolated staging area with no held-out access.
    This function does not create that environment or attest permit authenticity.
    A repeated plan/edition is refused rather than silently restarting a trial.
    environment_check (tests/trusted hosts) replaces only the installed-version
    probe and must raise ValueError to refuse; None runs the real check.
    """
    # Detach caller-owned mappings so later mutation cannot rewrite lineage.
    plan = json.loads(json.dumps(plan, allow_nan=False))
    permit = json.loads(json.dumps(permit, allow_nan=False))
    # Injected engines/version probes exercise the contract, not actual-model evidence.
    execution_kind = "mock" if engine is not None or environment_check is not None else "actual_training"
    if plan.get("schema_version") != "TrainingPlan/v2":
        raise ValueError("execution_requires_v2_plan")
    validate_training_plan(plan, permit, at=clock())
    staging = Path(root)
    for part in (staging, *staging.parents):
        no_links(part)
    staging = staging.resolve(strict=True)
    paths, metadata = inspect_artifacts(plan, staging, environment_check=environment_check)
    train_rows = load_training_data(paths["train"], "train")
    dev_rows = load_training_data(paths["dev"], "dev")
    if ({r["record"].content_sha256 for r in train_rows} &
            {r["record"].content_sha256 for r in dev_rows}):
        raise ValueError("train_dev_message_overlap")
    plan_hash, permit_hash = digest(plan), digest(permit)
    # Reserve a permanent, plan-addressed run slot before opening the budget DB.
    # A crash consumes the slot; recovery must account the original attempt.
    runs = staging / "runs"
    no_links(runs)
    runs.mkdir(exist_ok=True)
    run_dir = runs / plan["edition_id"]
    run_dir.mkdir(exist_ok=False)
    _write_json(run_dir / "run-started.json", {
        "schema_version": "TrainingRunStarted/v2", "plan_sha256": plan_hash,
        "execution_kind": execution_kind,
        "permit_sha256": permit_hash, "edition_id": plan["edition_id"],
        "started_at": clock().isoformat(), "trial_ids": [t["trial_id"] for t in plan["trials"]]})
    accounting = staging / "accounting"
    no_links(accounting)
    accounting.mkdir(exist_ok=True)
    from m7.ledger import BudgetExceeded, ReservationLedger
    authority_path = accounting / (permit["authorization_id"] + ".authorization.json")
    no_links(authority_path)
    authority_binding = {"schema_version": "TrainingAccountingAuthority/v1",
                         "permit_sha256": permit_hash, "plan_sha256": plan_hash,
                         "currency": permit["currency"], "cap_micros": permit["cap_micros"]}
    try:
        _write_json(authority_path, authority_binding)
    except FileExistsError:
        if load_object(authority_path) != authority_binding:
            raise ValueError("accounting_authority_mismatch") from None
    db_path = accounting / (permit["authorization_id"] + ".sqlite")
    no_links(db_path)
    ledger = ReservationLedger(db_path, cap_micros=permit["cap_micros"],
                               authorization_id=permit["authorization_id"])
    ledger.initialize()
    if engine is None:
        from .gliner_backend import LocalGLiNEREngine
        engine = LocalGLiNEREngine()
    receipts = []
    cancelled = False
    blocked_reason = None
    for trial_index, trial in enumerate(plan["trials"]):
        if cancelled:
            break
        # Expiry/hash drift before reservation stops without calling the backend.
        if cancel is not None and cancel():
            cancelled = True
            break
        try:
            validate_training_plan(plan, permit, at=clock())
        except ValueError:
            blocked_reason = "permit_not_current"
            break
        try:
            inspect_artifacts(plan, staging, environment_check=environment_check)
        except (ValueError, OSError):
            blocked_reason = "artifact_or_environment_invalid"
            break
        attempt_id = training_attempt_id(plan_hash, trial["trial_id"])
        trial_dir = run_dir / trial["trial_id"]
        trial_dir.mkdir(exist_ok=False)
        reserved = plan["per_trial_worst_case_micros"]
        try:
            ledger.reserve(attempt_id, reserved, category="training")
        except BudgetExceeded:
            blocked_reason = "budget_rejected"
            break
        started = clock()
        started_mono = time.monotonic()
        _write_json(trial_dir / "started.json", {
            "schema_version": "TrainingAttemptStarted/v2", "trial_id": trial["trial_id"],
            "plan_sha256": plan_hash, "permit_sha256": permit_hash,
            "ledger_attempt_id": attempt_id, "reserved_micros": reserved,
            "started_at": started.isoformat(), "trial_index": trial_index})

        def heartbeat() -> None:
            if cancel is not None and cancel():
                raise TrainingCancelled()
            validate_training_plan(plan, permit, at=clock())
            if time.monotonic() - started_mono >= plan["max_seconds_per_trial"]:
                raise TrainingCancelled()

        status, error = "failed", "engine_failure"
        checkpoint_hash, result = None, None
        try:
            heartbeat()
            result = engine.run(TrialContext(
                trial=trial.copy(), plan=json.loads(json.dumps(plan)), paths=paths.copy(),
                config=json.loads(json.dumps(metadata["config"])),
                environment=json.loads(json.dumps(metadata["environment"])), train_rows=train_rows, dev_rows=dev_rows,
                output_dir=trial_dir, heartbeat=heartbeat))
            heartbeat()
            if not isinstance(result, EngineResult):
                raise ValueError("invalid_engine_result")
            integer(result.optimizer_steps, 1, plan["max_steps"])
            if (type(result.epochs) not in (float, int) or not math.isfinite(result.epochs) or
                    not 0 < result.epochs <= plan["max_epochs"]):
                raise ValueError("epoch_cap_exceeded")
            if result.actual_micros is not None:
                integer(result.actual_micros, 0, 2**63 - 1)
                from .validation import identifier
                identifier(result.billing_receipt_id)
            checkpoint_hash = tree_sha256(trial_dir / "checkpoint")
            # Reject a backend that altered its pinned inputs, not just outputs.
            inspect_artifacts(plan, staging, environment_check=environment_check)
            status, error = "completed", None
        except (TrainingCancelled, KeyboardInterrupt):
            status, error, cancelled = "cancelled", "cancelled", True
        except (TrainingOOM, MemoryError):
            status, error = "oom", "out_of_memory"
        except RuntimeError as exc:
            # Includes allocation/loading OOM before the backend train loop.
            # Inspect only in memory; no exception body enters the receipt.
            if "out of memory" in str(exc).lower():
                status, error = "oom", "out_of_memory"
            else:
                status, error = "failed", "engine_failure"
        except Exception:
            # Never persist exception repr/message or an untrusted backend payload.
            status, error = "failed", "engine_failure"
        actual = result.actual_micros if status == "completed" else None
        billing = result.billing_receipt_id if status == "completed" else None
        receipt = {
            "schema_version": "TrainingReceipt/v2", "execution_kind": execution_kind,
            "edition_id": plan["edition_id"], "plan_sha256": plan_hash,
            "permit_sha256": permit_hash, "authorization_id": permit["authorization_id"],
            "artifact_hashes": {k: v["sha256"] for k, v in plan["artifacts"].items()},
            "trial_id": trial["trial_id"], "trial_sha256": digest(trial), "seed": trial["seed"],
            "status": status, "error_code": error, "optimizer_steps": result.optimizer_steps
            if status == "completed" else None, "epochs": result.epochs if status == "completed" else None,
            "checkpoint_sha256": checkpoint_hash if status == "completed" else None,
            "checkpoint_relative_path": (trial_dir / "checkpoint").relative_to(staging).as_posix()
            if status == "completed" else None, "ledger_attempt_id": attempt_id,
            "reserved_micros": reserved, "actual_micros": actual,
            "billing_receipt_id": billing, "cost_status": "known" if actual is not None else "unknown",
            "started_at": started.isoformat(), "finished_at": clock().isoformat(),
            "duration_seconds": max(0.0, time.monotonic() - started_mono),
            "independent_audit": "pending", "m7_02_accepted": False}
        validate_training_outcome(receipt, plan, permit)
        # Persist before reconciling. Crash between these leaves conservative liability.
        _write_json(trial_dir / "receipt.json", receipt)
        ledger.reconcile(attempt_id, actual_micros=actual, receipt_id=billing,
                         usage_units=receipt["optimizer_steps"],
                         # Ledger proxy bound is 0..1e9 s; an out-of-range duration stays unknown.
                         compute_seconds=receipt["duration_seconds"] if receipt["duration_seconds"] <= 10**9 else None,
                         state={"completed": "succeeded", "oom": "failed"}.get(status, status))
        receipts.append(receipt)
    run = {"schema_version": "TrainingRun/v2", "edition_id": plan["edition_id"],
           "evidence_kind": execution_kind,
           "plan_sha256": plan_hash, "permit_sha256": permit_hash,
           "status": "cancelled" if cancelled else "blocked" if blocked_reason else "completed_with_outcomes",
           "blocked_reason": blocked_reason,
           "receipts": receipts, "unattempted_trial_ids": [t["trial_id"] for t in plan["trials"][len(receipts):]],
           "accounting": ledger.summary(), "selection_status": "pending_dev_lock",
           "runtime_acceptance": False}
    _write_json(run_dir / "run.json", run)
    return run
