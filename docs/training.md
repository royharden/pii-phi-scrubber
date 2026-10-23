# Local training executor source

This package is construction source, not a trained model or measured result. No
training, imports of model packages, backend calls, dataset generation or runtime
checks were performed during construction. Runtime remains unverified. Dirty Mode
must close and exact execution/resource/license/custody authority must exist before
any training command is run. The templates are deliberately invalid/unapproved.

`m7.training` is canonical; root `training` only re-exports it for old callers.
`validate_training_plan(plan, permit)` validates v1 or v2 and never executes.
`validate_training_receipt(receipt, plan, permit=None)` checks completed receipt
structure/lineage; even success leaves independent audit and M7-02 acceptance open.
v1 remains validation-only and cannot enter the executor.

Future operator entrypoint (do not run during Dirty Mode):

```text
python scripts/train.py --plan PLAN --authorization PERMIT --validate-only
python scripts/train.py --plan PLAN --authorization PERMIT --execute --staging-root STAGING
```

Validation is the default when neither mode flag is present. An optional staging
root in validation mode checks local artifacts/environment without loading a model
or creating a run/ledger. Validation does not authorize execution.

## Execution interface and staged data

`execute_training(plan, permit, *, root, engine=None, cancel=None, clock=now_utc)`
returns a `TrainingRun/v2`. The production optional backend is `LocalGLiNEREngine`;
a trusted injected `TrainingEngine.run(TrialContext) -> EngineResult` is supported
for later controlled integration checks. Injected engines must obey all caps,
call `context.heartbeat()` each step, and write a checkpoint only to
`context.output_dir / 'checkpoint'`. Injection is not execution evidence.

The dedicated staging root contains only approved local artifacts and executor
outputs. A future operator must enforce OS/process isolation from sealed test
files and make inputs read-only. Python path validation is not an OS sandbox. The
executor has no sealed-bundle/test reader, never searches other directories and
does not provision this isolation. Do not point it at an evaluator checkout.

TrainingPlan/v2 pins exactly eight artifacts: `model` and `tokenizer` directory
trees, and `train`, `dev`, `config`, `environment`, `license_packet`, `custody_audit`
files. Every descriptor has `path` (forward-slash relative to staging), `kind`
(`tree`/`file`) and exact lowercase `sha256`. Absolute/parent paths, symlinks and
Windows junctions are rejected. File hashes cover bytes; tree hashes cover canonical
JSON of sorted `[POSIX-relative-filename, file-sha256]` pairs, without whitespace.
Inputs are checked before launch, each trial, and after backend completion.

`prepare_training_dataset(records, gold, *, split='train'|'dev')` accepts D4's
already-filtered `LogRecord` and `GoldRow` channels. No CorpusBundle or directory
is accepted. It returns `TrainingDataset/v1`: `split` and `records`, each row having
`record` (LogRecord/v1 JSON) and `gold` (`[{start,end,label}]`). Mixed splits,
missing/duplicate/extra gold rows or content-hash mismatches fail. The loader also
validates all bounds, duplicate messages/spans and train/dev message disjointness.
This handoff does not substitute for D4's independent provenance/custody audit.
Gold offsets remain original Python codepoints; no text normalization is permitted.

The environment manifest pins exact Python patch version, package versions
(`gliner`, `torch`, `transformers`, `accelerate`, `safetensors`), resource ID and
device (`cpu` or `cuda:0`). It is inspected against the current interpreter before
execution. It does not prove hardware identity or resource exclusivity. The
training config pins labels, the 1,024-codepoint bound, token cap, decoder and label
description hashes. Base/fine parity and selection locks are a later source seam.

## Caps, failure accounting and lineage

The immutable plan enumerates one to three trials (`trial_id`, `seed`, learning
rate, batch size), at most three epochs, at most 1,000 optimizer steps and a
per-trial duration cap. The local backend uses one device and no accumulation;
its effective step cap also respects the epoch bound. Heartbeats enforce current
permit, cancellation and duration between steps, not during a blocked native
kernel. A future supervisor must terminate a hung kernel conservatively, retaining
its unknown liability. No automatic retry or trial-count reset is implemented.

