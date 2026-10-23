"""Paired provenance-block percentile bootstrap, never span resampling."""
from __future__ import annotations

import hashlib
import json
import math
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
              "draw_digest": None, "executed_draws": 0}
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
        if a is not None and b is not None and math.isfinite(a) and math.isfinite(b):
            values.append(a - b)
    result.update(valid_draws=len(values), undefined_draws=draws-len(values),
                  executed_draws=draws, draw_digest=digest.hexdigest())
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
    """All absolute quality/harm intervals from one common block-draw stream."""
    return metric_intervals(rows, seed=seed)


def metric_intervals(left: Sequence[Observation], right: Sequence[Observation] | None = None,
                     *, seed: int = 7) -> dict:
    """2,000 paired whole-block draws, fixed 95% and >=1,800 defined draws.

    Quality undefined in a draw stays undefined. No zero fill, span resampling,
    record dropping or ad-hoc retry of undefined draws. Same block draw digest for
    all rows within this scope; total/normal/challenge have separate visible units.
    """
    lm = {r.record_id: r for r in left}
    rm = {r.record_id: r for r in right} if right is not None else lm
    if len(lm) != len(left) or (right is not None and len(rm) != len(right)) or lm.keys() != rm.keys():
        raise ValueError('unpaired_population')
    groups = defaultdict(list)
    for key in sorted(lm):
        a, b = lm[key], rm[key]
        if (a.block_id != b.block_id or a.slice_name != b.slice_name or a.length != b.length
                or {(s.start, s.end, s.label) for s in a.gold} != {(s.start, s.end, s.label) for s in b.gold}):
            raise ValueError('unpaired_gold_or_provenance')
        groups[a.block_id].append(key)
    blocks = sorted(groups)
    harm_keys = ('residual_sensitive_codepoints', 'records_with_residual', 'benign_codepoints_redacted',
                 'benign_record_overredaction', 'unavailable', 'unsafe_or_unavailable')
    paths = [('per_class', label, metric) for label in LABELS for metric in ('precision', 'recall', 'f1')]
    paths += [(group, metric) for group in ('micro', 'macro') for metric in ('precision', 'recall', 'f1')]
    paths += [(key,) for key in harm_keys]
    values = {path: [] for path in paths}
    digest = hashlib.sha256()
    executed = 0

    def extract(metrics, path):
        for key in path:
            metrics = metrics[key]
        value = metrics['value']
        return value if value is not None and math.isfinite(value) else None

    if len(blocks) >= 20:
        rng = random.Random(seed)
        for _ in range(2000):
            selected = [rng.choice(blocks) for _ in blocks]
            digest.update(json.dumps(selected, separators=(',', ':')).encode())
            ids = [key for block in selected for key in groups[block]]
            a = score([lm[key] for key in ids])
            b = score([rm[key] for key in ids]) if right is not None else None
            for path in paths:
                av = extract(a, path)
                bv = extract(b, path) if b is not None else 0.0
                if av is not None and bv is not None:
                    values[path].append(av - bv)
            executed += 1

    def interval(samples):
        result = {'method': 'paired_group_percentile', 'level': .95, 'draws': 2000,
                  'seed': seed, 'effective_blocks': len(blocks), 'executed_draws': executed,
                  'valid_draws': len(samples), 'undefined_draws': executed - len(samples),
                  'draw_digest': digest.hexdigest() if executed else None,
                  'interval': None, 'null_reason': None}
        if len(blocks) < 20:
            return {**result, 'null_reason': 'insufficient_units'}
        if len(samples) < 1800:
            return {**result, 'null_reason': 'insufficient_valid_draws'}
        ordered = sorted(samples)
        def percentile(p):
            position = (len(ordered) - 1) * p
            low = int(position)
            high = min(low + 1, len(ordered) - 1)
            return ordered[low] + (ordered[high] - ordered[low]) * (position - low)
        return {**result, 'interval': [percentile(.025), percentile(.975)]}

    output = {'per_class': {label: {} for label in LABELS}, 'micro': {}, 'macro': {}}
    for path in paths:
        destination = output
        for key in path[:-1]:
            destination = destination[key]
        destination[path[-1]] = interval(values[path])
    # Retain the original report's explicit lookup without a second computation.
    output['macro_f1'] = output['macro']['f1']
    return output
