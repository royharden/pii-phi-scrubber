"""Readiness CLI is a refusal/report path, not an alternative execution switch."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import m7.experiment.readiness


def run_cli(directory, *arguments):
    # Derive the script from the imported exact candidate source, including when
    # this independent test suite is consumed against a review-source overlay.
    source = Path(m7.experiment.readiness.__file__).resolve().parents[3]
    return subprocess.run([sys.executable, str(source / "scripts" / "eval.py"), *arguments],
                          cwd=directory, capture_output=True, text=True, timeout=30)


def test_readiness_cli_reports_not_ready_with_refusal_exit_and_no_outputs(tmp_path):
    result = run_cli(tmp_path, "--readiness")
    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "ExperimentReadiness/v1"
    assert payload["status"] == "NOT_READY"
    assert payload["actual_model_execution"] is False
    assert payload["execution_allowed"] is False
    assert payload["product_acceptance"] is False
    assert payload["held_decisions"] == ["H1", "H2", "H3", "H4", "H5", "H6"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("arguments", [
    ("--execute-locked",), ("--execute-campaign",), ("--edition", "development"),
    ("--operator-host", "untrusted.module:factory"), ("--operator-host", "none"),
    ("--result-sha256", "none"), ("--arms", "regex"), ("--out", "m7-forbidden.html"),
])
def test_readiness_cli_rejects_every_explicit_execution_or_extra_input(tmp_path, arguments):
    # what_bug_this_catches: a globally exempt sentinel string could silently
    # accept an explicit operator-host/receipt argument on the input-free mode.
    result = run_cli(tmp_path, "--readiness", *arguments)
    assert result.returncode == 2
    assert result.stdout == ""
    assert list(tmp_path.iterdir()) == []
