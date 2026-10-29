"""Stopped-worker accounting recovery. Never restarts training or rewrites history."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Callable, Literal

from pydantic import model_validator

from m7.contracts import Boundary, Digest, Identifier
from m7.ledger import ReservationLedger
from .artifacts import file_sha256, load_object, no_links
from .executor import _write_json
from .selection import authenticate, Verifier
from .validation import digest, now_utc, training_attempt_id, utc, validate_training_outcome, validate_training_plan


class RecoveryAuthorization(Boundary):
    schema_version: Literal["TrainingRecoveryAuthorization/v1"] = "TrainingRecoveryAuthorization/v1"
    authorization_id: Identifier
    edition_id: Identifier
    plan_sha256: Digest
    permit_sha256: Digest
    run_started_sha256: Digest
    stopped_worker_receipt_sha256: Digest
    allowed_action: Literal["account_interrupted_no_restart"]
    approved_by: Identifier
    issued_at: str
    expires_at: str

    @model_validator(mode="after")
    def coherent(self):
        if utc(self.expires_at) <= utc(self.issued_at):
            raise ValueError("invalid_recovery_window")
        return self


def recover_training_run(plan: dict, permit: dict, *, root: Path,
                         authorization: RecoveryAuthorization, verify_receipt: Verifier,
                         clock: Callable[[], datetime] = now_utc) -> dict:
    """Preserve originals, identify interrupted attempts, keep unknown liability.

    The trusted host must prove the original worker is stopped. No PID guessing,
    force killing, lock deletion, new trial reservation or backend call occurs.
    Untouched planned slots are reported, never automatically rerun/reallocated.
    """
    root = root.resolve(strict=True)
    run_dir = root / "runs" / plan["edition_id"]
    for path in (run_dir, run_dir.parent, root, *root.parents):
        no_links(path)
    header_path = run_dir / "run-started.json"
    no_links(header_path)
    header = load_object(header_path)
    if (authorization.edition_id != plan["edition_id"] or authorization.plan_sha256 != digest(plan) or
            authorization.permit_sha256 != digest(permit) or
            authorization.run_started_sha256 != digest(header) or
            header.get("schema_version") != "TrainingRunStarted/v2" or
            header.get("plan_sha256") != digest(plan) or header.get("permit_sha256") != digest(permit) or
            header.get("edition_id") != plan["edition_id"] or
            header.get("trial_ids") != [t["trial_id"] for t in plan["trials"]] or
            not utc(authorization.issued_at) <= clock() < utc(authorization.expires_at)):
        raise ValueError("recovery_authorization_binding_mismatch")
    # Expired training permits may be accounted, never used for new model work.
    validate_training_plan(plan, permit, at=utc(header["started_at"]))
    authenticate(verify_receipt, "training_recovery_authorization", digest(authorization.model_dump(mode="json")))
    authenticate(verify_receipt, "training_worker_stopped", authorization.stopped_worker_receipt_sha256)
    db_path = root / "accounting" / (permit["authorization_id"] + ".sqlite")
    no_links(db_path.parent)
    no_links(db_path)
    attempts = {}
    if db_path.exists():
        # Read before reconciliation so a known late invoice is never erased by
        # an older unknown-cost outcome. URI read-only forbids accidental creation.
        with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            if db.execute("SELECT id,cap FROM authorization").fetchall() != [(permit["authorization_id"], permit["cap_micros"])]:
                raise ValueError("recovery_ledger_authority_mismatch")
            attempts = {row[0]: row[1:] for row in db.execute(
                "SELECT id,reserved,actual,state,usage_units,receipt_id FROM attempts")}
    expected = {training_attempt_id(digest(plan), t["trial_id"]) for t in plan["trials"]}
    if set(attempts) - expected:
        raise ValueError("recovery_ledger_unplanned_attempts")
    rows = []
    ledger = ReservationLedger(db_path, cap_micros=permit["cap_micros"], authorization_id=permit["authorization_id"])
    if db_path.exists():
        # Migrate a pre-amount_source store before reconciling; never create a missing one.
        ledger.initialize()
    for trial in plan["trials"]:
        attempt = training_attempt_id(digest(plan), trial["trial_id"])
        trial_dir = run_dir / trial["trial_id"]
        no_links(trial_dir)
        started_path, receipt_path = trial_dir / "started.json", trial_dir / "receipt.json"
        no_links(started_path)
        no_links(receipt_path)
        existing = attempts.get(attempt)
        if existing is not None and existing[0] != plan["per_trial_worst_case_micros"]:
            raise ValueError("recovery_reservation_mismatch")
        outcome = "unattempted"
        original_receipt_sha = original_started_sha = None
        if started_path.exists():
            started = load_object(started_path)
            original_started_sha = digest(started)
            if (started.get("schema_version") != "TrainingAttemptStarted/v2" or
                    started.get("trial_id") != trial["trial_id"] or started.get("plan_sha256") != digest(plan) or
                    started.get("permit_sha256") != digest(permit) or started.get("ledger_attempt_id") != attempt):
                raise ValueError("recovery_attempt_header_mismatch")
        if receipt_path.exists():
            # Hash and preserve even a partial/unreadable receipt. It is never
            # interpreted as completed work or overwritten with repaired content.
            original_receipt_sha = file_sha256(receipt_path)
            try:
                receipt = load_object(receipt_path)
                validate_training_outcome(receipt, plan, permit)
                if receipt["ledger_attempt_id"] != attempt or receipt["trial_id"] != trial["trial_id"]:
                    raise ValueError("recovery_receipt_attempt_mismatch")
            except (ValueError, OSError):
                outcome = "original_receipt_unusable"
            else:
                original_receipt_sha = digest(receipt)
                outcome = "original_" + receipt["status"]
                if existing is None:
                    raise ValueError("receipt_without_reservation")
                if existing[1] is not None:
                    if receipt["actual_micros"] is not None and existing[1] != receipt["actual_micros"]:
                        raise ValueError("recovery_known_cost_conflict")
                else:
                    # Repair only accounting, using the immutable original outcome.
                    ledger.reconcile(attempt, actual_micros=receipt["actual_micros"],
                        receipt_id=receipt["billing_receipt_id"], usage_units=receipt["optimizer_steps"],
                        compute_seconds=receipt["duration_seconds"] if receipt["duration_seconds"] <= 10**9 else None,
                        state={"completed": "succeeded", "oom": "failed"}.get(receipt["status"], receipt["status"]))
                    if receipt["actual_micros"] is not None:
                        existing = (existing[0], receipt["actual_micros"], "succeeded", receipt["optimizer_steps"],
                                    receipt["billing_receipt_id"])
        elif existing is not None or started_path.exists():
            outcome = "interrupted_no_success_receipt"
        if existing is None and started_path.exists():
            raise ValueError("started_attempt_without_reservation")
        if existing is not None and existing[1] is None:
            if outcome in ("interrupted_no_success_receipt", "original_receipt_unusable"):
                ledger.reconcile(attempt, actual_micros=None, state="unknown")
        rows.append({"trial_id": trial["trial_id"], "ledger_attempt_id": attempt if existing is not None else None,
                     "outcome": outcome, "original_started_sha256": original_started_sha,
                     "original_receipt_sha256": original_receipt_sha,
                     "reserved_micros": existing[0] if existing is not None else None,
                     "known_actual_micros": existing[1] if existing is not None else None,
                     "checkpoint_promoted": False, "new_attempt_allowed": False})
    recovery_parent = run_dir / "recovery"
    no_links(recovery_parent)
    recovery_parent.mkdir(exist_ok=True)
    recovery_dir = recovery_parent / authorization.authorization_id
    recovery_dir.mkdir(exist_ok=False)
    report = {"schema_version": "TrainingRecoveryReceipt/v1", "edition_id": plan["edition_id"],
        "plan_sha256": digest(plan), "permit_sha256": digest(permit),
        "recovery_authorization_sha256": digest(authorization.model_dump(mode="json")),
        "stopped_worker_receipt_sha256": authorization.stopped_worker_receipt_sha256,
        "run_started_sha256": digest(header), "recovered_at": clock().isoformat(), "outcomes": rows,
        "accounting": ledger.summary() if db_path.exists() else None,
        "status": "accounted_originals_preserved_no_restart", "new_trials_started": 0,
        "unattempted_trial_ids": [r["trial_id"] for r in rows if r["outcome"] == "unattempted"],
        "incomplete_attempt_trial_ids": [r["trial_id"] for r in rows if r["outcome"] in
                                        ("interrupted_no_success_receipt", "original_receipt_unusable")],
        "execution_or_product_acceptance": False}
    _write_json(recovery_dir / "receipt.json", report)
    return report
