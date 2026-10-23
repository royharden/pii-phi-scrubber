"""Injected, permit-gated model boundary; never downloads or loads models."""
from collections.abc import Callable
from typing import Literal

from m7.contracts import Boundary, Digest, Identifier, LogRecord, Prediction, Span, failure, validate_prediction


class ModelPermit(Boundary):
    permit_id: Identifier
    model_id: Identifier
    weights_sha256: Digest
    tokenizer_sha256: Digest
    license_receipt_sha256: Digest
    authorization_sha256: Digest
    approved: Literal[True]


class TokenSpan(Boundary):
    """Backend must emit original-message code points, never byte/UTF16 offsets."""
    spans: tuple[Span, ...]
    truncated: bool
    input_sha256: Digest
    offset_unit: Literal['unicode_codepoint']


def detect_model(record: LogRecord, *, arm: Literal['base', 'finetuned'], model_id: str, run_id: str = 'development', permit: ModelPermit | None = None, backend: Callable[[str], TokenSpan] | None = None) -> Prediction:
    if permit is None or backend is None or not permit.approved or permit.model_id != model_id:
        return failure(record, run_id=run_id, arm=arm, model_id=model_id, status='unavailable', error_code='permit_required')
    try:
        result = backend(record.log.message)
        if not isinstance(result, TokenSpan) or result.input_sha256 != record.content_sha256:
            return failure(record, run_id=run_id, arm=arm, model_id=model_id)
        if result.truncated:
            return failure(record, run_id=run_id, arm=arm, model_id=model_id, error_code='truncated')
        return validate_prediction(record, Prediction(run_id=run_id, record_id=record.record_id, content_sha256=record.content_sha256, arm=arm, model_id=model_id, attempt_id='attempt-1', status='ok', spans=result.spans))
    except Exception:
        # Provider exception bodies may contain source; retain only this fixed enum.
        return failure(record, run_id=run_id, arm=arm, model_id=model_id, status='failed', error_code='backend_failure')
