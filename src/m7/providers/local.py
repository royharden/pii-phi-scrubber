"""Lazy GLiNER integration: exact local pins, original text and fail-closed limits.

The integration is source only. No optional library imports happen at module load.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from importlib.metadata import version
import json
import os
from threading import RLock
from typing import Protocol

from m7.contracts import LogRecord, Span
from m7.detectors.model import TokenSpan
from .contracts import AdapterFault, ExecutionPermit, LocalModelConfig, config_digest, verify_artifacts
from .parity import validate_architecture

LABELS = ("NAME", "EMAIL", "PHONE", "ACCOUNT_ID")
_OFFLINE_LOCK = RLock()


class LocalBackend(Protocol):
    def preflight(self, message: str) -> int:
        """Return full prompt+message token count or raise; no inference/truncation."""
        ...

    def predict(self, record: LogRecord) -> TokenSpan: ...


LocalLoader = Callable[[LocalModelConfig], LocalBackend]


@contextmanager
def _offline():
    # Offline flags plus explicit local paths/local_files_only/token=False are
    # defense in depth, not an OS network sandbox. Do not share this process with
    # workers mutating library/global environment while loading approved artifacts.
    flags = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
             "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "HF_HUB_DISABLE_TELEMETRY": "1"}
    with _OFFLINE_LOCK:
        previous = {key: os.environ.get(key) for key in flags}
        os.environ.update(flags)
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class GlinerBackend:
    """Adapter for the approved uni-encoder GLiNER package revision.

    Internal processor/splitter API is version-pinned and requires later runtime
    validation. Unsupported layouts fail closed instead of guessing token limits.
    """

    def __init__(self, config: LocalModelConfig):
        self.config = config
        if config.arm == "base" and (config.base_weights_sha256 != config.weights_sha256
                                    or config.training_receipt_sha256 is not None):
            raise AdapterFault("permit_required")
        model_path, backbone_path = verify_artifacts(config)
        if version("gliner") != config.gliner_version or version("transformers") != config.transformers_version:
            raise AdapterFault("unavailable")
        config_path = model_path / "gliner_config.json"
        if not config_path.is_file() or config_path.stat().st_size > 1_048_576:
            raise AdapterFault("permit_required")
        data = json.loads(config_path.read_text(encoding="utf-8"))
        # Rehoming must happen BEFORE artifact approval/hashing, never on load.
        if data.get("model_name") != str(backbone_path) or data.get("labels_encoder"):
            raise AdapterFault("permit_required")
        validate_architecture(data, config)
        with _offline():
            from gliner import GLiNER
            self.model = GLiNER.from_pretrained(str(model_path), local_files_only=True,
                                               token=False, load_tokenizer=False,
                                               map_location=config.device,
                                               compile_torch_model=False, strict=True)
            self.model.eval()

    def preflight(self, message: str) -> int:
        if len(message) > 1024 or any(0xD800 <= ord(c) <= 0xDFFF for c in message):
            raise AdapterFault("truncated")
        processor = self.model.data_processor
        words = []
        previous_end = 0
        for word, start, end in processor.words_splitter(message):
            if (type(start) is not int or type(end) is not int
                    or not previous_end <= start < end <= len(message)
                    or type(word) is not str or message[start:end] != word):
                raise AdapterFault("invalid_output")
            # The splitter may omit whitespace only, never an unrepresented tail.
            if message[previous_end:start].strip():
                raise AdapterFault("truncated")
            previous_end = end
            words.append(word)
        if message[previous_end:].strip():
            raise AdapterFault("truncated")
        configured_limit = self.model.config.max_len
        if (type(configured_limit) is not int or configured_limit <= 0
                or len(words) > min(configured_limit, self.config.max_words)):
            raise AdapterFault("truncated")
        tokenizer = processor.transformer_tokenizer
        limit = tokenizer.model_max_length
        if type(limit) is not int or not 1 <= limit <= 131072:
            raise AdapterFault("unavailable")
        # Count the SAME label-prompt/word representation used by the processor,
        # including special tokens. A plain-text token estimate would undercount.
        inputs, _ = processor.prepare_inputs([words], list(self.config.decoder.labels))
        encoded = tokenizer(inputs, is_split_into_words=True, truncation=False,
                            padding=False, add_special_tokens=True)
        ids = encoded["input_ids"]
        if (type(ids) is not list or len(ids) != 1 or type(ids[0]) is not list
                or any(type(token) is not int for token in ids[0])):
            raise AdapterFault("invalid_output")
        count = len(ids[0])
        if count > min(limit, self.config.max_input_tokens):
            raise AdapterFault("truncated")
        return count

    def predict(self, record: LogRecord) -> TokenSpan:
        self.preflight(record.log.message)
        decoder = self.config.decoder
        with _offline():
            from torch import inference_mode
            with inference_mode():
                entities = self.model.predict_entities(record.log.message, list(decoder.labels),
                    threshold=decoder.threshold, flat_ner=decoder.flat_ner, multi_label=decoder.multi_label)
        if type(entities) is not list or len(entities) > 128:
            raise AdapterFault("invalid_output")
        spans = []
        mapping = dict(zip(decoder.labels, LABELS, strict=True))
        for entity in entities:
            if type(entity) is not dict or set(entity) != {"start", "end", "text", "label", "score"}:
                raise AdapterFault("invalid_output")
            start, end = entity["start"], entity["end"]
            if (type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(record.log.message)
                    or entity["text"] != record.log.message[start:end]
                    or entity["label"] not in mapping or type(entity["score"]) is not float):
                raise AdapterFault("invalid_output")
            spans.append(Span(start=start, end=end, label=mapping[entity["label"]],
                              confidence=entity["score"]))
        return TokenSpan(spans=tuple(spans), truncated=False, input_sha256=record.content_sha256,
                         offset_unit="unicode_codepoint")


class PermittedLocalBackend:
    """Lazy instance: validate permission on every request, before any loader I/O."""

    def __init__(self, config: LocalModelConfig, permit: ExecutionPermit, *, run_id: str,
                 loader: LocalLoader | None = None, allow_execution: bool = False):
        self.config, self.permit, self.run_id = config, permit, run_id
        self.loader = loader or GlinerBackend
        self.allow_execution = allow_execution
        self._backend: LocalBackend | None = None
        self._lock = RLock()
        self._warm_backend = None
        self._warm_id = None
        self._physical_calls = 0

    def check(self) -> None:
        if not self.allow_execution:
            raise AdapterFault("permit_required")
        self.permit.check(run_id=self.run_id, model_id=self.config.model_id,
                          scope="local_inference", config_sha256=config_digest(self.config))

    def _ensure_loaded(self) -> LocalBackend:
        self.check()
        if self._backend is None:
            # Injected engines obey the same artifact boundary as real loaders.
            verify_artifacts(self.config)
            self._backend = self.loader(self.config)
            from uuid import uuid4
            self._warm_backend = self._backend
            self._warm_id = "local-" + uuid4().hex
        return self._backend

    def warm_state(self):
        """Inspect existing instance only; never load or warm on demand."""
        with self._lock:
            self.check()
            if self._backend is None or self._backend is not self._warm_backend or not self._physical_calls:
                raise AdapterFault("unavailable")
            return self._warm_id, self._physical_calls

    def preflight(self, records: tuple[LogRecord, ...]) -> None:
        with self._lock:
            backend = self._ensure_loaded()
            for record in records:
                self.check()
                backend.preflight(record.log.message)
            self.check()

    def __call__(self, record: LogRecord) -> TokenSpan:
        with self._lock:
            backend = self._ensure_loaded()
            backend.preflight(record.log.message)
            self.check()  # Loading/preflight may consume the remaining permit time.
            self._physical_calls += 1
            result = backend.predict(record)
            if (not isinstance(result, TokenSpan) or result.truncated
                    or result.input_sha256 != record.content_sha256):
                raise AdapterFault("truncated" if isinstance(result, TokenSpan) and result.truncated
                                   else "invalid_output")
            return result

