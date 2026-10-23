"""Validate adapter specifications; explicitly permitted LOCAL inference is opt-in.

Future operator entrypoint. Construction has never run this script. External model
execution uses an injected host registry: no provider/tokenizer/key is auto-selected.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from _common import emit, guarded
from pydantic import TypeAdapter
from m7.contracts import Identifier, LogRecord
from m7.detectors.registry import build_registry
from m7.ledger import BudgetExceeded, ReservationLedger
from m7.providers.contracts import (AdapterFault, AttemptPolicy, ExecutionPermit,
                                   FrontierConfig, LocalModelConfig, config_digest)
from m7.providers.parity import validate_pair


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("nonfinite_json")


def read_spec(path: Path):
    if path.stat().st_size > 2_000_000:
        raise ValueError("spec_byte_limit")
    raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    if (type(raw) is not dict or set(raw) != {"schema_version", "run_id", "configs", "permits", "policies"}
            or raw["schema_version"] != "AdapterRegistry/v2"
            or any(type(raw[key]) is not dict for key in ("configs", "permits", "policies"))):
        raise ValueError("invalid_adapter_spec")
    configs = {}
    for arm, row in raw["configs"].items():
        if arm not in ("base", "finetuned", "frontier"):
            raise ValueError("unknown_arm")
        # JSON validation preserves strict scalar types while allowing JSON arrays
        # for the immutable tuple fields. Python-mode strict validation would
        # incorrectly reject those arrays after load_json decoded them to lists.
        configs[arm] = (FrontierConfig if arm == "frontier" else LocalModelConfig).model_validate_json(
            json.dumps(row, allow_nan=False))
    permits = {arm: ExecutionPermit.model_validate(row) for arm, row in raw["permits"].items()}
    policies = {arm: AttemptPolicy.model_validate(row) for arm, row in raw["policies"].items()}
    if not configs or set(configs) != set(permits) or set(configs) != set(policies):
        raise ValueError("adapter_config_mismatch")
    run_id = TypeAdapter(Identifier).validate_python(raw["run_id"], strict=True)
    if "finetuned" in configs:
        if "base" not in configs:
            raise ValueError("base_fine_pair_required")
        validate_pair(configs["base"], configs["finetuned"])
    return run_id, configs, permits, policies


def inference_records(path: Path, *, max_records: int) -> tuple[LogRecord, ...]:
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("corpus_byte_limit")
    rows, seen = [], set()
    with path.open("rb") as source:
        while line := source.readline(32769):
            if len(line) > 32768:
                raise ValueError("record_line_limit")
            raw = json.loads(line, object_pairs_hook=_pairs, parse_constant=_constant)
            record = LogRecord.model_validate_json(json.dumps(raw, allow_nan=False))
            if record.split_id != "inference" or record.record_id in seen or len(rows) >= max_records:
                raise ValueError("inference_identity_limit")
            rows.append(record)
            seen.add(record.record_id)
    if not rows:
        raise ValueError("empty_inference_population")
    return tuple(rows)


def infer_records(records: tuple[LogRecord, ...], registry, *, emit_prediction=emit) -> None:
    """Reusable injected-host seam; no provider selection, retries or gold access here."""
    for adapter in registry.values():
        adapter.preflight(records)
    for record in records:
        for arm, adapter in registry.items():
            try:
                prediction = adapter(record)
            except BudgetExceeded:
                emit_prediction({"record_id": record.record_id, "arm": arm,
                                 "status": "unattempted", "error_code": "budget_rejected"})
            else:
                # Only span wire, never source or rendered text, reaches stdout.
                emit_prediction(prediction.model_dump(mode="json"))


def main():
    if sys.argv[1:] == ["--worker"]:
        # Only the explicitly verified parent launcher supplies this stdio mode.
        # No spec/path flag, module import name or credentials come from its wire.
        from m7.providers.worker_service import serve_worker
        return serve_worker(sys.stdin.buffer, sys.stdout.buffer)
    if "--validate-worker" in sys.argv[1:]:
        from m7.providers.worker import validate_worker_spec
        from m7.providers.worker_profile import WorkerLaunchPolicy, WorkerProfile
        from m7.providers.worker_wire import MAX_BOOTSTRAP_BYTES, WorkerBootstrap, decode_line
        worker_parser = argparse.ArgumentParser(description="Validate only; never launch a worker")
        worker_parser.add_argument("--validate-worker", action="store_true", required=True)
        worker_parser.add_argument("--bootstrap", type=Path, required=True)
        worker_parser.add_argument("--policy", type=Path, required=True)
        worker_parser.add_argument("--profile", type=Path, required=True)
        worker_args = worker_parser.parse_args()
        def read_boundary(path, schema):
            with path.open("rb") as source:
                raw = source.read(MAX_BOOTSTRAP_BYTES + 1)
            if not raw.endswith(b"\n"):
                raw += b"\n"
            return decode_line(raw, schema, limit=MAX_BOOTSTRAP_BYTES)
        emit(validate_worker_spec(read_boundary(worker_args.bootstrap, WorkerBootstrap),
                                  read_boundary(worker_args.policy, WorkerLaunchPolicy),
                                  profile=read_boundary(worker_args.profile, WorkerProfile)))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--execute-local", action="store_true")
    parser.add_argument("--records", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--diagnostics", type=Path)
    args = parser.parse_args()
    if args.validate_only == args.execute_local:
        raise ValueError("choose_exactly_one_mode")
    run_id, configs, permits, policies = read_spec(args.spec)
    # Dry validation checks bindings/expiry, not receipt authenticity or artifacts.
    for arm, config in configs.items():
        if isinstance(config, FrontierConfig):
            policies[arm].require_frontier_bound(config)
        permits[arm].check(run_id=run_id, model_id=config.model_id,
            scope="frontier_inference" if arm == "frontier" else "local_inference",
            config_sha256=config_digest(config), attempt_policy_sha256=config_digest(policies[arm]))
    if args.validate_only:
        if any(value is not None for value in (args.records, args.ledger, args.diagnostics)):
            raise ValueError("records_not_needed")
        emit({"status": "spec_validated_only", "arms": sorted(configs),
              "executed": False, "artifact_pins_checked": False,
              "authorization_authenticity_checked": False})
        return 0
    if ("frontier" in configs or args.records is None or args.ledger is None
            or args.diagnostics is None):
        raise ValueError("local_execution_only")
    authorities = {(p.authorization_id, p.authorization_cap_micros) for p in policies.values()}
    if len(authorities) != 1:
        raise ValueError("shared_authorization_required")
    authorization_id, cap = authorities.pop()
    records = inference_records(args.records, max_records=min(p.max_records for p in policies.values()))
    ledger = ReservationLedger(args.ledger, cap_micros=cap, authorization_id=authorization_id)
    # Future explicit execution only: validation never creates/opens a database.
    ledger.initialize()
    with args.diagnostics.open("x", encoding="utf-8") as stream:
        def diagnostic_sink(event):
            stream.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        registry = build_registry(configs, permits, run_id=run_id, policies=policies,
            ledgers={arm: ledger for arm in configs}, diagnostic_sink=diagnostic_sink,
            allow_execution=True, include_regex=False)
        infer_records(records, registry)
    return 0


if __name__ == "__main__":
    def safe_main():
        try:
            return main()
        except AdapterFault:
            emit({"status": "error", "reason": "adapter_authority_or_preflight_rejected"})
            return 2
    guarded(safe_main)

