# Locked-edition evaluator

Source construction only; this flow has not run. No sealed dataset, approved lock,
training receipt, model/provider execution or scientific result is supplied here.

`m7.experiment.execute_edition` is the future authorized host API. It takes a
`LockedEdition`, standalone inference records, a separate tuple of `CustodyGold`,
an arm-to-`AdapterBinding` mapping, an `EditionJournal`, and a mandatory authority
callback. All four ordered arm pins and the entire sorted record/hash population
are fixed in the lock. `check_channels` rejects missing/duplicate IDs, differing
input hashes, invalid gold bounds or a mismatched inference split before any call.

`channels_from_bundle` verifies D4's `CorpusBundle`, pins its complete manifest,
selects only test provenance, then creates separate message and evaluator gold
channels. It requires at least 20 declared test blocks; it cannot independently
certify semantic ancestry. The authority gate must authenticate the separate audit.
Only `LogRecord` reaches an adapter. Family, slice, gold and the containing bundle
never appear in the adapter signature. An in-process callback is a logical
boundary: the deployment custodian must supply actual process/file separation.

The trusted host supplies `ReceiptAuthority` with a real receipt verifier for the
evaluation authorization, custody release, independent audit and pre-test D5
selection lock. Packet shape and a digest alone are not authentication. Revocation
and expiry are checked before open and every new logical call. There is no default
approval or sample approved packet. Fine/base configuration and actual artifact
lineage must be checked by that host and by D6's adapter bindings.

An `AdapterBinding` pins the arm/model/artifact/configuration and wraps D6's
`(LogRecord) -> Prediction`. Its mandatory preflight checks the full population
against tokenizer/context limits before the journal is opened. A corpus
incompatibility aborts all arms; no per-arm shortening is allowed. The D6 controller
owns at most one transient transport retry and the reservation/attempt accounting.
The evaluator does not retry a malformed response or repeat the logical call.

## Seal, open, resume

Private journal storage contains `edition.json`, `events.jsonl` and an exclusively
created `writer.lock`. The canonical edition seal is immutable. Events are sequenced,
hash chained, flushed and fsynced. A torn or changed event fails closed. These hashes
detect integrity errors; they are not signatures against a hostile filesystem owner.
An abandoned writer lock requires an operator to verify the prior owner has stopped
before removing it. There is no timer/lease-based takeover.

The first event opens the edition once. Each logical arm/record call gets a durable
`begin` before execution and one terminal prediction afterward. On resume, a begin
without a terminal becomes `interrupted_unknown`; it is never reissued. Provider
billing can therefore stay unresolved without invisible duplicate inference.
Cancellation preserves completed/failed cells and leaves never-begun cells pending.
They may resume only under the same lock and current authority. Missing adapters
and budget rejection become explicit terminal outcomes; adding an adapter later
does not replace those outcomes or change this edition. A full rerun needs a newly
authorized edition, with its scientific limitations recorded.

Only when every intended cell has a terminal does the journal close. Replaying a
closed edition recomputes aggregates without any adapter call. Hash pins, current
authorization and the original custody channels are still required. A closed edition
may be incomplete scientifically (for example one wholly unavailable arm).

Every arm shares the exact intended population digest. `attempted_N + unattempted_N`
equals corpus size; `answered_N + error_N` equals attempted count. Budget-rejected,
unavailable, pending, cancelled and interrupted counts remain visible. An arm with
no attempts has null metrics, rather than an invented zero-quality measurement.
For a partially measured arm, every intended record enters unconditional scoring;
missing output is an empty prediction and all sensitive characters remain exposed.
Successful-only metrics are explicitly secondary.

Journal predictions contain IDs, hashes, offsets, labels and bounded enums, never
raw text/gold/prompts/completions/provider exceptions. Keep the journal private:
held-out span tables are not public artifacts. Aggregate output omits even prediction
spans, provenance IDs and rendered held-out messages. Render/gold-mask gate failures
are counted before suppression; gate suppression never repairs detection quality.
`write_aggregate_result` applies a closed numeric/enum field projection, verifies
the identical four-arm counts and writes a new JSON file exclusively. Arbitrary
bundle keys, diagnostics, prediction tables and strings cannot become public JSON.
The source additionally computes total/normal/challenge per-class/micro/macro and
harm intervals from common whole-block draws. It records all 2,000 requested draws,
executed/valid/undefined counts, 95% level, seed and draw digest; fewer than 20 units
or 1,800 valid draws leaves bounds unavailable. Fine-minus-base uses exactly paired
records, gold and blocks. It does not drop failed or unattempted records to improve
quality. Physical attempt summaries (at most the initial call and one transient
retry) remain in the private cell journal. Missing attempt metadata is visible and
cannot satisfy adoption lineage. Preflight-only/no-request outcomes are unattempted;
uncertain interrupted requests retain attempted/unknown status.

`LockedEdition` includes the exact `AdoptionPolicy` and timing-plan hash;
`EvaluationAuthorization` binds both. D5's canonical `PreTestSelectionLock` and
`NumericalTargets` are mapped by `policy_from_selection_lock` without reimplementing
checkpoint selection. Exact target/config/justification/expiry bindings and actual
external receipts are checked before opening gold. Floors apply only to the total
test set. Positive paired macro-F1 lower bound, no increased residual-sensitive
rate, zero structure failures, identical accounting, complete four-arm attempts,
known lineage and complete reconciled training/inference costs are required for a
candidate recommendation. Missing/failed gates preserve benchmark/no-deployment.
Even a candidate recommendation is not independent finished-product acceptance.

