"""Public evaluator has an independent oracle and detects planted scorer corruption."""

import runpy
from pathlib import Path

import m7.runner


def harness():
    return runpy.run_path(str(Path(__file__).resolve().parents[2] / "evals" / "public_eval.py"))


def test_public_controls_pass_without_models_or_private_inputs():
    result = harness()["controls"]()
    assert len(result) == 6
    assert all(result.values())


def test_public_oracle_detects_planted_bad_exact_count(monkeypatch):
    # what_bug_this_catches: a harness that asserts only presence/shape could
    # certify a scorer which invents true positives. The literal oracle refuses it.
    original = m7.runner.score
    def corrupt(rows):
        result = original(rows)
        result["micro"]["tp"] = 999
        return result
    monkeypatch.setattr(m7.runner, "score", corrupt)
    result = harness()["controls"]()
    assert result["exact_and_unrun"] is False
    assert result["partial_no_overlap_credit"] is False
