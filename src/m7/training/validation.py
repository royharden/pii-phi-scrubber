"""Value-free training contracts. Validation grants no execution authority."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

SHA = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
ARTIFACTS = frozenset({"model", "tokenizer", "train", "dev", "config", "environment",
                       "license_packet", "custody_audit"})
SELECTION_RULE = "dev_macro_exact_f1_then_recall_then_lower_cost"
RECEIPT_FIELDS = {"schema_version", "execution_kind", "edition_id", "plan_sha256", "permit_sha256",
                  "authorization_id", "artifact_hashes", "trial_id", "trial_sha256", "seed", "status",
                  "error_code", "optimizer_steps", "epochs", "checkpoint_sha256", "checkpoint_relative_path",
                  "ledger_attempt_id", "reserved_micros", "actual_micros", "billing_receipt_id", "cost_status",
                  "started_at", "finished_at", "duration_seconds", "independent_audit", "m7_02_accepted"}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def training_attempt_id(plan_hash: str, trial_id: str) -> str:
    return "train-" + digest({"plan": plan_hash, "trial": trial_id})[:48]


def shape(value: object, keys: set[str] | frozenset[str]) -> None:
    if type(value) is not dict or set(value) != keys:
        raise ValueError("invalid_contract_shape")


def identifier(value: object) -> None:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("invalid_identifier")


def hash_pin(value: object) -> None:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError("invalid_hash_pin")


def integer(value: object, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("invalid_integer_bound")


def utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid_utc_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid_utc_timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("utc_required")
    return parsed


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _v1(plan: dict, permit: dict) -> dict:
    """Compatibility validator only; v1 cannot enter the execution function."""
    fields = {"schema_version", "edition_id", "model_sha256", "tokenizer_sha256", "train_sha256",
              "dev_sha256", "config_sha256", "environment_sha256", "seed", "trial_count",
              "max_epochs", "max_steps", "worst_case_micros", "selection_rule", "sealed_test_access"}
    shape(plan, fields)
    identifier(plan["edition_id"])
    for key in ("model", "tokenizer", "train", "dev", "config", "environment"):
        hash_pin(plan[key + "_sha256"])
    integer(plan["seed"], 0, 2**32 - 1)
    integer(plan["trial_count"], 1, 3)
    integer(plan["max_epochs"], 1, 3)
    integer(plan["max_steps"], 1, 1000)
    integer(plan["worst_case_micros"], 0, 2**63 - 1)
    if plan["selection_rule"] != SELECTION_RULE or plan["sealed_test_access"] is not False:
        raise ValueError("invalid_selection_custody")
    for field in ("plan_sha256", "license_packet_sha256", "custody_audit_sha256"):
        hash_pin(permit.get(field))
    if (permit.get("schema_version") != "ExecutionPermit/v1" or
            permit["plan_sha256"] != digest(plan) or permit.get("approved") is not True or
            permit.get("training_allowed") is not True):
        raise ValueError("training_not_authorized")
    integer(permit.get("cap_micros"), plan["worst_case_micros"], 2**63 - 1)
    identifier(permit.get("authorization_id"))
    if now_utc() >= utc(permit.get("expires_at")):
        raise ValueError("permit_expired")
    return {"status": "plan_validated_not_executed", "plan_sha256": digest(plan),
            "execution_allowed_now": False, "reason": "legacy_validation_only"}


def validate_training_plan(plan: dict, permit: dict, *, at: datetime | None = None) -> dict:
    if type(plan) is not dict or type(permit) is not dict:
        raise ValueError("object_required")
    if plan.get("schema_version") == "TrainingPlan/v1":
        return _v1(plan, permit)
    shape(plan, {"schema_version", "edition_id", "artifacts", "trials", "max_epochs", "max_steps",
                 "max_seconds_per_trial", "per_trial_worst_case_micros", "selection_rule",
                 "sealed_test_access", "resource_id", "backend"})
    if plan["schema_version"] != "TrainingPlan/v2" or plan["backend"] != "gliner_local":
        raise ValueError("unsupported_training_backend")
    identifier(plan["edition_id"])
    identifier(plan["resource_id"])
    if plan["selection_rule"] != SELECTION_RULE or plan["sealed_test_access"] is not False:
        raise ValueError("invalid_selection_custody")
    integer(plan["max_epochs"], 1, 3)
    integer(plan["max_steps"], 1, 1000)
    integer(plan["max_seconds_per_trial"], 1, 14400)
    integer(plan["per_trial_worst_case_micros"], 0, 2**60)
    shape(plan["artifacts"], ARTIFACTS)
    for name, item in plan["artifacts"].items():
        shape(item, {"path", "sha256", "kind"})
        hash_pin(item["sha256"])
        path = item["path"]
        if (not isinstance(path, str) or not path or "\\" in path or ":" in path or
                Path(path).is_absolute() or any(p in ("..", ".") for p in path.split("/")) or
                any(not p for p in path.split("/"))):
            raise ValueError("relative_local_artifact_required")
        if item["kind"] != ("tree" if name in {"model", "tokenizer"} else "file"):
            raise ValueError("artifact_kind_mismatch")
    if plan["artifacts"]["train"]["path"] == plan["artifacts"]["dev"]["path"]:
        raise ValueError("split_alias")
    trials = plan["trials"]
    if type(trials) is not list or not 1 <= len(trials) <= 3:
        raise ValueError("trial_cap_exceeded")
    ids = set()
    for trial in trials:
        shape(trial, {"trial_id", "seed", "learning_rate", "batch_size"})
        identifier(trial["trial_id"])
        if trial["trial_id"] in ids:
            raise ValueError("duplicate_trial")
        ids.add(trial["trial_id"])
        integer(trial["seed"], 0, 2**32 - 1)
        integer(trial["batch_size"], 1, 32)
        lr = trial["learning_rate"]
        if type(lr) not in (float, int) or not math.isfinite(lr) or not 0 < lr <= 0.01:
            raise ValueError("invalid_learning_rate")
    shape(permit, {"schema_version", "authorization_id", "approved", "training_allowed",
                   "plan_sha256", "edition_id", "license_packet_sha256", "custody_audit_sha256",
                   "resource_id", "cap_micros", "currency", "issued_at", "expires_at", "approved_by"})
    if (permit["schema_version"] != "ExecutionPermit/v2" or permit["approved"] is not True or
            permit["training_allowed"] is not True or permit["plan_sha256"] != digest(plan) or
            permit["edition_id"] != plan["edition_id"] or permit["resource_id"] != plan["resource_id"]):
        raise ValueError("permit_plan_mismatch")
    for field in ("authorization_id", "approved_by", "currency"):
        identifier(permit[field])
    for field in ("license_packet", "custody_audit"):
        if permit[field + "_sha256"] != plan["artifacts"][field]["sha256"]:
            raise ValueError("permit_artifact_mismatch")
    integer(permit["cap_micros"], len(trials) * plan["per_trial_worst_case_micros"], 2**63 - 1)
    point = at or now_utc()
    if not utc(permit["issued_at"]) <= point < utc(permit["expires_at"]):
        raise ValueError("permit_not_current")
    return {"status": "plan_validated_not_executed", "plan_sha256": digest(plan),
            "permit_sha256": digest(permit), "execution_allowed_now": False,
            "reason": "validation_does_not_execute_or_approve"}


def _validate_completed_receipt(receipt: dict, plan: dict, permit: dict | None = None,
                                *, allow_mock: bool = False) -> dict:
    """Structural/lineage check only, never independent execution acceptance."""
    if type(receipt) is not dict or receipt.get("plan_sha256") != digest(plan):
        raise ValueError("receipt_plan_mismatch")
    if receipt.get("schema_version") == "TrainingReceipt/v1":
        for field in ("model", "tokenizer", "train", "dev", "config", "environment"):
            if receipt.get(field + "_sha256") != plan.get(field + "_sha256"):
                raise ValueError("receipt_lineage_mismatch")
        if receipt.get("seed") != plan.get("seed"):
            raise ValueError("receipt_lineage_mismatch")
        hash_pin(receipt.get("checkpoint_sha256"))
        integer(receipt.get("optimizer_steps"), 1, plan["max_steps"])
        if not receipt.get("ledger_attempt_id") or not receipt.get("billing_receipt_id"):
            raise ValueError("missing_accounting_receipt")
    elif receipt.get("schema_version") == "TrainingReceipt/v2":
        shape(receipt, RECEIPT_FIELDS)
        if receipt.get("artifact_hashes") != {k: v["sha256"] for k, v in plan["artifacts"].items()}:
            raise ValueError("receipt_lineage_mismatch")
        trial = next((t for t in plan["trials"] if t["trial_id"] == receipt.get("trial_id")), None)
        if trial is None or receipt.get("trial_sha256") != digest(trial) or receipt.get("seed") != trial["seed"]:
            raise ValueError("receipt_trial_mismatch")
        integer(receipt.get("optimizer_steps"), 1, plan["max_steps"])
        epochs = receipt.get("epochs")
        if type(epochs) not in (int, float) or not math.isfinite(epochs) or not 0 < epochs <= plan["max_epochs"]:
            raise ValueError("invalid_epoch_count")
        hash_pin(receipt.get("checkpoint_sha256"))
        hash_pin(receipt.get("permit_sha256"))
        identifier(receipt.get("ledger_attempt_id"))
        identifier(receipt.get("authorization_id"))
        if (receipt["edition_id"] != plan["edition_id"] or receipt["error_code"] is not None or
                receipt["ledger_attempt_id"] != training_attempt_id(digest(plan), trial["trial_id"]) or
                receipt["reserved_micros"] != plan["per_trial_worst_case_micros"] or
                receipt["checkpoint_relative_path"] != f"runs/{plan['edition_id']}/{trial['trial_id']}/checkpoint" or
                receipt["independent_audit"] != "pending" or receipt["m7_02_accepted"] is not False):
            raise ValueError("receipt_metadata_mismatch")
        if utc(receipt["finished_at"]) < utc(receipt["started_at"]):
            raise ValueError("receipt_time_mismatch")
        duration = receipt["duration_seconds"]
        if type(duration) not in (float, int) or not math.isfinite(duration) or duration < 0:
            raise ValueError("invalid_duration")
        if receipt["actual_micros"] is None:
            if receipt["cost_status"] != "unknown" or receipt["billing_receipt_id"] is not None:
                raise ValueError("receipt_cost_mismatch")
        else:
            integer(receipt["actual_micros"], 0, 2**63 - 1)
            identifier(receipt["billing_receipt_id"])
            if receipt["cost_status"] != "known":
                raise ValueError("receipt_cost_mismatch")
        if permit is not None:
            validate_training_plan(plan, permit, at=utc(receipt["started_at"]))
            if receipt["permit_sha256"] != digest(permit) or receipt["authorization_id"] != permit["authorization_id"]:
                raise ValueError("receipt_permit_mismatch")
    else:
        raise ValueError("unknown_receipt_schema")
    mock = allow_mock and receipt.get("schema_version") == "TrainingReceipt/v2" and receipt.get("execution_kind") == "mock"
    if (receipt.get("execution_kind") != "actual_training" and not mock) or receipt.get("status") != "completed":
        raise ValueError("actual_training_required")
    return {"status": "structurally_valid_mock" if mock else "structurally_valid",
            "independent_audit": "pending", "m7_02_accepted": False}


def validate_training_receipt(receipt: dict, plan: dict, permit: dict | None = None) -> dict:
    """Actual completed-training lineage only; mock outcomes cannot pass this gate."""
    return _validate_completed_receipt(receipt, plan, permit)


def validate_training_outcome(receipt: dict, plan: dict, permit: dict) -> dict:
    """Canonical outcome reader; failures are never turned into success receipts."""
    if receipt.get("status") == "completed":
        return _validate_completed_receipt(receipt, plan, permit, allow_mock=True)
    shape(receipt, RECEIPT_FIELDS)
    expected = {"failed": "engine_failure", "oom": "out_of_memory", "cancelled": "cancelled"}
    trial = next((t for t in plan["trials"] if t["trial_id"] == receipt["trial_id"]), None)
    if (receipt["schema_version"] != "TrainingReceipt/v2" or receipt["execution_kind"] not in ("actual_training", "mock") or
            receipt["status"] not in expected or receipt["error_code"] != expected[receipt["status"]] or
            trial is None or receipt["trial_sha256"] != digest(trial) or receipt["seed"] != trial["seed"] or
            receipt["plan_sha256"] != digest(plan) or receipt["permit_sha256"] != digest(permit) or
            receipt["edition_id"] != plan["edition_id"] or receipt["authorization_id"] != permit["authorization_id"] or
            receipt["artifact_hashes"] != {k: v["sha256"] for k, v in plan["artifacts"].items()} or
            receipt["reserved_micros"] != plan["per_trial_worst_case_micros"] or
            receipt["ledger_attempt_id"] != training_attempt_id(digest(plan), trial["trial_id"]) or
            receipt["independent_audit"] != "pending" or receipt["m7_02_accepted"] is not False or
            receipt["cost_status"] != "unknown"):
        raise ValueError("failed_training_receipt_binding_mismatch")
    if any(receipt[k] is not None for k in ("optimizer_steps", "epochs", "checkpoint_sha256",
                                            "checkpoint_relative_path", "actual_micros", "billing_receipt_id")):
        raise ValueError("failed_attempt_cannot_claim_completed_work")
    identifier(receipt["ledger_attempt_id"])
    validate_training_plan(plan, permit, at=utc(receipt["started_at"]))
    duration = receipt["duration_seconds"]
    if (utc(receipt["finished_at"]) < utc(receipt["started_at"]) or
            type(duration) not in (float, int) or not math.isfinite(duration) or duration < 0):
        raise ValueError("invalid_failed_attempt_time")
    return {"status": "structurally_valid_failure", "independent_audit": "pending", "m7_02_accepted": False}
