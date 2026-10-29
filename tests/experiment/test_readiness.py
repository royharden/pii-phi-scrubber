"""Independent W2 prerequisite controls; every fixture is public/mock metadata.

These tests exercise readiness reporting, never actual execution or W8 acceptance.
"""

import builtins
import json
import socket
import subprocess
import warnings
from pathlib import Path

import pytest
from pydantic import ValidationError

from m7.data.lifecycle import CustodyLifecycle
from m7.experiment.readiness import (
    ArmAccounting,
    ComponentFact,
    ExperimentReadiness,
    assess_readiness,
)
from m7.ledger import ReservationLedger

from .scenario import bundle, mixed_cells

EXPECTED_CHECKS = (
    "artifacts", "training", "providers", "training_plan", "preregistration",
    "campaign_binding", "intended_population", "costs", "H1", "H2", "H3", "H4", "H5", "H6",
)
EXPECTED_HOLDS = ("H1", "H2", "H3", "H4", "H5", "H6")


def checks(report):
    return {row.name: row for row in report.checks}


def assert_no_authority(report):
    assert report.status == "NOT_READY"
    assert report.actual_model_execution is False
    assert report.execution_allowed is False
    assert report.product_acceptance is False
    assert report.held_decisions == EXPECTED_HOLDS
    assert set(EXPECTED_HOLDS).issubset(report.blockers)


def test_default_readiness_names_every_missing_and_held_prerequisite():
    result = assess_readiness()
    assert_no_authority(result)
    assert result.evidence_kind == "readiness"
    assert tuple(row.name for row in result.checks) == EXPECTED_CHECKS
    for name in EXPECTED_HOLDS:
        assert (checks(result)[name].state, checks(result)[name].reason) == ("held", "held_by_roy")
    for name in EXPECTED_CHECKS[:7]:
        assert checks(result)[name].state == "missing"
    assert checks(result)["costs"].state == "unknown"
    assert result.cost.provider_cash_total_micros is None
    assert result.cost.economic_total_micros is None
    assert result.accounting == ()


def test_legitimate_canonical_readiness_survives_strict_json_roundtrip():
    # what_bug_this_catches: a model-before validator can turn JSON tuples into
    # Python lists before strict validation, making the producer wire unusable.
    report = assess_readiness()
    assert ExperimentReadiness.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize("state", ("mock", "shape_valid"))
def test_complete_producer_claims_cannot_close_scientific_or_product_holds(state):
    # what_bug_this_catches: three populated producer facts could be mistaken for
    # executed training/frontier or independent scientific/product acceptance.
    facts = tuple(ComponentFact(component=name, state=state, evidence_sha256="a" * 64)
                  for name in ("artifacts", "training", "providers"))
    result = assess_readiness(component_facts=facts, evidence_kind="mock")
    assert_no_authority(result)
    assert all(checks(result)[name].state == state for name in ("artifacts", "training", "providers"))
    assert checks(result)["preregistration"].state == "missing"
    assert checks(result)["campaign_binding"].state == "missing"


@pytest.mark.parametrize("key,value", [
    ("status", "READY"), ("evidence_kind", "actual"),
    ("actual_model_execution", True), ("actual_model_execution", 1),
    ("execution_allowed", True), ("execution_allowed", "false"),
    ("product_acceptance", True), ("product_acceptance", 0),
])
def test_forged_execution_and_acceptance_claims_are_refused(key, value):
    payload = assess_readiness().model_dump(mode="json")
    payload[key] = value
    with pytest.raises((ValidationError, ValueError)):
        ExperimentReadiness.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("mutation", ("missing_hold", "missing_check", "hide_blocker", "unhold"))
