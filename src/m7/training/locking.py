"""Dev-justified target locks and authenticated D4/D7 projections, no test access."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from .executor import _write_json
from .selection import authenticate, Verifier
from .selection_models import NumericalTargets, PreTestLockApproval, PreTestSelectionLock
from .validation import digest, hash_pin, now_utc, utc


def justify_targets(selection: dict, targets: NumericalTargets, *, rationale_receipt_sha256: str,
                    clock: Callable[[], datetime] = now_utc) -> dict:
    """Propose target values against actual dev results; grants no approval."""
    hash_pin(rationale_receipt_sha256)
    fine = selection["selected_finetuned"]
    if (selection.get("schema_version") != "DevSelectionReceipt/v1" or
            selection.get("heldout_accessed") is not False or not fine["eligible"]):
        raise ValueError("actual_development_selection_required")
    evidence = {}
    for label, target in targets.per_class.items():
        metrics = fine["metrics"]["total"]["per_class"][label]
        interval = selection["selected_quality_intervals"]["finetuned"]["per_class"][label]["recall"]
        lower = interval["interval"][0] if interval["interval"] is not None else None
        evidence[label] = {"support": metrics["support"], "precision": metrics["precision"],
            "recall": metrics["recall"], "recall_interval": interval,
            "dev_meets_proposed_precision": metrics["precision"]["value"] is not None and
                metrics["precision"]["value"] >= target.precision,
            "dev_meets_proposed_recall": metrics["recall"]["value"] is not None and
                metrics["recall"]["value"] >= target.recall,
            "dev_meets_proposed_recall_bound": lower is not None and lower >= target.recall_lower_95}
    return {"schema_version": "TargetJustification/v1", "edition_id": selection["edition_id"],
        "dev_selection_receipt_sha256": digest(selection), "targets": targets.model_dump(mode="json"),
        "targets_sha256": digest(targets.model_dump(mode="json")), "per_class_dev_evidence": evidence,
        "false_negative_consequence": "annotated_sensitive_codepoints_exposed",
        "false_positive_consequence": "useful_benign_information_removed",
        "rationale_receipt_sha256": rationale_receipt_sha256, "created_at": clock().isoformat(),
        "scope": "engineering_targets_for_fictional_logs_not_real_privacy_certification",
        "approval_status": "requires_explicit_integrator_approval",
        "exact_invariants": {"structure_failures": 0, "intended_record_accounting": 1.0},
        "heldout_accessed": False}


def lock_binding(selection: dict, parity: dict, justification: dict, *, corpus_manifest_sha256: str) -> dict:
    """Exact candidate bindings to approve. No approve=True or timestamp invention."""
    hash_pin(corpus_manifest_sha256)
    fine, base = selection["selected_finetuned"], selection["selected_base"]
    targets = NumericalTargets.model_validate(justification["targets"])
    if (selection.get("schema_version") != "DevSelectionReceipt/v1" or
            selection.get("heldout_accessed") is not False or selection.get("product_acceptance") is not False or
            not fine["eligible"] or not base["eligible"] or
            fine["measurement_status"] != "measured" or base["measurement_status"] != "measured" or
            parity.get("schema_version") != "TrainingParity/v1" or parity["edition_id"] != selection["edition_id"] or
            parity["selected_training_receipt_sha256"] != fine["training_receipt_sha256"] or
            parity["selected_checkpoint_sha256"] != fine["checkpoint_sha256"] or
            parity["checkpoint_export_sha256"] != fine["checkpoint_export_sha256"] or
            parity["selection_rule_sha256"] != selection["selection_rule_sha256"] or
            parity["base_configuration_sha256"] != base["configuration_sha256"] or
            parity["finetuned_configuration_sha256"] != fine["configuration_sha256"] or
            justification.get("schema_version") != "TargetJustification/v1" or
            justification["edition_id"] != selection["edition_id"] or justification["heldout_accessed"] is not False or
            justification["dev_selection_receipt_sha256"] != digest(selection) or
            justification["targets_sha256"] != digest(targets.model_dump(mode="json")) or
            justification["exact_invariants"] != {"structure_failures": 0, "intended_record_accounting": 1.0}):
        raise ValueError("pre_test_lock_material_binding_mismatch")
    return {"edition_id": selection["edition_id"],
        "experiment_plan_sha256": selection["experiment_plan_sha256"],
        "training_plan_sha256": selection["training_plan_sha256"],
        "corpus_manifest_sha256": corpus_manifest_sha256,
        "selection_rule_sha256": selection["selection_rule_sha256"],
        "dev_selection_receipt_sha256": digest(selection),
        "selected_training_receipt_sha256": fine["training_receipt_sha256"],
        "selected_checkpoint_sha256": fine["checkpoint_sha256"],
        "base_configuration_sha256": base["configuration_sha256"],
        "finetuned_configuration_sha256": fine["configuration_sha256"],
        "parity_receipt_sha256": digest(parity), "target_justification_sha256": digest(justification),
        "targets_sha256": justification["targets_sha256"]}


def _authenticate_materials(binding: dict, selection: dict, parity: dict,
                            justification: dict, verify_receipt: Verifier) -> None:
    for kind, sha in (
        ("dev_selection_policy", selection["policy_sha256"]),
        ("dev_selection_receipt", binding["dev_selection_receipt_sha256"]),
        ("training_receipt", binding["selected_training_receipt_sha256"]),
        ("training_run_closeout", selection["training_run_closeout_sha256"]),
        ("checkpoint_export", parity["checkpoint_export_sha256"]),
        ("parity_receipt", binding["parity_receipt_sha256"]),
        ("numerical_targets", binding["targets_sha256"]),
        ("target_justification", binding["target_justification_sha256"]),
        ("target_rationale", justification["rationale_receipt_sha256"]),
    ):
        authenticate(verify_receipt, kind, sha)


def create_pre_test_lock(selection: dict, parity: dict, justification: dict, *,
                         corpus_manifest_sha256: str, approval: PreTestLockApproval,
                         verify_receipt: Verifier,
                         clock: Callable[[], datetime] = now_utc) -> PreTestSelectionLock:
    binding = lock_binding(selection, parity, justification, corpus_manifest_sha256=corpus_manifest_sha256)
    _authenticate_materials(binding, selection, parity, justification, verify_receipt)
    point = clock()
    approval_hash = digest(approval.model_dump(mode="json"))
    authenticate(verify_receipt, "pre_test_lock_approval", approval_hash)
    if (approval.binding_sha256 != digest(binding) or
            not utc(selection["registered_at"]) <= utc(selection["first_evaluated_at"]) <=
                utc(selection["created_at"]) <= utc(justification["created_at"]) <= utc(approval.issued_at) <= point or
            not point < utc(approval.expires_at)):
        raise ValueError("pre_test_lock_approval_or_chronology_mismatch")
    # Trusted host must consult current authoritative custody state. This is not
    # a file read of held-out data and has no permissive default implementation.
    authenticate(verify_receipt, "heldout_unopened", digest(binding))
    return PreTestSelectionLock(**binding, approval_sha256=approval_hash,
                                locked_at=point.isoformat(), expires_at=approval.expires_at)


def verify_pre_test_lock(lock: PreTestSelectionLock, *, selection: dict, parity: dict,
                         justification: dict, approval: PreTestLockApproval,
                         verify_receipt: Verifier,
                         clock: Callable[[], datetime] = now_utc) -> None:
    binding = lock_binding(selection, parity, justification, corpus_manifest_sha256=lock.corpus_manifest_sha256)
    _authenticate_materials(binding, selection, parity, justification, verify_receipt)
    if (any(getattr(lock, key) != value for key, value in binding.items()) or
            lock.approval_sha256 != digest(approval.model_dump(mode="json")) or
            approval.binding_sha256 != digest(binding) or
            not utc(selection["registered_at"]) <= utc(selection["first_evaluated_at"]) <=
                utc(selection["created_at"]) <= utc(justification["created_at"]) or
            not utc(justification["created_at"]) <= utc(approval.issued_at) <= utc(lock.locked_at) <= clock() <
                utc(lock.expires_at) <= utc(approval.expires_at)):
        raise ValueError("pre_test_lock_binding_or_expiry_mismatch")
    authenticate(verify_receipt, "pre_test_lock_approval", lock.approval_sha256)
    authenticate(verify_receipt, "pre_test_selection_lock", lock.sha256)


def selection_lock_reference(lock: PreTestSelectionLock):
    """Project the canonical lock; caller must authenticate it before release."""
    from m7.data.lifecycle_models import SelectionLockReference
    return SelectionLockReference(edition_id=lock.edition_id, receipt_sha256=lock.sha256,
        corpus_manifest_sha256=lock.corpus_manifest_sha256, selection_rule_sha256=lock.selection_rule_sha256,
        locked_at=lock.locked_at)


def export_pre_test_lock(lock: PreTestSelectionLock, destination: Path, *, selection: dict,
                         parity: dict, justification: dict, approval: PreTestLockApproval,
                         verify_receipt: Verifier) -> dict:
    """Write a new authenticated lock/projection envelope; never overwrite a lock."""
    verify_pre_test_lock(lock, selection=selection, parity=parity, justification=justification,
                         approval=approval, verify_receipt=verify_receipt)
    reference = selection_lock_reference(lock)
    projection = reference.model_dump(mode="json")
    authenticate(verify_receipt, "pre_test_lock_binding", digest(projection))
    envelope = {"schema_version": "PreTestLockExport/v1", "lock": lock.model_dump(mode="json"),
                "selection_lock_sha256": lock.sha256, "custody_reference": projection,
                "custody_reference_sha256": digest(projection)}
    from .artifacts import no_links
    for path in (destination, *destination.parents):
        no_links(path)
    # One immutable admitted lock per edition in the trusted lock store.
    _write_json(destination.resolve(strict=True) / (lock.edition_id + ".lock.json"), envelope)
    return envelope
