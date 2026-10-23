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

## Generator annotation and challenge taxonomy

`m7.data` recipes compose literal segments and typed fictional lexicon segments.
At append time the generator records the cursor before/after each typed segment;
it does not run a detector to produce its own gold. Repeated values receive one
span per occurrence; a NAME-looking substring inside EMAIL receives only the
EMAIL span. Literal punctuation/cue text remains outside the entity. Gold must
have no overlap and each span must fit the unchanged decoded message.

| Taxonomy tag | Observable criterion |
|---|---|
| normal_context | Explicit person, email, phone and account contexts |
| benign_identifiers | Trace/request/job IDs, service names, latency and opaque numbers |
| name_in_email | A person-like email local part; no nested NAME span |
| derived_username | Username derived from a person name, outside NAME scope |
| phone_vs_port | Numeric/phone-like content with port/latency context; no PHONE span |
| repeat_entity | Same value appearing multiple times, each occurrence annotated |
| unicode_offsets | Astral emoji and/or combining sequences before sensitive spans |
| multiline | Decoded CRLF/newlines inside the message |
| escaped_punctuation | Literal quotes/backslashes/punctuation preserved exactly |
| prompt_as_data | Instruction-like message content treated as inert log text |
| implicit_person | A full person name in observable attendee/person narrative context |
| ambiguous_context | Prior adjudication required; cannot seal while pending |

Tags describe content, not seen/unseen provenance. Normal/challenge is declared per
recipe before generation, with plan-pinned proportions per block. All final test
families must be jointly unseen in semantic templates and entities. No tag or
family identifier is a detector input or source of truth for inference.
Ambiguous recipes carry `adjudication=pending` until an external pre-seal decision
sets `resolved` with an immutable reference. A detector miss never justifies
changing the guide or gold after opening results.

Development includes repeated entities, punctuation, multiple classes, Unicode
prefixes, multiline messages, benign negatives and prompt-like text treated as data.
Public fictional fixtures are development scaffolding only. They are not independent
held-out blocks, licensed training evidence, measured results or a sealed corpus.
