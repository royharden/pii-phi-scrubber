"""Paired provenance-block percentile bootstrap, never span resampling."""
from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from typing import Callable, Sequence

from . import LABELS, Observation, score


def paired_interval(left: Sequence[Observation], right: Sequence[Observation] | None,
                    metric: Callable[[dict], float | None], *, seed: int = 7,
                    draws: int = 2000, minimum_blocks: int = 20,
                    minimum_valid: int = 1800) -> dict:
    if draws != 2000 or minimum_blocks < 20 or minimum_valid < 1800:
        raise ValueError("preregistered_bootstrap_limits")
    lm = {r.record_id: r for r in left}
    rm = {r.record_id: r for r in right} if right is not None else lm
    if len(lm) != len(left) or (right is not None and len(rm) != len(right)) or lm.keys() != rm.keys():
        raise ValueError("unpaired_population")
    groups = defaultdict(list)
    for key, row in lm.items():
        if row.block_id != rm[key].block_id or row.slice_name != rm[key].slice_name:
            raise ValueError("unpaired_provenance")
        if row.length != rm[key].length or {(s.start,s.end,s.label) for s in row.gold} != {(s.start,s.end,s.label) for s in rm[key].gold}:
            raise ValueError("unpaired_gold")
        groups[row.block_id].append(key)
    blocks = sorted(groups)
    result = {"method": "paired_group_percentile", "level": 0.95, "draws": draws,
              "seed": seed, "effective_blocks": len(blocks), "valid_draws": 0,
              "undefined_draws": 0, "interval": None, "null_reason": None,
              "draw_digest": None}
    if len(blocks) < minimum_blocks:
        return {**result, "null_reason": "insufficient_units"}
    rng = random.Random(seed)
    digest = hashlib.sha256()
    values = []
    for _ in range(draws):
        selected = [rng.choice(blocks) for _ in blocks]
        digest.update(json.dumps(selected, separators=(",", ":")).encode())
        ids = [key for block in selected for key in groups[block]]
        a = metric(score([lm[key] for key in ids]))
        b = metric(score([rm[key] for key in ids])) if right is not None else 0.0
        if a is not None and b is not None:
            values.append(a - b)
    result.update(valid_draws=len(values), undefined_draws=draws-len(values), draw_digest=digest.hexdigest())
    if len(values) < minimum_valid:
        return {**result, "null_reason": "insufficient_valid_draws"}
    values.sort()
    def percentile(p: float) -> float:
        position = (len(values) - 1) * p
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        return values[lower] + (values[upper] - values[lower]) * (position - lower)
    return {**result, "interval": [percentile(.025), percentile(.975)]}


def quality_intervals(rows: Sequence[Observation], *, seed: int = 7) -> dict:
    """Absolute per-class P/R/F1 plus macro F1, using the same block draws."""
    output = {"per_class": {}}
    for label in LABELS:
        output["per_class"][label] = {}
        for metric in ("precision", "recall", "f1"):
            output["per_class"][label][metric] = paired_interval(
                rows, None, lambda m, label=label, metric=metric: m["per_class"][label][metric]["value"], seed=seed)
    output["macro_f1"] = paired_interval(rows, None, lambda m: m["macro"]["f1"]["value"], seed=seed)
    return output
