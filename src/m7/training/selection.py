"""Dev-only exact-span selection. No detector, model or test-corpus calls."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from m7.contracts import LogRecord, Span, validate_prediction
from m7.eval import Observation, score
from m7.eval.bootstrap import paired_interval, quality_intervals
from m7.providers.contracts import config_digest
from .selection_models import DevEvaluation, DevSelectionPolicy
from .artifacts import inspect_artifacts, load_training_data, no_links
from .validation import digest, now_utc, utc, validate_training_outcome

Verifier = Callable[[str, str], bool]


def authenticate(verifier: Verifier, kind: str, sha256: str) -> None:
    if verifier(kind, sha256) is not True:
        raise ValueError("receipt_not_authenticated_or_revoked")


@dataclass(frozen=True)
class DevRecord:
    record: LogRecord
    gold: tuple[Span, ...]
    block_id: str
    slice_name: str


def _population(rows: Sequence[DevRecord]) -> tuple[dict, str]:
    by_id = {}
    for row in rows:
        if (row.record.split_id != "dev" or row.slice_name not in ("normal", "challenge") or
                not row.block_id or row.record.record_id in by_id or
                any(s.end > len(row.record.log.message) for s in row.gold) or
                len({(s.start, s.end, s.label) for s in row.gold}) != len(row.gold)):
            raise ValueError("invalid_development_population")
        by_id[row.record.record_id] = row
    if not by_id:
        raise ValueError("empty_development_population")
    identity = [{"record_id": key, "content_sha256": by_id[key].record.content_sha256,
                 "block_id": by_id[key].block_id, "slice": by_id[key].slice_name}
                for key in sorted(by_id)]
    return by_id, digest(identity)


def _observations(population: dict, evaluation: DevEvaluation) -> tuple[list[Observation], bool]:
    predictions = {}
    for prediction in evaluation.predictions:
        row = population.get(prediction.record_id)
        if row is None or prediction.record_id in predictions:
            raise ValueError("development_prediction_population_mismatch")
        if (prediction.arm != evaluation.config.arm or prediction.model_id != evaluation.config.model_id or
                prediction.content_sha256 != row.record.content_sha256):
            raise ValueError("development_prediction_identity_mismatch")
        prediction = validate_prediction(row.record, prediction)
        if any(s.confidence is None or s.confidence < evaluation.config.decoder.threshold for s in prediction.spans):
            raise ValueError("development_threshold_mismatch")
        predictions[prediction.record_id] = prediction
    observations, complete = [], len(predictions) == len(population)
    for key in sorted(population):
        row, prediction = population[key], predictions.get(key)
        available = prediction is not None and prediction.status == "ok"
        complete = complete and available
        observations.append(Observation(record_id=key, block_id=row.block_id, slice_name=row.slice_name,
            length=len(row.record.log.message), gold=row.gold,
            predicted=prediction.spans if available else (), available=available, structure_valid=available))
    return observations, bool(complete)


def _choose(candidates: list[dict], observations: dict, policy: DevSelectionPolicy) -> tuple[dict, list[dict]]:
    """Macro F1, paired indistinguishability, recall, conservative cost, stable ID."""
    eligible = [c for c in candidates if c["eligible"]]
    if not eligible:
        raise ValueError("no_complete_development_candidate")
    best = max(eligible, key=lambda c: c["metrics"]["total"]["macro"]["f1"]["value"])
    tied, comparisons = [], []
    for candidate in eligible:
        interval = paired_interval(observations[best["evaluation_id"]], observations[candidate["evaluation_id"]],
            lambda m: m["macro"]["f1"]["value"], seed=policy.rule.bootstrap_seed)
        # Missing uncertainty cannot silently stand for equality or proof of gain.
        if interval["interval"] is None:
            raise ValueError("development_selection_uncertainty_unavailable")
        comparisons.append({"left": best["evaluation_id"], "right": candidate["evaluation_id"],
                            "metric": "macro_exact_f1", **interval})
        if interval["interval"][0] <= 0:
            tied.append(candidate)
    recall_best = max(tied, key=lambda c: c["metrics"]["total"]["macro"]["recall"]["value"])
    recall_tied = []
    for candidate in tied:
        interval = paired_interval(observations[recall_best["evaluation_id"]], observations[candidate["evaluation_id"]],
            lambda m: m["macro"]["recall"]["value"], seed=policy.rule.bootstrap_seed)
        if interval["interval"] is None:
            raise ValueError("development_recall_uncertainty_unavailable")
        comparisons.append({"left": recall_best["evaluation_id"], "right": candidate["evaluation_id"],
                            "metric": "macro_exact_recall", **interval})
        if interval["interval"][0] <= 0:
            recall_tied.append(candidate)
    chosen = min(recall_tied, key=lambda c: (c["selection_cost_upper_micros"],
                                            c["trial_id"] or "", c["threshold"], c["evaluation_id"]))
    return chosen, comparisons


def select_checkpoint(rows: Sequence[DevRecord], evaluations: Sequence[DevEvaluation], *,
                      policy: DevSelectionPolicy, training_plan: dict, training_permit: dict,
                      trial_receipts: Sequence[dict], checkpoint_exports: Sequence[dict],
                      training_run: dict, training_root: Path,
                      verify_receipt: Verifier, clock: Callable[[], datetime] = now_utc) -> dict:
    """Consume authenticated actual dev observations; never run inference here.

    Every completed planned trial and base must have the entire same threshold
    grid. Failed trials remain in accounting. No extra trials can be supplied.
    """
    population, population_hash = _population(rows)
    for path in (training_root, *training_root.parents):
        no_links(path)
    paths, _ = inspect_artifacts(training_plan, training_root.resolve(strict=True), check_environment=False)
    staged = {r["record"].record_id: r for r in load_training_data(paths["dev"], "dev")}
    if staged.keys() != population.keys():
        raise ValueError("development_artifact_population_mismatch")
    for key, row in population.items():
        truth = staged[key]
        if (row.record != truth["record"] or
                {(s.start, s.end, s.label) for s in row.gold} !=
                {(s.start, s.end, s.label) for s in truth["spans"]}):
            raise ValueError("development_artifact_gold_mismatch")
    authenticate(verify_receipt, "development_population", population_hash)
    policy_hash = digest(policy.model_dump(mode="json"))
    authenticate(verify_receipt, "dev_selection_policy", policy_hash)
    if (policy.training_plan_sha256 != digest(training_plan) or policy.edition_id != training_plan["edition_id"] or
            policy.dev_sha256 != training_plan["artifacts"]["dev"]["sha256"] or
            utc(policy.registered_at) > clock()):
        raise ValueError("development_policy_binding_mismatch")
    if len({r.block_id for r in rows}) < policy.rule.minimum_blocks:
        raise ValueError("insufficient_development_units")
    receipts, exports, outcomes = {}, {}, []
    planned = {t["trial_id"] for t in training_plan["trials"]}
    if not 1 <= len(planned) <= 3:
        raise ValueError("trial_cap_exceeded")
    for receipt in trial_receipts:
        if receipt.get("execution_kind") != "actual_training":
            raise ValueError("actual_training_required")
        validate_training_outcome(receipt, training_plan, training_permit)
        key = receipt["trial_id"]
        if key in receipts or key not in planned:
            raise ValueError("duplicate_or_unplanned_training_receipt")
        authenticate(verify_receipt, "training_receipt", digest(receipt))
        receipts[key] = receipt
        outcomes.append({"trial_id": key, "status": receipt["status"], "receipt_sha256": digest(receipt),
                         "actual_micros": receipt["actual_micros"], "reserved_micros": receipt["reserved_micros"],
                         "cost_status": receipt["cost_status"]})
    for export in checkpoint_exports:
        authenticate(verify_receipt, "checkpoint_export", digest(export))
        key = export["trial_id"]
        if key in exports or key not in receipts or receipts[key]["status"] != "completed":
            raise ValueError("invalid_checkpoint_export_trial")
        if (export.get("schema_version") != "CheckpointExport/v1" or
                export["training_receipt_sha256"] != digest(receipts[key]) or
                export["original_checkpoint_sha256"] != receipts[key]["checkpoint_sha256"]):
            raise ValueError("checkpoint_export_lineage_mismatch")
        exports[key] = export
    authenticate(verify_receipt, "training_run_closeout", digest(training_run))
    if (training_run.get("edition_id") != policy.edition_id or training_run.get("plan_sha256") != digest(training_plan) or
            training_run.get("permit_sha256") != digest(training_permit)):
        raise ValueError("training_closeout_binding_mismatch")
    if training_run.get("schema_version") == "TrainingRun/v2":
        if ({digest(r) for r in training_run["receipts"]} != {digest(r) for r in trial_receipts} or
                training_run["status"] not in ("completed_with_outcomes", "cancelled", "blocked")):
            raise ValueError("training_run_receipt_mismatch")
        unattempted = sorted(training_run["unattempted_trial_ids"])
        incomplete = []
    elif training_run.get("schema_version") == "TrainingRecoveryReceipt/v1":
        by_trial = {row["trial_id"]: row for row in training_run["outcomes"]}
        if set(by_trial) != planned:
            raise ValueError("recovery_trial_coverage_mismatch")
        for key, receipt in receipts.items():
            if by_trial[key]["original_receipt_sha256"] != digest(receipt) or by_trial[key]["outcome"] != "original_" + receipt["status"]:
                raise ValueError("recovered_original_receipt_mismatch")
        unattempted = sorted(training_run["unattempted_trial_ids"])
        incomplete = sorted(training_run["incomplete_attempt_trial_ids"])
    else:
        raise ValueError("training_closeout_required")
    if (set(unattempted) & receipts.keys() or set(incomplete) & receipts.keys() or
            set(unattempted) & set(incomplete) or set(unattempted) | set(incomplete) | receipts.keys() != planned):
        raise ValueError("unaccounted_training_slot")
    candidates, observations, seen, measured_at = [], {}, set(), []
    per_checkpoint = {}
    base_identity = None
    for evaluation in evaluations:
        evaluation_hash = digest(evaluation.model_dump(mode="json"))
        authenticate(verify_receipt, "dev_evaluation", evaluation_hash)
        cfg = evaluation.config
        threshold = cfg.decoder.threshold
        key = (evaluation.trial_id, threshold)
        if (key in seen or evaluation.evaluation_id in observations or threshold not in policy.rule.thresholds or
                evaluation.edition_id != policy.edition_id or evaluation.dev_sha256 != policy.dev_sha256 or
                evaluation.policy_sha256 != policy_hash or cfg.decoder.threshold_selection_sha256 != policy.rule.sha256 or
                not utc(policy.registered_at) <= utc(evaluation.measured_at) <= clock()):
            raise ValueError("development_evaluation_binding_mismatch")
        seen.add(key)
        measured_at.append(evaluation.measured_at)
        # Across threshold probes every byte except the scalar threshold is fixed.
        configuration = cfg.model_dump(mode="json")
        configuration["decoder"].pop("threshold")
        identity = digest(configuration)
        if cfg.arm == "base":
            if base_identity is not None and base_identity != identity:
                raise ValueError("base_changed_between_thresholds")
            base_identity = identity
            cost, cost_status, training_hash, checkpoint_hash = 0, "not_applicable_no_training", None, None
        else:
            trial_id = evaluation.trial_id
            receipt, exported = receipts.get(trial_id), exports.get(trial_id)
            if receipt is None or exported is None or receipt["status"] != "completed":
                raise ValueError("completed_exported_training_required")
            if (evaluation.checkpoint_export_sha256 != digest(exported) or
                    cfg.training_receipt_sha256 != digest(receipt) or
                    cfg.weights_sha256 != exported["weights_sha256"] or
                    cfg.tokenizer_sha256 != exported["tokenizer_sha256"] or
                    cfg.architecture_sha256 != exported["architecture_sha256"]):
                raise ValueError("development_checkpoint_binding_mismatch")
            cost = receipt["actual_micros"] if receipt["actual_micros"] is not None else receipt["reserved_micros"]
            cost_status = "known_provider_cash" if receipt["actual_micros"] is not None else "reserved_upper_bound_unknown_actual"
            training_hash, checkpoint_hash = digest(receipt), receipt["checkpoint_sha256"]
        if evaluation.trial_id in per_checkpoint and per_checkpoint[evaluation.trial_id] != identity:
            raise ValueError("checkpoint_changed_between_thresholds")
        per_checkpoint[evaluation.trial_id] = identity
        obs, complete = _observations(population, evaluation)
        observations[evaluation.evaluation_id] = obs
        measured = bool(evaluation.predictions)
        metrics = {part: score([r for r in obs if part == "total" or r.slice_name == part])
                   for part in ("total", "normal", "challenge")} if measured else None
        eligible = bool(complete and measured and metrics["total"]["macro"]["f1"]["value"] is not None and
                        metrics["total"]["macro"]["recall"]["value"] is not None)
        candidates.append({"evaluation_id": evaluation.evaluation_id, "evaluation_sha256": evaluation_hash,
            "arm": cfg.arm, "trial_id": evaluation.trial_id, "threshold": threshold,
            "configuration_sha256": config_digest(cfg), "training_receipt_sha256": training_hash,
            "checkpoint_sha256": checkpoint_hash, "checkpoint_export_sha256": evaluation.checkpoint_export_sha256,
            "metrics": metrics, "measurement_status": "not_measured" if not measured else
            "measured" if complete else "measured_incomplete", "eligible": eligible,
            "selection_cost_upper_micros": cost, "cost_status": cost_status})
    expected_trials = {key for key, r in receipts.items() if r["status"] == "completed"}
    expected = {(key, threshold) for key in expected_trials | {None} for threshold in policy.rule.thresholds}
    if seen != expected or not expected_trials:
        raise ValueError("full_preregistered_development_grid_required")
    base, base_comparisons = _choose([c for c in candidates if c["arm"] == "base"], observations, policy)
    finalists, comparisons = [], list(base_comparisons)
    for trial_id in sorted(expected_trials):
        pool = [c for c in candidates if c["trial_id"] == trial_id]
        # Failed dev-only checkpoints stay visible but cannot win selection.
        if any(c["eligible"] for c in pool):
            selected, intervals = _choose(pool, observations, policy)
            finalists.append(selected)
            comparisons.extend(intervals)
    fine, intervals = _choose(finalists, observations, policy)
    comparisons.extend(intervals)
    return {"schema_version": "DevSelectionReceipt/v1", "edition_id": policy.edition_id,
        "experiment_plan_sha256": policy.experiment_plan_sha256, "training_plan_sha256": digest(training_plan),
        "policy_sha256": policy_hash, "selection_rule_sha256": policy.rule.sha256,
        "dev_sha256": policy.dev_sha256, "dev_population_sha256": population_hash,
        "created_at": clock().isoformat(), "registered_at": policy.registered_at,
        "first_evaluated_at": min(measured_at, key=utc), "candidates": candidates,
        "training_outcomes": outcomes, "unattempted_trial_ids": unattempted,
        "incomplete_attempt_trial_ids": incomplete, "training_run_closeout_sha256": digest(training_run),
        "training_accounting": training_run["accounting"],
        "selected_base": base, "selected_finetuned": fine, "comparisons": comparisons,
        "selected_quality_intervals": {
            "base": quality_intervals(observations[base["evaluation_id"]], seed=policy.rule.bootstrap_seed),
            "finetuned": quality_intervals(observations[fine["evaluation_id"]], seed=policy.rule.bootstrap_seed)},
        "cost_scope": "provider_cash_or_reserved_bound_not_total_economic_cost",
        "heldout_accessed": False, "product_acceptance": False}