Exclusive creation of `runs/<edition_id>` prevents a repeated or changed plan from
silently starting more trials for that edition in the same staging area. Preserve
that area across crashes; copying to a fresh staging root does not authorize more
trials. `run-started.json`, trial `started.json`, `receipt.json` and `run.json` are
exclusive-create, fsynced records. Partial/crashed writes fail closed. Recovery
must account the original attempt; deleting a run to restart is prohibited.

Every trial reserves its full worst-case cost with `m7.ledger.ReservationLedger`
before backend loading. Accounting is shared per authorization in
`accounting/<authorization_id>.sqlite`. Failed, OOM, cancelled and interrupted
attempts retain reservations as unresolved liabilities. Unknown is never zero.
Local compute cost is not guessed from duration; a genuine billing receipt is
needed for known cost, and electricity/amortization remain separately unmeasured.
Any actual overrun is recorded honestly and blocks further unaffordable work.

Each actual attempted trial writes TrainingReceipt/v2 with plan/permit, trial/seed,
all artifact hashes, timestamps/duration, ledger attempt, known/unknown cost and
outcome. Completed outcomes add actual optimizer steps/epochs, checkpoint tree
hash and relative path. Failed/OOM/cancelled outcomes have no successful checkpoint
claim. Exception bodies, source values, model outputs and prompt/completion bodies
are never persisted. A completed training receipt is not a selected checkpoint,
pre-test target lock, held-out opening grant or final product acceptance.

## Optional backend integration and deferred checks

The backend loads only a local GLiNER artifact with `local_files_only=True` and no
token lookup; offline and telemetry settings are restored afterward. The pinned
`gliner_config.json` must point `model_name` at the separately pinned local
backbone/tokenizer directory. Dependencies and weights must already be approved
and staged; there is no install/download path. Library stdout/stderr/logging is
discarded while training, and reporting/checkpoint autosaving is disabled.

Exact token boundaries must align; unsupported gold boundaries/span widths fail
rather than snap or disappear. All four labels are explicit in every training
example, including benign examples. Batch word counts/masks and token caps guard
tail truncation on every actual batch. Unicode/CRLF/astral and supported tokenizer
behavior still require later runtime qualification.

