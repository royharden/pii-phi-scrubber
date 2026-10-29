"""Training authorization and receipt source; deliberately no training executor."""
from __future__ import annotations

import hashlib
import json
import re

_SHA = re.compile(r"^[0-9a-f]{64}$")


def _hashes(value: dict, fields: tuple[str, ...]) -> None:
    if any(not isinstance(value.get(key), str) or not _SHA.fullmatch(value[key]) for key in fields):
        raise ValueError("missing_or_invalid_hash_pin")


def validate_training_plan(plan: dict, permit: dict) -> dict:
    """Validate a proposed launch only. A valid plan is never a training receipt.

    Receipt authenticity, licensing and real custody require later independent audit.
    """
    required = {"schema_version", "edition_id", "model_sha256", "tokenizer_sha256",
                "train_sha256", "dev_sha256", "config_sha256", "environment_sha256",
                "seed", "trial_count", "max_epochs", "max_steps", "worst_case_micros",
                "selection_rule", "sealed_test_access"}
    if set(plan) != required or plan.get("schema_version") != "TrainingPlan/v1":
        raise ValueError("invalid_training_plan_shape")
    _hashes(plan, ("model_sha256", "tokenizer_sha256", "train_sha256", "dev_sha256",
                   "config_sha256", "environment_sha256"))
    for field, lower, upper in (("trial_count", 1, 3), ("max_epochs", 1, 3), ("max_steps", 1, 1000)):
        if type(plan[field]) is not int or not lower <= plan[field] <= upper:
            raise ValueError("trial_bounds_exceeded")
    if type(plan["seed"]) is not int or plan["sealed_test_access"] is not False:
        raise ValueError("invalid_selection_custody")
    if plan["selection_rule"] != "dev_macro_exact_f1_then_recall_then_lower_cost":
        raise ValueError("unlocked_selection_rule")
    if type(plan["worst_case_micros"]) is not int or plan["worst_case_micros"] < 0:
        raise ValueError("invalid_worst_case")
    if not isinstance(plan["edition_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", plan["edition_id"]):
        raise ValueError("invalid_edition")
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    _hashes(permit, ("plan_sha256", "license_packet_sha256", "custody_audit_sha256"))
    if permit.get("schema_version") != "ExecutionPermit/v1" or permit.get("plan_sha256") != digest:
        raise ValueError("permit_plan_mismatch")
    if permit.get("approved") is not True or permit.get("training_allowed") is not True:
        raise ValueError("training_not_authorized")
    if type(permit.get("cap_micros")) is not int or permit["cap_micros"] < plan["worst_case_micros"]:
        raise ValueError("insufficient_authorization")
    if not permit.get("authorization_id") or not permit.get("expires_at"):
        raise ValueError("incomplete_authorization")
    # Expiry is checked at future execution, against an authoritative UTC clock.
    return {"status": "plan_validated_not_executed", "plan_sha256": digest,
            "execution_allowed_now": False, "reason": "executor_not_implemented_dirty_mode"}


def validate_training_receipt(receipt: dict, plan: dict) -> dict:
    _hashes(receipt, ("plan_sha256", "model_sha256", "tokenizer_sha256", "train_sha256",
                      "dev_sha256", "config_sha256", "environment_sha256", "checkpoint_sha256"))
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if receipt.get("schema_version") != "TrainingReceipt/v1" or receipt["plan_sha256"] != digest:
        raise ValueError("receipt_plan_mismatch")
    if receipt.get("execution_kind") != "actual_training" or receipt.get("status") != "completed":
        raise ValueError("actual_training_required")
    for key in ("model_sha256", "tokenizer_sha256", "train_sha256", "dev_sha256", "config_sha256", "environment_sha256", "seed"):
        if receipt.get(key) != plan.get(key):
            raise ValueError("receipt_lineage_mismatch")
    if type(receipt.get("optimizer_steps")) is not int or not 0 < receipt["optimizer_steps"] <= plan["max_steps"]:
        raise ValueError("invalid_step_count")
    if not receipt.get("ledger_attempt_id") or not receipt.get("billing_receipt_id"):
        raise ValueError("missing_accounting_receipt")
    return {"status": "structurally_valid", "independent_audit": "pending",
            "m7_02_accepted": False}


__all__ = ["validate_training_plan", "validate_training_receipt"]