`TimingPlan` fixes record order, 0..1,024 length partitions, warmup hash, hardware,
driver, precision, batch one, environment/package locks, concurrency one and three
passes. `run_timing` requires a closed primary journal and separately authenticated
`timing_execution` approval for all repeats/warmup and costs. `TimingWorker` supplies
startup and a fresh per-pass controller sharing the warmed backend, avoiding D6's
replay cache. New timing registries are required for cold initialization; process/OS
cache effects still need qualification. Frontier cold means client initialization,
not provider-model startup. All-attempt/successful-only p50/p95 and throughput, failed
counts, each pass and length slice are separate. Gold safety/scoring/uncertainty
assembly overhead is reported separately from detector+validation+renderer latency.
A started timing run has an exclusive marker and cannot silently rerun after a crash.

The trusted `OperatorHost` is provisioned outside this checkout after authorization.
It supplies inert registry factories, authenticated receipt verification/revocation,
D4 claimed filesystem and actual native-isolation guard, full cost scope and optional
timing factories. No permissive host, fabricated receipt, native sandbox, provider
credential or environment is supplied. Isolated worker bindings may use the optional
`attempt_metadata` callback for value-free physical diagnostics. Source-level
signatures are not OS isolation evidence.

The activation CLI composes D4 `CustodyLifecycle.evaluation_gate(ReceiptAuthority)`,
authenticates current `require_released` before `read_bundle(..., filesystem=...)`, and gives
the registry only detached messages. Edition journals live under the evaluator
filesystem role. Both D4 and D7 journals reject a changed run/population/fingerprint.
The nonconsuming release check also guards whole-corpus preflight; only afterward
does the execution gate consume D4 open and append the D7 opened marker. A crash
between those markers fails closed for explicit custody investigation. A new empty
journal cannot claim an idempotent fresh open of an already-opened edition.
No held-out source is read during the lock-only validation path.

Full cash accounting combines distinct training and inference authorizations in an
authenticated common currency, preserving every failed/retried/cancelled attempt.
Unknown amounts retain conservative reservations. No cross-ledger cap transfer is
permitted. Economic electricity/amortization remain null unless a separately
authenticated allocation supplies them. Zero invoice cash never implies zero total
economic cost. The ledger is canonical; report fields are projections, not a second
financial store.

`write_locked_artifacts` assembles aggregate JSON and HTML in memory, scans all
surfaces against original gold values and escaped/HTML/URL/normalized forms, then
creates a new artifact directory. Failed assembly produces a value-free suppression
card and never improves the private detector results. Public development report
writing also requires a whole-artifact approval callback. Offline replay copies
previously approved HTML bytes with their exact SHA256; it never regenerates a new
gold-free artifact or repeats model calls. The README documents each future mode.

For a shape-only future check: `python scripts/eval.py --validate-lock <lock.json>`.
This does not authenticate, seal, open or execute the edition. Programmatic execution
must be activated only after Dirty Mode closes and actual custody/license/resource
and environment gates have been satisfied.

## Joined isolated campaign

`m7.experiment.campaign.validate_campaign_inputs` consumes D5 `WorkerLaunchBundle`,
`LockedEdition` and `EvaluationAuthorization`, reusing D5 `validate_launch_bundle`
and `campaign_arm_pins`. It does not reselect checkpoints, repair bootstraps, create
profiles or issue authority. D5 `load_launch_bundle` is the strict bounded CLI loader.
Default `--launch-bundle` mode never imports an operator host or reads private data.

Explicit `execute_isolated_campaign` freshly calls D5 `prepare_launch_bundle` with
real receipt/native qualification. D5 `d7_worker_definitions(prepared.bundle)` supplies
the internal worker views and the preparation receipt pins each L. Shared P and full per-arm L come only from D6's
pure helpers. P equals campaign/capability/release/guard. Exact process verification
receives PID/start identity and full L after native launch, before messages. A
prepared campaign does not depend on an already-running worker.

`read_released_channels` verifies D4's separate inference/evaluator export commitments,
authenticated receipts, exact file sets/manifests, read-time byte hashes and population.
The evaluator alone reads gold/block/slice data. No raw CorpusBundle is read in this
path. No custody, training, export or ledger path enters a child message.

`IsolatedRegistry` is lazy. Preflight/predict recheck current release, finance,
profile and launch rights. D6 supplies native launch, exact process attestation,
bounded stdio, sealed population, parent ledger broker and owned cleanup. The bridge
validates/unwraps `AttemptEvent.attempt`. Pre-dispatch guard failures are known
no-request diagnostics; uncertain sent calls retain failure/liability.

The host supplies real parent-only ledgers at disjoint evaluator paths and an
authenticated current training accounting snapshot bound to the original closeout.
Fixed per-arm allocations and bounded closed training liabilities enforce the
combined campaign budget without cap borrowing. Each live ledger remains atomic.
Historical overruns, unknown liability and unallocated economics remain visible.

Sessions close in `finally`. Unverified cleanup creates a private marker requiring
investigation before reuse. No unrelated process is located or terminated. The native
launcher must own/bound its entire process/job tree. Actual OS/token/ACL/job/stdio,
cancellation/crash behavior has not been exercised.

The isolated primary session caches one sealed population. It cannot silently
serve controlled timing. Until a separately approved phase/reset contract preserves
the warm backend and supplies fresh logical controllers, isolated `--run-timing`
is explicitly unavailable. No cold-respawn timing or changed IDs are substituted.
This remaining source seam is not a measured timing failure or complete scientific
product acceptance.
