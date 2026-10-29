"""Independent W2 product packet tests: a readiness display never creates authority."""

import json
import warnings

import pytest

from m7.experiment.readiness import ExperimentReadiness, assess_readiness
from m7.publish.acceptance import render_acceptance_packet, write_acceptance_packet


def test_default_packet_keeps_holds_and_actual_results_unmeasured():
    document = render_acceptance_packet(assess_readiness())
    assert "NOT_READY" in document
    for hold in ("H1", "H2", "H3", "H4", "H5", "H6"):
        assert f"{hold}: held" in document
    for arm in ("regex", "frontier", "base", "finetuned"):
        assert f"<th>{arm}</th><td>NOT_MEASURED</td>" in document
    assert "Population evidence missing; counts NOT_MEASURED" in document
    assert "<th>economic_total_micros</th><td>unknown</td>" in document
    assert "not an independent verdict" in document
    assert "No privacy or compliance certification is issued" in document
    assert "<script" not in document.lower()
    assert "<canvas" not in document.lower()


def test_valid_canonical_json_projection_matches_model_display():
    result = assess_readiness(evidence_kind="mock")
    payload = json.loads(result.model_dump_json())
    assert render_acceptance_packet(payload) == render_acceptance_packet(result)
    assert "Evidence kind: mock" in render_acceptance_packet(payload)


@pytest.mark.parametrize("field,value", [
    ("status", "READY"), ("actual_model_execution", True),
    ("execution_allowed", True), ("product_acceptance", True),
    ("held_decisions", []), ("checks", []), ("blockers", []),
])
def test_edited_model_instances_are_revalidated_before_display(field, value):
    # what_bug_this_catches: trusted-looking model_copy/model_construct bypasses
    # can forge authority; the consumer must rerun canonical validation.
    result = assess_readiness().model_copy(update={field: value})
    with pytest.raises(ValueError, match="^canonical_readiness_required$"):
        render_acceptance_packet(result)


@pytest.mark.parametrize("location", ("extra", "check_reason", "cost_status"))
def test_hostile_free_text_is_refused_without_echo_in_error_or_artifact(tmp_path, location):
    marker = "public-only-secret-like-value<script>alert('fixture')</script>"
    payload = assess_readiness().model_dump(mode="json")
    if location == "extra":
        payload[marker] = marker
    elif location == "check_reason":
        payload["checks"][0]["reason"] = marker
    else:
        payload["cost"]["status"] = marker
    target = tmp_path / "m7-refused-packet.html"
    with pytest.raises(ValueError) as error:
        write_acceptance_packet(payload, target)
    assert str(error.value) == "canonical_readiness_required"
    assert marker not in str(error.value)
    assert not target.exists()


@pytest.mark.parametrize("field", ("evidence_kind", "held_decisions", "checks", "blockers"))
def test_forged_model_warning_cannot_echo_source_values(tmp_path, field):
    # what_bug_this_catches: serializing an invalid model before revalidation may
    # emit Pydantic warnings containing the raw supplied value despite a safe error.
    marker = "public-only-sensitive-fixture-marker"
    forged = assess_readiness().model_copy(update={field: marker if field == "evidence_kind" else [marker]})
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        with pytest.raises(ValueError, match="^canonical_readiness_required$"):
            write_acceptance_packet(forged, tmp_path / "m7-warning-refused.html")
    assert all(marker not in str(item.message) for item in emitted)
    assert not (tmp_path / "m7-warning-refused.html").exists()


def test_packet_does_not_reevaluate_adoption_or_execute_readiness(monkeypatch):
    result = assess_readiness()
    def forbidden(*args, **kwargs):
        raise AssertionError("display_must_not_assess_or_execute")
    monkeypatch.setattr("m7.experiment.adoption.adoption_report", forbidden)
    monkeypatch.setattr("m7.experiment.readiness.assess_readiness", forbidden)
    document = render_acceptance_packet(result)
    assert "NOT_READY" in document


def test_exclusive_writer_preserves_previous_artifact(tmp_path):
    target = tmp_path / "m7-existing.html"
    target.write_text("previous-public-artifact", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_acceptance_packet(assess_readiness(), target)
    assert target.read_text(encoding="utf-8") == "previous-public-artifact"


def test_writer_emits_only_validated_preparation_packet(tmp_path):
    target = tmp_path / "m7-new.html"
    result = ExperimentReadiness.model_validate_json(assess_readiness().model_dump_json())
    write_acceptance_packet(result, target)
    assert target.read_text(encoding="utf-8") == render_acceptance_packet(result)
