"""Strict ephemeral quote anchoring. No requests, completions, or quote hashes persist."""
import json
from typing import Annotated

from pydantic import Field, ValidationError

from m7.contracts import Boundary, Label, LogRecord, Prediction, Span, failure


class Proposal(Boundary):
    label: Label
    quote: Annotated[str, Field(min_length=1, max_length=1024)]
    left_ctx: Annotated[str, Field(max_length=24)]
    right_ctx: Annotated[str, Field(max_length=24)]


def _unique(text: str, needle: str) -> int | None:
    index = text.find(needle)
    return index if index >= 0 and text.find(needle, index + 1) < 0 else None


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


def anchor_frontier(record: LogRecord, response: str, *, run_id: str = 'development', model_id: str, attempt_id: str = 'attempt-1') -> Prediction:
    """Call only on an already permitted backend response; this function does no I/O."""
    try:
        if type(response) is not str or len(response.encode('utf-8')) > 262144:
            raise ValueError('response_limit')
        raw = json.loads(response, object_pairs_hook=_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
        if type(raw) is not list or len(raw) > 128:
            raise ValueError('proposal_limit')
        proposals = [Proposal.model_validate(item) for item in raw]
        spans = []
        missing = 0
        for proposal in proposals:
            combined = proposal.left_ctx + proposal.quote + proposal.right_ctx
            index = _unique(record.log.message, combined)
            if index is not None:
                start = index + len(proposal.left_ctx)
            else:
                start = _unique(record.log.message, proposal.quote)
            if start is None:
                missing += 1
            else:
                spans.append(Span(start=start, end=start + len(proposal.quote), label=proposal.label))
        return Prediction(run_id=run_id, record_id=record.record_id, content_sha256=record.content_sha256, arm='frontier', model_id=model_id, attempt_id=attempt_id, status='ok', spans=tuple(spans), unanchored_count=missing)
    except (ValueError, TypeError, UnicodeError, ValidationError, RecursionError):
        return failure(record, run_id=run_id, arm='frontier', model_id=model_id, attempt_id=attempt_id)