def test_readiness_cannot_hide_held_or_missing_checks(mutation):
    payload = assess_readiness().model_dump(mode="json")
    if mutation == "missing_hold":
        payload["held_decisions"].pop()
    elif mutation == "missing_check":
        payload["checks"].pop()
    elif mutation == "hide_blocker":
        payload["blockers"].remove("H6")
    else:
        payload["checks"][-1].update(state="shape_valid", reason="shape_only_not_authenticated")
        payload["blockers"].remove("H6")
    with pytest.raises((ValidationError, ValueError)):
        ExperimentReadiness.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("field,value", [
    ("corpus_N", True), ("attempted_N", -1), ("answered_N", 3),
    ("error_N", 0), ("unattempted_N", 0), ("corpus_N", 2.0),
])
def test_accounting_rejects_wrong_types_and_shrinking_failure_population(field, value):
    # Three intended records: two attempts, one answer, one error, one unattempted.
    row = dict(arm="regex", corpus_N=3, attempted_N=2, answered_N=1, error_N=1, unattempted_N=1)
    row[field] = value
    with pytest.raises((ValidationError, ValueError)):
        ArmAccounting(**row)


def test_valid_incomplete_population_remains_visible_without_execution_claims():
    result = assess_readiness(result_bundle=bundle(mixed_cells()), evidence_kind="mock")
    assert_no_authority(result)
    assert checks(result)["intended_population"].state == "shape_valid"
    assert len(result.accounting) == 4
    frontier = next(row for row in result.accounting if row.arm == "frontier")
    assert (frontier.corpus_N, frontier.attempted_N, frontier.answered_N,
            frontier.error_N, frontier.unattempted_N) == (2, 2, 1, 1, 0)
    assert checks(result)["preregistration"].state == "missing"


def test_malformed_result_is_invalid_without_repaired_or_invented_accounting():
    result = assess_readiness(result_bundle={"corpus_N": True, "arms": []})
    assert_no_authority(result)
    assert checks(result)["intended_population"].state == "invalid"
    assert result.accounting == ()


def test_zero_provider_invoice_does_not_measure_economic_total(tmp_path):
    ledger = ReservationLedger(tmp_path / "m7-readiness.sqlite3", cap_micros=0, authorization_id="m7-zero")
    ledger.initialize()
    ledger.reserve("m7-local", 0, category="training")
    ledger.reconcile("m7-local", actual_micros=0, state="succeeded", receipt_id="m7-invoice")
    summary = {**ledger.summary(), "scope_complete": True, "currency": "USD"}
    result = assess_readiness(cost_summary=summary)
    assert_no_authority(result)
    assert result.cost.provider_cash_total_micros == 0
    assert result.cost.economic_total_micros is None
    assert checks(result)["costs"].state == "unknown"


def test_validator_exceptions_are_fixed_diagnostics_without_source_bodies(monkeypatch):
    marker = "public-fixture-value-that-must-not-reach-diagnostics"
    def fail(*args, **kwargs):
        raise RuntimeError(marker)
    monkeypatch.setattr("m7.experiment.readiness.cost_report", fail)
    result = assess_readiness(training_plan={"raw_body": marker}, training_permit={})
    assert_no_authority(result)
    assert checks(result)["training_plan"].state == "invalid"
    assert checks(result)["costs"].state == "invalid"
    assert marker not in result.model_dump_json()


@pytest.mark.parametrize("field", ("component", "state"))
def test_invalid_producer_model_diagnostics_do_not_emit_supplied_values(field):
    marker = "public-only-producer-fixture-marker"
    fact = ComponentFact(component="providers", state="held").model_copy(update={field: [marker]})
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        with pytest.raises(ValidationError) as error:
            assess_readiness(component_facts=(fact,))
    assert marker not in str(error.value)
    assert all(marker not in str(item.message) for item in emitted)


def test_default_assessment_has_no_artifact_custody_process_or_network_effects(monkeypatch):
    calls = []
    def forbidden(*args, **kwargs):
        calls.append("forbidden_effect")
        raise AssertionError("readiness_effect_forbidden")
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(Path, "open", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(subprocess, "Popen", forbidden)
        patch.setattr(CustodyLifecycle, "__init__", forbidden)
        result = assess_readiness()
    assert calls == []
    assert_no_authority(result)