The integration follows upstream [model training source](https://github.com/urchade/GLiNER/blob/main/gliner/model.py)
and [trainer source](https://github.com/urchade/GLiNER/blob/main/gliner/training/trainer.py),
inspected 2026-10-23. Upstream's OOM-skipping step is bypassed in favor of the
Transformers step so OOM fails the trial. `model._create_data_collator()` is a
private upstream seam. Exact approved GLiNER/Transformers versions, small-v2.1
artifact compatibility, offline loader/tokenizer behavior, callback/cap semantics,
OOM/cancellation, crash accounting and checkpoint reload have not been exercised.
No package is downloaded or version selected by this source.

## Development selection and target locks

The B source adds `SelectionRule`, `DevSelectionPolicy`, `DevRecord`,
`DevEvaluation`, `select_checkpoint`, `NumericalTargets`, checkpoint/parity helpers,
pre-test lock helpers and stopped-worker recovery. It has not run. No development
measurements, trained checkpoint, approved targets, selection lock or recovery
receipt is supplied. The numerical target template holds the promoted plan's
provisional engineering values, not approved or measured privacy guarantees.

A trusted future host constructs typed models with `model_validate_json` for JSON
input (strict tuple fields are not loose Python lists). The host supplies
`verify_receipt(kind, sha256) -> bool`, with issuer/content/revocation checks in its
real authority store. There is no permissive default, arbitrary plugin loader or
credential setup. Successful structural validation is never authentication.

1. Freeze `SelectionRule` before development observation: the finite shared
   threshold grid (at most 21), 2,000 paired block draws, seed, >=20 blocks,
   >=1,800 valid draws and recall/cost tie-break policy. `rule.sha256` is the
   reusable `selection_rule_sha256` pinned by D4's corpus freeze; it excludes
   later data hashes. `DevSelectionPolicy` separately binds edition, promoted
   experiment-plan hash, exact training-plan/dev-file hashes and registration time.
   Experiment-plan hash is distinct from D4's generator CorpusPlan hash.
2. Train only within the original capped plan. `export_checkpoint(receipt, plan,
   permit, staging_root=..., destination=..., base_config=..., verify_receipt=...)`
   creates a fresh D6-compatible model/backbone artifact directory. Safetensors only;
   no executable/pickle files. It copies no data/gold. A local backbone path is
   rehomed only in the new export before new hashes are pinned. The original
   checkpoint and receipt stay unchanged. Sidecar `<destination>.export.json`
   sits outside the closed D6 artifact root. Export failure leaves its new partial
   directory for investigation; it never overwrites/retries that directory.
3. `verify_checkpoint_export` rehashes local bytes and lineage. `verify_parity`
   reuses D6's `validate_pair`, `verify_artifacts` and `validate_architecture`, then
   joins the training receipt/export. No second adapter validator is implemented.
   Both arms share base weights lineage, tokenizer/backbone, architecture, pinned
   libraries, label descriptions, offset/decoder mapping and threshold-selection
   rule. Independently dev-selected scalar thresholds may differ. Configuration
   digests also freeze device/limits and local artifacts, not only a model name.
4. A future authorized host runs each completed checkpoint and base across the
   SAME complete preregistered threshold grid on dev only, storing authenticated
   `DevEvaluation/v1` objects with exact configs/predictions. Selection itself
   runs no detector or model. Supply `DevRecord(record,gold,block_id,slice_name)`
   from D4's prefiltered dev channels. `select_checkpoint(rows, evaluations,
   policy=..., training_plan=..., training_permit=..., trial_receipts=...,
   checkpoint_exports=..., training_run=..., training_root=..., verify_receipt=...)`
   verifies the staged dev-file bytes/records/gold, authenticated population/block
   identity, every actual evaluation, original trial outcomes and stopped/finished
   run closeout. Missing/corrupt/interrupted slots cannot become unattempted work
   or disappear. New unplanned trials, duplicate grid cells, changed configs within
   a checkpoint, altered thresholds, missing grids, mixed splits and unequal
   record populations fail. Predictions do not expose source values.
5. Per-class exact P/R/F1, support, normal/challenge/total and failure-adjusted
   metrics remain visible. Entirely unrun grid cells have null metrics; incomplete
   cells retain the intended denominator and cannot win selection. Highest macro
   exact F1 is compared by paired 95% block uncertainty; statistically
   indistinguishable candidates advance to the same macro-recall comparison and
   then the preregistered lower cost bound. Unknown cost uses its reserved upper
   bound, visibly labelled; it is never treated as measured zero. Exact remaining
   ties use trial/threshold/ID order. Missing/insufficient uncertainty fails closed,
   rather than implying equality or adding trials. Thresholds are chosen separately
   for base and each trial; the selected fine trial comes from those finalists.
   Selected class intervals include draw counts/digest and undefined reasons.
   This development comparison is detection-only; it does not certify rendering.
6. `justify_targets(selection, targets, rationale_receipt_sha256=...)` proposes a
   value-free per-class target rationale against dev estimates/recall intervals
   and explicit miss/overredaction consequences. It never approves or silently
   lowers a target. Zero structure failures and complete intended accounting remain
   immutable invariants. INT must explicitly approve the exact `lock_binding(...)`
   digest through `PreTestLockApproval`; targets may be failed or revised on dev
   only, with the approved rationale retained. A held-out target failure later
   means retain the benchmark and recommend no deployment, never rewrite targets.

TrainingConfig/v1 now explicitly includes ordered `label_descriptions` and verifies
`label_descriptions_sha256 = digest(label_descriptions)`. Its `decoder_sha256` is
`digest(base_config.decoder.model_dump(mode='json', exclude={'threshold'}))`;
threshold-rule digest remains included. Training maps NAME/EMAIL/PHONE/ACCOUNT_ID
to those same descriptions, loads the pinned backbone with `load_tokenizer=False`
as D6 does, and counts the same full prompt/word representation without truncation.

### Exact D4/D7 lock contract

`PreTestSelectionLock/v1` fields are `schema_version`, `edition_id`,
`experiment_plan_sha256`, `training_plan_sha256`, `corpus_manifest_sha256`,
`selection_rule_sha256`, `dev_selection_receipt_sha256`,
`selected_training_receipt_sha256`, `selected_checkpoint_sha256`,
`base_configuration_sha256`, `finetuned_configuration_sha256`,
`parity_receipt_sha256`, `target_justification_sha256`, `targets_sha256`,
`approval_sha256`, `locked_at`, `expires_at`. All are strict, frozen and extras are
forbidden. `lock.sha256` is SHA256 of canonical JSON `model_dump(mode='json')`,
with sorted keys, separators `(',', ':')`, `ensure_ascii=True`, `allow_nan=False`.
It has no embedded self-digest. This matches D4/D7 canonical commitments.

`create_pre_test_lock` authenticates actual policy/development/training/closeout,
checkpoint export, parity, numerical targets, target rationale/justification and
exact approval. It enforces registration -> observations -> selection ->
justification -> approval -> lock chronology, expiry, and authoritative
`heldout_unopened` verification against the candidate-binding digest. This callback
must check current custody state; a caller-provided `True` is not evidence.

`verify_pre_test_lock` rechecks bindings/current revocation and the admitted
`pre_test_selection_lock` digest. A fresh candidate is not automatically admitted
by creating it. `selection_lock_reference(lock)` returns D4's existing
SelectionLockReference/v1 projection: edition/corpus/selection-rule/locked-at plus
`receipt_sha256=lock.sha256`. D4 authenticates both that original digest and
`pre_test_lock_binding=digest(projection)`. It does not recalculate selection.

`export_pre_test_lock(lock, destination_directory, ..., verify_receipt=...)` writes
one exclusive `<edition_id>.lock.json` in the existing trusted lock store, after
both lock and projection authenticate. Envelope contains the lock and canonical
reference/digests; no development predictions or source text. D7 may load exact
`NumericalTargets` separately from the trusted store, verify `lock.targets_sha256`,
and bind its adoption policy. Its authority still independently requires custody
release and evaluation authorization. Creating/exporting a lock opens no held-out
files, starts no evaluation and grants no model/provider authority.

Receipt-kind names shared with D7 are `pre_test_selection_lock`,
`pre_test_lock_binding`, `parity_receipt`, `numerical_targets`,
`target_justification`, `training_receipt`, `pre_test_lock_approval`. Additional
producer checks use `dev_selection_policy`, `development_population`,
`dev_evaluation`, `checkpoint_export`, `training_run_closeout`, `target_rationale`,
`base_adapter_configuration`, `finetuned_adapter_configuration`, and at creation
only `heldout_unopened`. The host authenticates exact contents and current
revocation; none is satisfied by digest shape alone.

### Cancellation and interrupted-attempt recovery

`recover_training_run(plan, permit, root=..., authorization=RecoveryAuthorization,
verify_receipt=...)` is future accounting source only. It requires a current,
authenticated `training_recovery_authorization` and `training_worker_stopped`
receipt, tied to exact original plan/permit/run-started digest. An expired training
permit may be accounted at its original start time; it cannot authorize new work.

Recovery reads the existing ledger read-only first, then reconciles only missing
accounting from valid immutable receipts. Original failed/OOM/cancelled/partial
receipts and run files are preserved. Known late billing is never replaced by an
older unknown value. A reserved attempt without a usable terminal receipt becomes
`interrupted_no_success_receipt` or `original_receipt_unusable`, retains full
unknown liability and never promotes a stray checkpoint. Untouched slots are
reported separately. No new reservation, attempt restart, lock deletion, worker
kill or successful receipt reconstruction occurs. The original same-edition run
slot remains consumed. Continuing untouched work, if needed later, requires an
explicit authorized continuation design; this API never silently retries.

Recovery writes a new fsynced `recovery/<authorization_id>/receipt.json` and can
repair accounting interrupted between receipt persistence and ledger reconciliation.
Unreadable headers or inconsistent reservation/authority fail closed, preserving
files. SQLite corruption and half-written authority-binding records require
operator investigation. OS custody isolation, issuer authentication, file/ledger
races, model/tokenizer compatibility, real metrics/uncertainty, interrupted-kernel
handling, export reload and all runtime behavior remain unverified.

`configuration_from_export(export, base, model_id=..., threshold=...)` constructs
D6's canonical fine configuration/FilePins for a grid cell without loading a model.
It retains the base's shared policy/decoder metadata and validates the pair. Local
training artifacts now enforce the same safetensors/no-executable-or-pickle file
boundary as D6, and the final model save explicitly requests safetensors with hub
publication disabled. CUDA training requires exactly one visible authorized GPU;
CPU remains separate. These checks are source only and have not been exercised.

## Selected-artifact campaign handoff

The C source closes the producer handoff to D7; it has not exported a real model,
prepared an actual campaign or enforced OS permissions. Canonical models are
`m7.training.campaign_models.SelectedArtifactManifest`, `CampaignSpec`,
`CampaignResources`, `CampaignBudget`, `CampaignAllocation` and
`CampaignActivationReceipt`. Source functions/protocol live in `m7.training.campaign`.
Both JSON templates deliberately contain missing hashes/configs/permissions and
are invalid for activation. Their zero numbers grant no budget or cost claim.

`build_selected_artifacts(...)` consumes actual original training plan/permit,
completed receipt, training run/recovery closeout, selected dev receipt, checkpoint
export/parity, lock/targets/justification/approval, exact base/fine D6 configs and
private training-root parameter. It authenticates and joins these before returning
SelectedArtifactManifest/v1. It never selects again, downloads, converts weights,
substitutes a checkpoint or edits original outcomes. Train/dev/config/environment/
model/tokenizer/license/custody hashes and exact seed/steps/epochs are preserved.
Original checkpoint TREE hash is separate from exported inference TREE hash and
D6's SINGLE `model.safetensors` FILE hash. These are not interchangeable pins.

Worker artifact roots must be separate, closed base/fine inference-only bundles,
disjoint from the training root. Only approved model config/safetensors and
recognized tokenizer/backbone asset names are allowed; no datasets, raw/gold
channels, training receipts, arbitrary JSON/scripts, executable Python or pickle
weights enter the manifest. Missing/incompatible layouts fail without repair.
D4 `checked_path` rejects lexical traversal, symlink/junction/reparse/hardlink
aliases before D6's canonical `verify_artifacts` rehashes the closed file manifest.
Those path checks are not an OS sandbox and cannot defeat hostile TOCTOU changes;
future artifacts must be immutable under the actual native enforcement profile.
Rehoming an artifact after dev selection changes its configuration pin and is
rejected; export/rehome must happen before the final dev evaluation and lock.

`CampaignSpec/v1` embeds only this selected artifact manifest, exact pre-test lock
and numerical targets, approved frontier config, regex artifact/config pins, three
D6 adapter permits/AttemptPolicies, resource/terms/custody/evaluation/isolation
receipt references, intended population commitment/count, D7 adoption-policy and
timing-plan hashes, and combined budget. It includes NO training-root, custody
root, dataset directory, gold, provenance, raw log or token/key fields. Local paths
inside base/fine configs address inference assets only. Frontier endpoints require
approved credential-free HTTPS without URL credentials, query or fragment.
The evaluator keeps the full campaign; do not send it to the worker. Give a worker
only D6's approved config/permit/policy and bounded opaque records.

Campaign resources distinguish the original training license packet from separate
local-inference license, local hardware, provider license/resource/terms, cash,
independent audit, custody release and evaluation authorization references.
Training permission alone does not imply inference/provider/hardware permission.
Exact run/model/config/policy, scope, cap and expiry must agree with each adapter
permit. No real account/credential lookup or provider call is implemented here.

Combined cash accounting carries the authenticated original training closeout,
known training cash and unresolved training liabilities. Three separately named
inference allocations plus prior known/unknown training liabilities must fit the
approved campaign cap. Unknown training cost stays charged, not silently zeroed.
Each allocation funds its declared call ceiling including allowed retries, and
must cover at least the primary pass plus three timing passes. Actual approved
warmup/other timing calls also belong in the ceiling; D7 must bind the exact timing
plan and ensure they fit. This is reservation/authority source, not measured total
economic cost. D7 adoption still requires combined actual training+inference
accounting, and honest electricity/amortization/unknown-cost limitations.

### Producer and operator entrypoints

```text
CampaignProducer.validate(spec, *, check_files=False) -> dict
CampaignProducer.prepare(spec, *, host=CampaignHost(...)) -> PreparedCampaign
SelectedCampaignProducer()  # concrete producer, construction has no effects
validate_campaign(spec, *, check_files=False) -> dict
prepare_campaign(spec, *, host=...) -> PreparedCampaign
campaign_arm_pins(spec) -> tuple[D7 ArmPin, ...]
export_prepared_campaign(prepared, existing_directory, *, host=...) -> dict
```

Default validation reparses strict schemas, checks commitments, same-base/fine
parity declarations, expiry, terms/resources and quoted budget. It performs no
artifact reads, authentication, model loading, DB operation or writes. Its result
always says activation_allowed=false. `check_files=True` additionally performs
read-only path/layout/hash checks, never model imports/inference.

CampaignHost requires the actual trusted receipt verifier and D4 IsolationGuard.
Preparation authenticates current campaign/selected-artifact/training-closeout/
checkpoint/lock/targets/parity/approval, licensing/hardware/provider/cash,
custody/evaluation/audit/adoption/timing, adapter permit/policy/rate references.
It binds the exact filesystem-policy/worker-policy/capability digests and calls
IsolationGuard.require_current, including the actual platform verifier. There is
no implementation that claims subprocesses or directory names enforce isolation.
Absent/revoked/mismatched enforcement fails closed. Preparation returns a fresh
value-free receipt with runtime_executed=false and does not spawn a worker, open
an edition, invoke a model or run evaluation. It is a point-in-time handoff, not a
substitute for D7/D6 rechecking guard/authority before each future execution phase.

The ArmPin helper uses D7's canonical type and D6 config_digest, in the required
regex/frontier/base/finetuned order. D7 can consume the one spec, compare its exact
run/corpus/population/lock/adoption/timing/resource commitments, build record-only
worker sessions and retain gold in the evaluator. It must not bypass its custody
open/resume journal, original ReceiptAuthority or actual isolation verification.

The exporter rechecks current authority, refuses to write inside worker artifact
roots, and creates only `<campaign_id>.campaign.json` exclusively in an existing
operator handoff directory. It never overwrites a prior campaign or changes a
trial receipt/unknown liability. It includes exact config pins and activation
receipt; it grants no source publication or model redistribution permission.

Future CLI (do not run during Dirty Mode):

```text
python scripts/train.py campaign --spec CAMPAIGN --validate-only
python scripts/train.py campaign --spec CAMPAIGN --validate-only --check-files
python scripts/train.py campaign --spec CAMPAIGN --activate --out EXISTING_HANDOFF_DIR
```

The ordinary training CLI remains compatible. Campaign activation from a bare
console returns unavailable/authenticated_campaign_host_required, with no writes.
A reviewed future operator host composes `train.main(argv, campaign_host=host)` or
calls the producer directly; there is no arbitrary plugin import, credential
setup, permissive local JSON trust store or fabricated native-enforcement stub.
The explicit activation source is complete as a host-injected handoff and fails
visibly when real authorization/isolation services have not been supplied.
Missing license/hardware/provider/custody/evaluation/cost/isolation permissions
remain named prerequisites, not empty successful stages.

Interrupted/failed/cancelled training uses the existing authenticated accounting
recovery API. A campaign cannot use an incomplete checkpoint or relabel missing
receipts successful. Source still does not silently restart consumed trial slots.
All native enforcement, model/checkpoint loading, provider permission, campaign
activation, worker/file separation, cost concurrency and operator journey behavior
remain runtime-unverified and require later authorized validation. No real
campaign, terms approval, isolation verdict or independent acceptance was created.

Current source reconciliation note: D4's edition capability binds one shared
worker-policy/profile digest. D6's per-arm launch policy additionally pins its
bootstrap/executable/entrypoint, and distinct arms naturally have distinct launch
hashes. CampaignSpec retains the shared profile commitment; the actual D6/D7
launcher must attest each exact allowed launch as a member of that approved
profile. Different launch hashes must never be asserted equal. This seam was
reported to INT for the D6/D7 owners; until those source owners reconcile it,
activation must remain unavailable rather than weakening the isolation check.
