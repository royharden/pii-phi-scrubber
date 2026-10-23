"""Exact scoring against original Unicode offsets; no source values in results."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

LABELS = ("NAME", "EMAIL", "PHONE", "ACCOUNT_ID")


@dataclass(frozen=True)
class Observation:
    record_id: str
    block_id: str
    slice_name: str
    length: int
    gold: tuple[Any, ...]
    predicted: tuple[Any, ...] = ()
    available: bool = False
    structure_valid: bool = False


def _triples(spans: Sequence[Any]) -> set[tuple[int, int, str]]:
    return {(s.start, s.end, str(s.label)) for s in spans}


def _mask(spans: Sequence[Any]) -> set[int]:
    return {i for s in spans for i in range(s.start, s.end)}


def ratio(numerator: int | float, denominator: int | float) -> dict:
    return {"value": numerator / denominator if denominator else None,
            "numerator": numerator, "denominator": denominator,
            "null_reason": None if denominator else "zero_denominator"}


def score(observations: Sequence[Observation]) -> dict:
    counts = {label: {"tp": 0, "fp": 0, "fn": 0} for label in LABELS}
    sensitive = residual = benign = removed_benign = leak_records = 0
    benign_records = benign_redacted_records = unavailable = structure_failures = 0
    for row in observations:
        gold = _triples(row.gold)
        predicted = _triples(row.predicted) if row.available else set()
        for label in LABELS:
            g = {s for s in gold if s[2] == label}
            p = {s for s in predicted if s[2] == label}
            counts[label]["tp"] += len(g & p)
            counts[label]["fp"] += len(p - g)
            counts[label]["fn"] += len(g - p)
        gm = _mask(row.gold)
        pm = _mask(row.predicted) if row.available and row.structure_valid else set()
        remaining = gm - pm
        sensitive += len(gm)
        residual += len(remaining)
        benign += row.length - len(gm)
        removed_benign += len(pm - gm)
        leak_records += bool(remaining)
        unavailable += not (row.available and row.structure_valid)
        structure_failures += row.available and not row.structure_valid
        benign_records += not gm
        benign_redacted_records += not gm and bool(pm)
    def quality(c: dict) -> dict:
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        return {**c, "support": tp + fn, "predicted_count": tp + fp,
                "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
                "f1": ratio(2 * tp, 2 * tp + fp + fn)}
    per_class = {label: quality(c) for label, c in counts.items()}
    total = {k: sum(c[k] for c in counts.values()) for k in ("tp", "fp", "fn")}
    macro = {}
    for metric in ("precision", "recall", "f1"):
        values = [c[metric]["value"] for c in per_class.values()]
        macro[metric] = {"value": sum(values) / len(values) if all(v is not None for v in values) else None,
                         "null_reason": None if all(v is not None for v in values) else "undefined_class",
                         "defined_classes": sum(v is not None for v in values), "class_count": len(LABELS)}
    unsafe = sum(not r.available or not r.structure_valid or bool(_mask(r.gold) - _mask(r.predicted)) for r in observations)
    answered = sum(r.available and r.structure_valid for r in observations)
    return {"corpus_N": len(observations), "eligible_N": len(observations),
            "answered_N": answered, "error_N": len(observations) - answered,
            "per_class": per_class, "micro": quality(total), "macro": macro,
            "residual_sensitive_codepoints": ratio(residual, sensitive),
            "records_with_residual": ratio(leak_records, len(observations)),
            "benign_codepoints_redacted": ratio(removed_benign, benign),
            "benign_record_overredaction": ratio(benign_redacted_records, benign_records),
            "unavailable": ratio(unavailable, len(observations)),
            "unsafe_or_unavailable": ratio(unsafe, len(observations)),
            "structure_failures": structure_failures}


__all__ = ["Observation", "score", "ratio"]
