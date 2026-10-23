# Pinned inference source, runtime unverified

M7 includes a lazy local GLiNER adapter and a bounded HTTPS chat-completions transport.
They have not loaded weights, downloaded models, opened network connections, or run
inference. Execution is outside Dirty Mode. Importing modules/building the registry
does not invoke either backend. See `contracts/adapters/README.md` for the callable
seam used by the edition executor, injected-engine contracts and CLI shape.

Local activation requires an externally approved, unexpired run/model/config permit,
licensed immutable artifacts and an exact installed GLiNER/Transformers version.
The closed manifest pins every artifact file, rejects symlinks, Python and pickle
weights, and requires safetensors. Tokenizer identity hashes the sorted compact JSON
mapping of names relative to the backbone subtree to SHA256 for its complete file
inventory. Weight
identity pins the loader's single `model.safetensors`; alternate/sharded GLiNER weight
layouts are currently unsupported and fail closed. The manifest pins configuration
and backbone files too. Prepare `gliner_config.json` with `model_name` equal to the
absolute local backbone directory before approving hashes. No rehoming happens at
load time. All approved files must remain immutable during load/use; filesystem
hash checks cannot eliminate time-of-check/time-of-use races.

The loader uses local paths, `local_files_only=True`, `token=False`, offline flags
and disabled implicit-token/telemetry flags. No environment secrets are read. These
are library-level defenses, not an OS network sandbox. Do not cohost environment-
mutating workers; the pinned library integration still needs runtime verification.
Future setup must approve the package and artifact license/backbone dependencies,
reproduce character mapping and confirm no fallback download or raw logging occurs.
`load_tokenizer=False` deliberately selects the local `config.model_name` backbone
tokenizer instead of an independent tokenizer in the weights directory. Its complete
backbone subtree fingerprint is shared between base/fine and includes every file.

Local preflight obtains original-text word positions, rejects dropped nonwhitespace
characters, checks GLiNER's word limit and counts the processor's full label-prompt
plus word sequence with truncation disabled. It then checks tokenizer and approved
token caps before inference. Unsupported internal API/configuration fails closed.
Returned entities must match original substrings at Python Unicode codepoint offsets;
unknown labels, invalid confidence, bounds and extra entity fields fail the record.
No normalization or text search repairs offsets. Astral emoji/combining marks/CRLF
remain original characters. Explicit byte/UTF16 conversion rejects split character
boundaries; token-span conversion needs original fast-tokenizer offset maps.

Base and fine use one loader/decoder implementation, four ordered descriptions,
overlap-preserving decoding and explicit thresholds. Registry parity checks bind the
originating base weights, common tokenizer/architecture/version/decoder/selection
policy and require a training-receipt commitment for fine. The local loader checks
the actual normalized architecture hash before loading. Receipt authenticity and
the D5 development-only threshold/target lock must still be checked by the host;
mere declarations are not proof of training. Actual limits are permit inputs, not guessed
from a model name. No model is implicitly selected or downloaded.

The frontier transport is a **provisional chat-completions/v1 integration assumption**,
not a certified vendor integration. Provider selection, immutable model name,
supported temperature/max_tokens/finish semantics, tokenizer, framing accounting,
terms and rates need later approval and live validation. An injected provider-aware
counter must count the entire prompt/request and completion. The fixed system prompt
instructs the model to treat logs as data; its SHA256 is bound by config/permit.
Prompt-like inputs remain a robustness limitation, never instructions to this app.

HTTPS has verified TLS, no configured proxies/redirects and bounded reads. It discards
HTTP exception bodies, rejects compressed/non-JSON responses, duplicate JSON keys,
nonfinite constants, model drift, tools/refusals, unsupported envelopes and truncated
completion reasons. It forwards only content in memory to unique exact quote/context
anchoring. Responses, raw values, quote/context hashes and headers are never persisted
by these modules. Caller-injected transports/credentials must obey the same policy;
there is no credential-file reader or default provider endpoint. One socket timeout
bounds a blocking operation, not a guaranteed total wall-clock deadline for a slow
peer; stronger cancellation/deadline handling needs later execution verification.

Attempt policy is preregistered and separately hash-bound in each execution permit.
Every physical attempt reserves its approved worst-case microcurrency via the
existing ReservationLedger API. Only one declared transient transport retry may
run, with its own reservation; malformed model content is terminal. Unknown provider
billing, interrupted calls and unresolved receipts retain their liability. Verified
receipt callbacks can reconcile cash; counting tokens at a published rate is an
estimate and does not produce an actual invoice. Local electrical/amortization cost
remains unknown even with verified zero incremental provider invoice cash.

The controller checks cancellation before reservation, after reservation/preflight
and after blocking calls, catches interrupted operations and preserves unknown cost.
It cannot force-stop an active GPU/socket; no background watcher is installed. A
failed reconciliation or diagnostics sink prevents another retry and preserves the
reservation for later repair. Per-attempt metadata and optional sink contain IDs,
input content hash, enums, span wire and numeric counters only; source text and
completions stay in memory. Reported duration is invocation wall time, including
accounting/preflight, and is not controlled warmed inference latency.

The standalone local CLI uses AdapterRegistry/v2 with policies and explicit
--ledger/--diagnostics selection. Its diagnostics file is created exclusively and
receives flushed/fsynced value-free events. Validation has no DB/model/artifact effects. Later authorized
execution preflights the entire bounded opaque inference corpus before calls.
External inference is available to an injected registry host; no uncertified
provider/tokenizer or credential reader is automatically selected by CLI defaults.
Sealed-edition execution must use D7's durable journal/custody gate; an in-memory
adapter replay guard does not provide cross-process sealed-edition custody.

Read-only integration references consulted 2026-10-23:

- [GLiNER maintainer repository](https://github.com/urchade/GLiNER): public loading and entity APIs.
- [GLiNER model source](https://github.com/urchade/GLiNER/blob/main/gliner/model.py): local-only loading options and entity fields.
- [GLiNER processor source](https://github.com/urchade/GLiNER/blob/main/gliner/data_processing/processor.py): word/prompt token preparation.
- [Transformers tokenizer documentation](https://huggingface.co/docs/transformers/main_classes/tokenizer): truncation and character alignment.

Those moving references guide source construction; they are not an approved package
lock or a compatibility receipt. Later activation must pin and verify exact versions.
Budget/retry/cancellation/parity/CLI source exists; no branch has been exercised.
Later activation must check all reserve/receipt/cancel/replay/error paths and ensure
the host persists diagnostics alongside D7's journal. No full-M7 gate is closed.

The isolated worker/session source is documented in
`contracts/adapters/worker-wire.md`. It adds record-only bounded stdio, parent-brokered
ledgers and explicit native process/file enforcement dependencies. Pure shared profile
P and exact launch L helpers live in `m7.providers.worker_profile`; D4's guard binds P
and the exact per-process verifier binds P plus L. A process or directory alone is
never treated as isolation. `--validate-worker` is definition-only; `--worker` is a
verified launcher's pipe service, not an independent custody approval. Concrete
Windows creation and fixed active-only factory source are in `docs/worker-host.md`.
Real preprovisioned token/control context, actual platform verification, approved
runtime/application receipts and qualified frontier counter/credential remain
activation dependencies; no worker was started.
