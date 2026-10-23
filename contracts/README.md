# Wire v1

`m7.contracts` is the authoritative schema. Python 3.12 and Pydantic 2 are intended;
compatibility has not been exercised. Models are frozen, strict, forbid extra keys,
and hide input values in exception strings. Never serialize `ValidationError.errors()`
without `include_input=False`; externally emit fixed error enums only.

`LogRecord(record_id, split_id, synthetic=True, content_sha256, log)` contains
`LogFields(timestamp, level, event, message)`. Only message contains fictional entities.
Hash the original decoded message as UTF-8; spans use inclusive start/exclusive end
Python Unicode code points without normalization. Reject surrogates and inputs over
1,024 code points. Timestamp is bounded ISO-shaped text; levels/events are enums.

`Span(start, end, label, confidence=None)` uses NAME/EMAIL/PHONE/ACCOUNT_ID.
`Prediction(run_id, record_id, content_sha256, arm, model_id, attempt_id, status,
spans=(), duration_ms=None, usage_ref=None, error_code=None, unanchored_count=0)`
persists offsets only. `validate_prediction(record, prediction)` rejects identity or
range disagreement as terminal invalid output. Duplicate exact triples collapse;
overlaps remain for exact scoring. Unmeasured timing is null.

`render(record, prediction)` returns `RenderResult(record_id, content_sha256,
renderer_version, safe_log, intervals, schema_valid, error_code)`. Intersecting spans
form unions; adjacent spans remain separate. Each interval carries start/end,
placeholder, candidate_ids (indices into sorted deduplicated spans), cross_label,
same_label and nested. Cross-label placeholders are REDACTED; other placeholders use
their label. Numbers are occurrence ordinals. Regex ignores existing emitted placeholders.
Rendering stays in memory until the separate gold-aware publication gate approves it.
The renderer may reject placeholder expansion beyond the schema message bound.

`detect_regex(record, run_id='development')` and `anchor_frontier(record, response,
run_id=..., model_id=...)` return Prediction. Frontier responses are ephemeral strict
JSON proposal arrays with label/quote/left_ctx/right_ctx; exact unique complete-context
anchor wins, then exact unique quote, otherwise count unanchored. No fuzzy repair.
`detect_model` requires an injected backend plus explicit approved pinned ModelPermit;
receipt authenticity, licenses and actual offset/token-limit behavior need later validation.
