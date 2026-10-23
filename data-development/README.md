# Public fictional development fixtures

`public-fictional.json` contains eight original hand-authored fictional examples and
gold offsets. EMAIL domains use reserved `.invalid`; phone numbers use fictional
555 examples. This file is the explicit public raw-source exception. All examples
are public development inputs, never sealed or independent test data. No training,
inference execution or quality result is implied. `dev-008` intentionally lacks the
regex NAME cue and must appear as a publication-suppressed miss when evaluated.

The object has `records` (LogRecord JSON objects) and `gold` (record-ID to span-array
mapping). Parse source data with strict Pydantic JSON validation; JSON arrays become
tuples through the JSON schema path. Do not attach gold to detector input.
These manually authored fixtures share one development provenance component; no
cross-split independence claim is made. Future independent custody owns held-out data.
