"""Public fake bytes and in-memory mocks; never real weights or execution permits."""
import hashlib
import json

from m7.contracts import make_record
from m7.detectors.model import TokenSpan
from m7.providers.contracts import DecoderConfig, ExecutionPermit, FilePin, LocalModelConfig, config_digest

RUN = "public-mock-run"
RECORD = make_record("person: Fable Rowan", "public-mock-record", "inference")


def local_config(root):
    model, backbone = root / "model", root / "backbone"
    model.mkdir(parents=True)
    backbone.mkdir()
    fake_weights, fake_tokenizer = b"PUBLIC-MOCK-NOT-MODEL-WEIGHTS", b"{}"
    (model / "model.safetensors").write_bytes(fake_weights)
    (backbone / "tokenizer.json").write_bytes(fake_tokenizer)
    weight_sha = hashlib.sha256(fake_weights).hexdigest()
    tokenizer_sha = hashlib.sha256(fake_tokenizer).hexdigest()
    subtree = json.dumps({"tokenizer.json": tokenizer_sha}, sort_keys=True, separators=(",", ":")).encode()
    return LocalModelConfig(
        arm="base", model_id="public-mock-base", base_revision="public-mock-revision",
        base_weights_sha256=weight_sha, architecture_sha256="a" * 64,
        artifact_root=str(root.resolve()), model_subdir="model", backbone_subdir="backbone",
        files=(FilePin(relative_path="model/model.safetensors", sha256=weight_sha),
               FilePin(relative_path="backbone/tokenizer.json", sha256=tokenizer_sha)),
        weights_sha256=weight_sha, tokenizer_sha256=hashlib.sha256(subtree).hexdigest(),
        gliner_version="mock-version", transformers_version="mock-version",
        decoder=DecoderConfig(threshold_selection_sha256="b" * 64),
        max_input_tokens=8, max_words=16,
    )


def permit_for(config):
    # A structural test fixture, not an authenticated grant or signed approval.
    return ExecutionPermit(
        permit_id="public-mock-permit", run_id=RUN, model_id=config.model_id,
        scope="local_inference", config_sha256=config_digest(config),
        authorization_sha256="1" * 64, license_receipt_sha256="2" * 64,
        resource_receipt_sha256="3" * 64, issued_at="2020-01-01T00:00:00Z",
        expires_at="2099-01-01T00:00:00Z", approved=True,
    )


class MockBackend:
    def __init__(self, count=1, *, preflight_effect=None, result=None):
        self.count, self.preflight_effect, self.result = count, preflight_effect, result
        self.preflight_calls = self.prediction_calls = 0

    def preflight(self, message):
        assert message == RECORD.log.message
        self.preflight_calls += 1
        if self.preflight_effect:
            self.preflight_effect()
        return self.count

    def predict(self, record):
        self.prediction_calls += 1
        return self.result or TokenSpan(spans=(), truncated=False, input_sha256=record.content_sha256,
                                        offset_unit="unicode_codepoint")
