# English fictional developer-log annotation v1

This guide defines a narrow experiment, not a real-world privacy guarantee.
Annotate the original decoded message with Python Unicode codepoint half-open spans.
Do not normalize combining sequences, emoji, CRLF, whitespace or escaped JSON first.
Only message is a target; timestamp/level/event remain safe bounded fields.

| Label | Include | Exclude |
|---|---|---|
| NAME | Fictional full person names after observable person/name/user cues, including hyphenated names and middle initials | Service names, capitalized product words, usernames merely derived from names |
| EMAIL | Complete syntactically email-like address, including local part and domain | Separate NAME inside an EMAIL; surrounding punctuation |
| PHONE | Fictional E.164 and national punctuated numbers, with extensions, in observable phone/tel/mobile context | Ports, latency, unrelated numbers |
| ACCOUNT_ID | Complete identifier after account/customer/user_id context | Request/trace identifiers and context-free opaque strings |

Email subsumes names occurring within it. Account values may be letters, digits,
underscores or hyphens; cue text and separators are not part of the span. Supported
phone punctuation includes parentheses, spaces, dots and hyphens; include extension
text as part of the number. A phone-looking port without phone context is benign.
Names are person references observable from text, never inferred from a template ID.

The regex baseline deliberately implements narrower cue grammars documented in
`src/m7/detectors/regex.py`; the guide is not defined by whatever that arm detects.
Adjudicate ambiguous examples before sealing. Never relabel a miss to improve scores.
Gold is generator-defined and requires an independent semantic/provenance audit.

Development includes repeated entities, punctuation, multiple classes, Unicode
prefixes, multiline messages, benign negatives and prompt-like text treated as data.
Public fictional fixtures are development scaffolding only. They are not independent
held-out blocks, licensed training evidence, measured results or a sealed corpus.
