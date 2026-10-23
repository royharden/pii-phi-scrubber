"""CLI support: fixed error enums, no raw exception/validation disclosure."""

import json
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(1, str(ROOT))


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate_json_key')
        value[key] = item
    return value


def _constant(_):
    raise ValueError('nonfinite_json')


def read_bounded(path: Path, maximum: int = 2_000_000) -> bytes:
    with path.open('rb') as handle:
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("input_too_large")
    return data


def load_json(path: Path) -> dict:
    value = json.loads(read_bounded(path), object_pairs_hook=_pairs, parse_constant=_constant)
    if not isinstance(value, dict):
        raise ValueError("object_required")
    return value


def load_boundary(path: Path, model):
    # Preserve strict JSON semantics for tuple fields; reject duplicates/nonfinite.
    return model.model_validate_json(json.dumps(load_json(path), allow_nan=False))


def approved_result(path: Path, expected_sha256: str) -> dict:
    from m7.experiment.result import public_aggregate
    raw = read_bounded(path, 16_000_000)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('approved_artifact_hash_mismatch')
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    if not isinstance(value, dict):
        raise ValueError('object_required')
    return public_aggregate(value)


def copy_approved_report(path: Path, expected_sha256: str, destination: Path) -> None:
    """Replay exactly the previously approved bytes; no new gold-free assembly."""
    raw = read_bounded(path, 16_000_000)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('approved_report_hash_mismatch')
    with destination.open('xb') as handle:
        handle.write(raw)


def emit(value: dict) -> None:
    print(json.dumps(value, allow_nan=False, sort_keys=True))


def guarded(main) -> None:
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        emit({'status': 'cancelled', 'reason': 'operator_interrupted'})
        raise SystemExit(130) from None
    except Exception:
        # The external provider/host may raise arbitrary exception types/bodies.
        # No exception text, paths, source values or validation bodies reach stdout.
        emit({"status": "error", "reason": "invalid_or_unavailable_input"})
        raise SystemExit(2) from None
