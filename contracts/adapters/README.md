# Adapter seam v1

Canonical source: `m7.detectors.registry.build_registry(configs, permits, *, run_id,
transports=None, counters=None, loaders=None, allow_execution=False, include_regex=True,
policies=None, ledgers=None, cancelled=lambda:False, receipt_resolvers=None,
diagnostic_sink=None)`.
Returns a mapping with `(LogRecord) -> Prediction` values. There is no provider I/O or
artifact read when constructing the registry. Unconfigured arms are absent, never
mocked. `allow_execution` defaults false; caller authority and a current approved
receipt are both needed later. The external approval/signature check is an operator
responsibility, not established by an `approved` boolean in a JSON file.

`configs` maps `base`/`finetuned` to `LocalModelConfig` and `frontier` to
`FrontierConfig`; `permits` has exactly the same keys and `ExecutionPermit` values.
All are frozen strict boundary models. `config_digest` is canonical compact sorted
JSON SHA256. `permit.check` binds config/run/model/scope, issued time and exclusive
expiry. Artifact/tokenizer/license/authorization digests are artifact commitments,
never hashes of entity values. No approved permit or fabricated output is shipped.

`loaders[arm](LocalModelConfig) -> LocalBackend`, where
`preflight(message) -> full_input_token_count` and `predict(LogRecord) -> TokenSpan`.
Injected loaders obey the local manifest gate too. `transports['frontier']` accepts
`(FrontierConfig, request_bytes) -> TransportResponse`; it must not persist/log
requests, completions, headers or exception bodies. `counters['frontier']` supplies
its pinned `sha256`, `request_tokens(payload)` including all prompt/framing tokens,
and `completion_tokens(content)`; unknown counters fail closed, never estimate.

Each configured adapter exposes `last_attempt: AttemptMetadata | None`, an allowlist
of attempt ID, arm/model, status/error, invocation wall time and optional usage
counts. It contains no record text, prompt/completion, quote/context or value hash.
It is sequential-worker state, not a durable audit log. `last_attempts` exposes all
physical/reservation-rejected attempts for the latest logical call. `diagnostic_sink`
may persist the fixed `AdapterAttempt/v1` allowlist (run/arm/model/record/input hash
and AttemptDiagnostic fields); no source values are present. Prediction.usage_ref
points to the latest reserved physical attempt; a rejected retry cannot erase a prior
attempt's unresolved liability. Omitted sink means host consumes last_attempts;
the ledger alone retains attempt totals/state, not a complete model-usage report.

Predictions and failures keep the common `m7.contracts` vocabulary unchanged.
Overlength/token-limit failures become `invalid_output/truncated`; malformed,
ambiguous and partial anchoring retain the original strict `anchor_frontier` policy.
Adapters never receive gold, provenance, family metadata or renderer callbacks.
Corpus-wide preflight must precede comparison; per-record rejection still remains
visible in the intended accounting population.

JSON CLI envelope: `AdapterRegistry/v2` with exactly `schema_version`, `run_id`,
`configs`, `permits`, `policies`; entries use `m7.providers.contracts` model fields.
`scripts/infer.py --spec <path> --validate-only` performs no model execution, DB or
artifact access. Future `--execute-local --records <inference-jsonl> --ledger <path>
--diagnostics <new-jsonl-path>`
opens its explicitly chosen local ledger and emits only predictions/value-free
budget-rejection cards. The CLI reads a bounded corpus first and preflights every
adapter before any inference; only opaque `split_id=inference` records are accepted.
External transport requires programmatic injection and is not exposed by that CLI yet.
No validation/inference command has been run in Dirty Mode.

Each registry entry also has `preflight(tuple[LogRecord,...]) -> None`,
`model_id`, `arm`, `configuration_sha256` and `artifact_sha256`.
`bind_registry(registry, pins, *, run_id)` accepts only D7's sequence of `ArmPin`
commitments and the edition run ID, and returns D7 `AdapterBinding` objects after
exact run/model/identity/hash comparison before inference.
It never receives an edition/custody/gold bundle. Regex artifact hash is the SHA256
of `detectors/regex.py` bytes, read at explicit binding time; its configuration hash
is SHA256 of `{"model_id":"context-regex-v1"}`. Local artifact hash pins weights;
frontier artifact hash is the externally approved `model_revision_sha256` receipt
commitment, not a claim that provider weights were obtained. Configuration hashes
use `config_digest`. Caller permits/external approval must authenticate these pins.
Whole-corpus preflight may lazily load authorized local artifacts/tokenize, but
never performs local inference or invokes the frontier transport.

Activation requires same-key `policies` and `ledgers` mappings. Each AttemptPolicy
binds authorization ID/cap, approved worst-case microcurrency per physical attempt,
rate-receipt hash, maximum logical records and 0-or-1 transient retries. The permit's
attempt_policy_sha256 must equal canonical config_digest(policy). All retries need a
new atomic reservation under the same authorized cap. The host initializes the ledger
after authenticating the resource receipt; build_registry never opens a database.
Receipt resolvers receive only attempt ID and span/usage result, and return an
externally verified CashReceipt or None. Usage/rate estimates are not actual bills.
Frontier activation also requires approved integer input/output microcurrency rates
per million tokens plus fixed-request allowance. The per-attempt reservation must
cover the integer-ceiling cost at both configured token caps; unknown rates reject
activation. Rate authenticity and unmodeled charges still require permit approval.

BudgetExceeded escapes ONLY for a rejected initial reserve before physical operation.
After any started/uncertain physical call, retry denial returns a failed Prediction.
Malformed envelopes/proposals, partial/ambiguous anchoring, truncation, local model
errors and bookkeeping failures never trigger content repair. A transient frontier
transport failure alone can use the single preregistered retry. Unknown cost retains
the full reservation, including cancellation and provider timeouts; only verified
cash receipts release it. Cancellation after reserve but before operation may record
a `no-call-<attempt>` local zero-call fact only if the approved policy explicitly
sets no_call_zero_cash_approved=true; otherwise liability stays unknown, including
preflight/compute charges. The zero-call fact is distinct from a provider bill.

Controllers retain terminal predictions/diagnostics in memory to avoid accidental
same-worker replay. D7's durable begin/terminal journal is REQUIRED for sealed-edition
restart/resume and its abandoned begins must never reexecute. The standalone local
CLI is a bounded operator tool, not a custody/sealed-restart executor. Cooperative
cancellation does not forcibly interrupt a blocking HTTP or GPU call.
CLI diagnostics uses an explicitly chosen new file with flush/fsync for each
value-free event. Existing files are never overwritten; registry creation itself
does not open a sink. Programmatic hosts supply their own sink or harvest last_attempts.

LocalModelConfig now declares base_weights_sha256, architecture_sha256 and optional
training_receipt_sha256. Finetuned registry entries require a matching base config.
validate_pair checks originating base weights, identical backbone/tokenizer/architecture,
versions/limits/device and decoder/threshold-selection policy. Per-arm dev-selected
thresholds may differ. Actual gliner_config normalization replaces only model_name
with `local-backbone`, hashes all other fields, and must match architecture_sha256.
These declarations are not authenticated training/selection receipts; D5/D7 authority
must verify their exact lineage/lock digests before opening held-out evaluation.

For process/file-separated held-out inference, use the explicit WorkerSessionProtocol
and native enforcement gate in [worker-wire.md](worker-wire.md). Shared profile and
exact per-arm launch hashing/membership come only from `m7.providers.worker_profile`;
the in-process registry itself does not certify worker isolation or custody.

