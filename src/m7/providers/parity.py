"""Cross-arm declarations and local artifact configuration parity, no execution."""
from __future__ import annotations

import hashlib
import json

from .contracts import AdapterFault, LocalModelConfig


def validate_pair(base: LocalModelConfig, fine: LocalModelConfig) -> None:
    if (base.arm != "base" or fine.arm != "finetuned"
            or base.base_weights_sha256 != base.weights_sha256
            or fine.base_weights_sha256 != base.weights_sha256
            or base.training_receipt_sha256 is not None or fine.training_receipt_sha256 is None):
        raise AdapterFault("permit_required")
    fields = ("base_revision", "tokenizer_sha256", "architecture_sha256", "gliner_version",
              "transformers_version", "max_input_tokens", "max_words", "device")
    if any(getattr(base, key) != getattr(fine, key) for key in fields):
        raise AdapterFault("permit_required")
    # Independently dev-selected thresholds may differ; the selection policy,
    # descriptions/order, decoder and mapping must match exactly.
    if base.decoder.model_dump(exclude={"threshold"}) != fine.decoder.model_dump(exclude={"threshold"}):
        raise AdapterFault("permit_required")


def validate_architecture(data: dict, config: LocalModelConfig) -> None:
    if type(data) is not dict:
        raise AdapterFault("permit_required")
    normalized = dict(data)
    # The approved absolute local backbone differs by machine/root; all semantic
    # configuration stays in the hash. No unlisted architecture fields are dropped.
    normalized["model_name"] = "local-backbone"
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != config.architecture_sha256:
        raise AdapterFault("permit_required")
