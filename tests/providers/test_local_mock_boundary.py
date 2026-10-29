"""W2 evidence_kind=mock: fail-closed local injection, never actual inference."""
from pathlib import Path

import pytest

from m7.detectors.model import TokenSpan
from m7.detectors.registry import build_registry
from m7.providers.contracts import AdapterFault
from m7.providers.local import PermittedLocalBackend
from m7.providers.parity import validate_pair

from .local_mock_fixtures import RECORD, RUN, MockBackend, local_config, permit_for


def permitted(config, mock, *, enabled=True):
    loads = []

    def loader(pinned):
        loads.append(pinned.model_id)
        return mock

    return PermittedLocalBackend(config, permit_for(config), run_id=RUN,
                                  loader=loader, allow_execution=enabled), loads


@pytest.mark.parametrize("entrypoint", ["corpus_preflight", "predict"])
@pytest.mark.parametrize("count,code", [
    (True, "invalid_output"), (False, "invalid_output"), ("8", "invalid_output"),
    (None, "invalid_output"), (7.0, "invalid_output"), (-1, "invalid_output"),
    (float("nan"), "invalid_output"), (float("inf"), "invalid_output"), (9, "truncated"),
])
def test_invalid_injected_token_count_never_reaches_predict(tmp_path, count, code, entrypoint):
    # Bug caught: the wrapper discarded count and trusted every injected loader;
    # a valid-looking span result could conceal over-limit/truncated input.
    config = local_config(tmp_path / "public-artifacts")
    mock = MockBackend(count)
    backend, loads = permitted(config, mock)
    with pytest.raises(AdapterFault) as caught:
        if entrypoint == "corpus_preflight":
            backend.preflight((RECORD,))
        else:
            backend(RECORD)
    assert caught.value.code == code
    assert loads == [config.model_id] and mock.prediction_calls == 0


@pytest.mark.parametrize("count", [1, 8])
def test_valid_count_including_exact_cap_allows_only_the_mock(tmp_path, count):
    config = local_config(tmp_path / "public-artifacts")
    mock = MockBackend(count)
    backend, loads = permitted(config, mock)
    backend.preflight((RECORD,))
    result = backend(RECORD)
    assert result.spans == () and result.input_sha256 == RECORD.content_sha256
    assert mock.prediction_calls == 1 and loads == [config.model_id]


def test_no_execution_grant_precedes_artifact_probe_or_loader(tmp_path, monkeypatch):
    # The constructor is inert; denied execution cannot inspect staged artifacts.
    config = local_config(tmp_path / "public-artifacts")
    mock = MockBackend()
    backend, loads = permitted(config, mock, enabled=False)
    probes = []

    def forbidden_probe(_):
        probes.append(True)
        raise AssertionError("artifact probe before grant")

    monkeypatch.setattr("m7.providers.local.verify_artifacts", forbidden_probe)
    with pytest.raises(AdapterFault) as caught:
        backend(RECORD)
    assert caught.value.code == "permit_required"
    assert not probes and not loads and mock.prediction_calls == 0


@pytest.mark.parametrize("defect", ["missing_root", "extra_file", "changed_weights"])
def test_artifact_refusal_precedes_injected_loader(tmp_path, defect):
    config = local_config(tmp_path / "public-artifacts")
    if defect == "missing_root":
        config = config.model_copy(update={"artifact_root": str(tmp_path / "missing")})
    elif defect == "extra_file":
        (Path(config.artifact_root) / "unexpected.json").write_text("{}", encoding="utf-8")
    else:
        (Path(config.artifact_root) / "model/model.safetensors").write_bytes(b"different-public-fake-bytes")
    mock = MockBackend()
    backend, loads = permitted(config, mock)
    with pytest.raises(AdapterFault) as caught:
        backend(RECORD)
    assert caught.value.code == "permit_required"
    assert not loads and mock.preflight_calls == mock.prediction_calls == 0


@pytest.mark.parametrize("phase", ["during_preflight", "after_cached_prediction"])
def test_revoked_permit_cannot_use_loaded_mock(tmp_path, phase):
    config = local_config(tmp_path / "public-artifacts")
    mock = MockBackend()
    backend, loads = permitted(config, mock)

    def revoke():
        backend.permit = backend.permit.model_copy(update={"expires_at": "2020-01-02T00:00:00Z"})

    if phase == "during_preflight":
        mock.preflight_effect = revoke
    else:
        backend(RECORD)
        revoke()
    with pytest.raises(AdapterFault) as caught:
        backend(RECORD)
    assert caught.value.code == "permit_required"
    assert mock.prediction_calls == (0 if phase == "during_preflight" else 1)
    assert mock.preflight_calls == 1 and loads == [config.model_id]


@pytest.mark.parametrize("truncated,hash_value,code", [
    (True, RECORD.content_sha256, "truncated"), (False, "0" * 64, "invalid_output"),
])
def test_bad_mock_result_remains_terminal(tmp_path, truncated, hash_value, code):
    config = local_config(tmp_path / "public-artifacts")
    result = TokenSpan(spans=(), truncated=truncated, input_sha256=hash_value, offset_unit="unicode_codepoint")
    mock = MockBackend(result=result)
    backend, _ = permitted(config, mock)
    with pytest.raises(AdapterFault) as caught:
        backend(RECORD)
    assert caught.value.code == code and mock.prediction_calls == 1


def fine_from(base):
    return base.model_copy(update={"arm": "finetuned", "model_id": "public-mock-fine",
                                   "training_receipt_sha256": "4" * 64})


@pytest.mark.parametrize("drift", ["base_revision", "base_weights_sha256", "tokenizer_sha256",
                                   "architecture_sha256", "max_input_tokens", "device",
                                   "label_order", "selection_policy"])
def test_base_fine_drift_is_refused_before_backend_construction(tmp_path, monkeypatch, drift):
    base = local_config(tmp_path / "public-artifacts")
    fine = fine_from(base)
    if drift in ("label_order", "selection_policy"):
        change = ({"labels": tuple(reversed(fine.decoder.labels))} if drift == "label_order"
                  else {"threshold_selection_sha256": "5" * 64})
        fine = fine.model_copy(update={"decoder": fine.decoder.model_copy(update=change)})
    else:
        value = {"base_revision": "different-revision", "base_weights_sha256": "6" * 64,
                 "tokenizer_sha256": "7" * 64, "architecture_sha256": "8" * 64,
                 "max_input_tokens": 9, "device": "cuda"}[drift]
        fine = fine.model_copy(update={drift: value})
    constructions = []

    def forbidden_backend(*args, **kwargs):
        constructions.append(True)
        raise AssertionError("backend before parity")

    monkeypatch.setattr("m7.detectors.registry.PermittedLocalBackend", forbidden_backend)
    with pytest.raises(AdapterFault) as caught:
        build_registry({"base": base, "finetuned": fine},
                       {"base": permit_for(base), "finetuned": permit_for(fine)}, run_id=RUN)
    assert caught.value.code == "permit_required" and not constructions


def test_dev_selected_threshold_difference_is_pure_and_permitted(tmp_path, monkeypatch):
    base = local_config(tmp_path / "public-artifacts")
    fine = fine_from(base).model_copy(update={"decoder": base.decoder.model_copy(update={"threshold": 0.75})})

    def forbidden_open(*args, **kwargs):
        raise AssertionError("parity must not read artifacts")

    monkeypatch.setattr(Path, "open", forbidden_open)
    assert validate_pair(base, fine) is None
