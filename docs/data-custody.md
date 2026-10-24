# Synthetic corpus and custody

This source implements future corpus construction. No generated train/dev bundle,
sealed test record, independent audit, or measured result was produced during the
Dirty Mode source pass. The checked-in `data-development/public-fictional.json`
remains the clearly labelled public development exception.

`m7.data` owns inventory, generation and mechanical split checks. Existing
`m7.contracts.LogRecord` and codepoint semantics are unchanged. A `CorpusBundle`
contains separate `records`, `gold`, `provenance`, `assignments`, `audit` and
`manifest` fields. The entire bundle and its directory are custodian/evaluator
material; never give either to a detector worker. `inference_records(bundle)`
returns only `LogRecord` values with opaque IDs and `split_id="inference"`.
No family name, difficulty, ancestry, label or gold span travels in that channel.
The evaluator retains its own ID-to-gold/provenance join for scoring/bootstrap.

## Authoring and independence

An inventory explicitly declares semantic ancestors of kinds `lexicon`,
`identifier_grammar`, `scenario`, `template`, and optional `derivation` with parent
references. Every family must resolve the first four kinds. Actual lexicon use is
added to closure even if a family omits it from its own list. Cycles, dangling
references and duplicate IDs fail. Families are unioned through the full parent
closure and through shared normalized sensitive lexicon values. Renaming a node,
changing a seed, paraphrasing a scenario or repartitioning values does not establish
independence. Semantic source/config descriptors have commitments; the generator
implementation has a separate aggregate source-file commitment.

The library cannot discover an undeclared conceptual ancestor. A separate
nonauthoring auditor must inspect original grammar/scenario/value-pool derivations,
alias relationships, hashes and a stratified annotation sample. Generic Python/RNG
utilities alone are not semantic ancestors; a shared account format generator or
log scenario skeleton is. Those distinctions must be preregistered and audited.
`custody_accepted` remains false and independent/label verdicts remain pending in
all library-produced manifests. Author self-inspection is not that audit.

`allocate_blocks` deterministically orders whole components using the split seed.
It requires exactly the plan's requested component count; it never silently drops
extra families or divides a component. Public development components supply the
train/dev pool; independently authored private components supply the test pool.
The split seed orders each pool, never moves exposed development families into
test or private test grammars into training. The plan defaults are 40/20/30 train/dev/test
blocks and 40 records per block; at least 20 independent test components and 200
test entities per class remain hard lower limits. Each generated block must contain
all four labels, normal/challenge records and at least 20% fully benign records.
Counts and seeds are explicit plan inputs rather than hardcoded fixture expansion.
The supported implementation bound is 10,000 records per edition.

`development_inventory()` is a small original recipe inventory with five named
families sharing scenario/template/identifier and lexicon ancestors. They form
ONE development component. It cannot satisfy a held-out requirement. No private
test grammar ships with these development sources. A separately appointed
custodian must author private test families without development-error or training
prompt access; an additional nonauthoring reviewer audits that work.

Near-duplicate audit replaces gold intervals in a private temporary string,
normalizes only that audit view and compares character-trigram Jaccard similarity
at a frozen 0.9 threshold. Cross-split matches block construction for prior
adjudication/ancestry repair; they are not removed from denominators. Only pair IDs
leave this function. No normalized source/value or low-entropy value hash is
published. This check supplements ancestry; it cannot establish independence.

## Producer/consumer API

| Call | Intended caller and result |
|---|---|
| `generate_development(inventory, plan, assignments=None)` | Developer; train/development-only `CorpusBundle`; rejects private inventory/test assignments |
| `allocate_blocks(inventory, plan)` | Custodian; deterministic whole-component assignments; insufficient inventory fails |
| `audit_inventory(inventory, assignments, plan, development_only=False)` | Custodian/auditor; mechanical `SplitAudit`, never independent verdict |
| `seal_corpus(inventory, plan, assignments, authorization)` | Future custodian; checks edition/inventory/plan pins, expiry and role separation before generation |
| `verify_bundle(bundle)` | Evaluator; channel commitments, IDs, spans, counts, provenance joins and audit consistency |
| `inference_records(bundle, split='test')` | Custodian/evaluator selects intended split; detector-safe record tuple only |
| `storage.write_bundle(bundle, destination, private_root=..., filesystem=...)` | Custodian; claimed filesystem required for sealed bundles; new directory, manifest completion marker last |
| `storage.read_bundle(directory, filesystem=...)` | Custodian/evaluator only; sealed bundles require claimed filesystem; bounded strict reads and commitments |

The manifest pins canonical SHA256 commitments of records, gold, provenance,
assignments, plan, inventory and mechanical audit, plus raw guide/generator-source
pins. Canonical JSON uses sorted keys, ASCII escaping, compact separators and no
NaN. These are reproducibility/integrity commitments, not signatures or proof of
custody authority. Inference records contain the original decoded-message hash;
channels are ordered and joined by opaque record ID. Gold offsets are calculated
at append time from original Python text, never re-found with regex/string search.

## Future commands, not executed

`python tools/data/build.py --plan <plan.json> --out <new-development-directory>`
uses the public development inventory. An explicit original development inventory
can be provided with `--inventory`. Pass `--assignments <array.json>` to designate whole train/dev components;
any test assignment is rejected. Without assignments all components are development.
The caller pins current guide/generator hashes
and selection-rule hash in `CorpusPlan/v1`; no populated approval template or fake
corpus receipt is supplied. The tool rejects changed source/guide pins.

The future host entrypoint `tools/data/seal.main(verify_receipt=trusted_verifier, filesystem=claimed_filesystem)`
accepts these CLI arguments (the standalone command refuses mutation without a
trusted verifier): `--inventory <private.json> --plan <plan.json>
--authorization <authorization.json> --approval-receipt <approved-original>
--audit-receipt <independent-original> --custodian-id <id>
--custody-store <preprovisioned-store> --private-root <existing-private-root>
--out <new-private-edition-directory>`
checks actual receipt bytes against their pinned hashes. Custodian and auditor must
differ from implementation authors; auditor also differs from all family authors.
Test-family authors must match the custodian. This does not authenticate the
receipt issuer: operating authorization and OS access controls must be supplied by
the future custodian. A matching frozen lifecycle must exist before any held-out
generation. `--resume-persisted` can seal an already-written complete bundle without
regeneration; it cannot repair partial channels or overwrite an edition. Never run
this entrypoint under Dirty Mode.

`python scripts/audit_split.py --manifest <manifest.json>
--bundle-dir <private-bundle> --inventory <private-inventory.json> --plan <plan.json>`
recomputes inventory ancestry audit against pinned bundle channels. It emits only
value-free totals/verdict-pending fields. Exit zero means mechanical minimum-count
checks, not G2 acceptance. Development's insufficient test count remains visible.
The legacy `SplitManifest/v1` CLI remains available for old declared-ancestor
checks; it does not verify a full corpus, guide or labeling sample.

Storage never overwrites an edition. A partial failure leaves private evidence;
manifest written last distinguishes complete channels. Caller provisions private
filesystem permissions and process isolation; path checks are not a sandbox and
plain corpus files are not encryption. Train/dev labels can be explicitly exported
to training; sealed test gold must remain evaluator-private. A seal is not a release
and never authorizes a model, provider, training job or held-out experiment by itself.

## Guarded lifecycle

`CustodyLifecycle(root, verify_receipt=trusted_verifier, filesystem=claimed_filesystem,
isolation_guard=actual_guard)` uses an existing private
root and an append-only, hash-chained numbered event store. All mutations use an
exclusive-created writer lock, and fsync event bytes. No root, event, lock or corpus
was created by executing these sources during construction. A crash/partial event
or retained writer lock fails closed for explicit operator investigation; do not
delete/reset the store to reopen an edition. Hash chains do not defeat hostile
rewrites by an OS user with custody rights; protect and back up the root externally.

1. `freeze_binding(inventory, plan, assignments, custodian_id=...)` computes a pure
   value-free approval payload. It pins inventory/guide/generator/plan, assignments,
   selection rule, split/sampling seeds, proportions, family author identities and
   semantic test source commitments. Test authors must be the custodian. A
   `CustodyActionAuthorization` binds the exact payload hash, edition, action and
   validity interval; its authenticated original is required by `freeze(...)`.
2. `validate_seal_inputs(...)` requires that exact frozen inventory before private
   generation. `seal(bundle, authorization=...)` verifies frozen commitments,
   authorization expiry/roles and the independent-audit receipt, then commits the
   manifest and sorted test population hash. An exact already-sealed bundle can be
   recognized without another seal event; any changed bundle fails.
3. `release(edition_id, selection_lock=..., authorization=...)` requires the full
   authenticated D5 pre-test-selection lock and a separately authenticated binding
   projection (`SelectionLockReference`). The projection binds the original D5
   receipt digest to this edition, corpus manifest, frozen selection rule and lock
   time. The trusted host verifies D5's actual selection/parity/target-lock schema;
   D4 does not duplicate D5's selection algorithm or accept a shaped JSON as proof.
   `ReleaseAuthorization/v2` additionally binds run, experiment-plan hash, exact
   population, audit, actual isolation capability and expiry. Only one release is
   allowed per edition. `CustodyRelease/v2` pins filesystem/worker-policy digests.
4. `authorize_open(edition, resume)` binds D7's `LockedEdition` fingerprint, run,
   population, plan, release, audit, selection lock and expiry. First open is durable
   exactly once. Resume is allowed only with the same fingerprint and an already
   opened D7 journal. Changed configuration/population or a fresh-journal first-open
   request is rejected. A crash between the two open markers requires explicit
   custody investigation; no silent replay resets either journal.
5. `revoke(...)` uses an authenticated action/edition/reason-bound authorization;
   no further release, opening, resumption or channel export is allowed. This cannot
   recall files already delivered to a worker. Stop/restrict worker access through
   the future operating host. `supersede(old,new,authorization=...)` retires the old
   edition and reserves a never-used successor ID. Its later freeze must use fresh
   private test semantic sources; merely changing seeds/labels/IDs cannot reset the
   holdout. Histories and prior failures remain intact. The successor freeze also
   requires `predecessor_inventory=` (the custodian already holds it): every labelled
   pool value of the successor's custodian-private test families is compared, in
   memory only, with the predecessor's, and any overlap refuses the freeze with
   `replacement_entity_value_reuse`. The single comparison form is
   `m7.data.corpus.normalize_entity_value`: Unicode NFC, casefold, NFC again (caseless
   matching), then every whitespace run collapsed to one space and the ends stripped. It is never used for
   offsets, model inputs or stored records. The FreezeReceipt records only
   `entity_disjoint_from_inventory_sha256`, the commitment of the predecessor
   inventory that was checked; journal replay requires it to equal the superseded
   edition's frozen `inventory_sha256` (and to be absent for a first edition). No
   entity value or value hash enters any receipt. This is an exact-value check after
   normalization, not a near-duplicate or alias detector.

Receipts remain narrow and value-free. They do not issue an independent verdict.
Corpus manifests retain `independent_audit='pending'` and `custody_accepted=false`;
actual signed independent scope/verdict remains in the authenticated external
receipt, not a fabricated author-authored approval field.

The host's verifier receives `(kind, digest)` and must authenticate actual contents,
issuer, action scope and current revocation from a trusted store. No permissive
fallback or automatically trusted local JSON exists. `pre_test_lock_binding` must
authenticate the projection against the original D5 lock and intended corpus, not
merely confirm that the digest has 64 characters. Release rechecks all required
receipt revocations on every open/resume/export.

## D5 and D7 channel integration

For D5, `training_channels(bundle, split='train'|'dev', authorization=...,
verify_receipt=...)` accepts an edition/manifest/split-bound current
`TrainingExportAuthorization`, filters only train or development provenance, and
sets record `split_id` to `train`/`dev`. This matches D5's existing
`prepare_training_dataset(channels.records, channels.gold, split=channels.split)`.
It exports no test examples, gold or family metadata. `write_training_channels`
writes new separate records/gold files with a completion manifest; actual training
and permitted artifact creation remain the training host's responsibility.
For a sealed corpus, `lifecycle=...` is mandatory: revoked/superseded editions,
unmatched manifests and new label exports after pre-test release/open are rejected.

For D7, construct its `ReceiptAuthority` with
`verify_receipt=lifecycle.verify_release_receipt`; custody releases are checked
against current local lifecycle state and other receipts go to the external
trusted host. Supply `authorize=lifecycle.evaluation_gate(authority)` to
`execute_edition`. Authority checks occur before the durable custody open. D7 owns
adapter execution and its own begin/terminal journal; D4 never touches those paths.

`released_channels(lifecycle, edition, bundle, authority=...)` authenticates release
before calling D7's canonical `channels_from_bundle`; it does not consume the
execution open. Return value is `(inference_records, evaluator_CustodyGold)`.
`write_released_channels(..., filesystem=claimed_filesystem)` can later materialize these into new directories under
separate, preprovisioned, disjoint worker/evaluator roots. Worker files contain only
opaque LogRecords and their channel manifest, never gold/provenance/block/slice.
Evaluator gold includes D7's block/slice fields privately. Separate roots/paths are
checks, not proof that ACL/process isolation has been provisioned.

## Safe inspection commands, not executed

- `python tools/data/custody.py pins`: guide/generator pins only.
- `python tools/data/custody.py inventory [--inventory <private.json>]
  [--plan <plan.json> --assignments <array.json>]`: component/count/commitment
  summary; full audit suppresses family/component mapping.
- `python tools/data/custody.py bundle --directory <private-bundle>`: verified
  counts/commitments only, no text, span rows or family identifiers.
- `python tools/data/custody.py store --root <private-store>`: locked phase/digest
  snapshot. Its deny-all verifier never grants an action; inspection is not approval.

No CLI prints source examples, lexicons, label rows, normalized strings or raw
exception/validation bodies. Independent custody/audit and all actual runtime,
crash recovery, ACL/isolation, sealing/generation and executor validation remain
deferred until authorized outside Dirty Mode.

## Filesystem and actual-enforcement capabilities

`CustodyPathPolicy/v1` names four existing, local, disjoint roots: private raw
corpus/journal, inference-only exports, evaluator-only gold exports and train/dev
artifacts. `CustodyFilesystem(policy, approval, verify_receipt=...)` authenticates a
current `FilesystemPolicyApproval` for the exact policy/custodian. Its explicit
future `claim_roots()` requires empty preprovisioned roots and writes exclusive
policy markers. A marker is an API ownership commitment, never an ACL or sandbox.
No roots, markers or permissions were created/changed during construction.

`checked_path` rejects relative custody paths, `.`/`..` traversal, network/UNC paths,
symlinks, junctions/reparse points and multiply-linked files before trusting a
resolved path. Each operation checks its root/role and markers. Private storage
and journal mutations now require the authenticated filesystem; raw bundles cannot
be loaded through the sealed-bundle reader without it. Roots must be provisioned
outside cloud/reparse-backed paths. Native OS enforcement must address races,
mapped drives and access by other processes; these Python checks cannot do so.

Training/worker/evaluator exports are new directories with strict allowed channel
filenames and typed manifests. Worker records are strict LogRecords with the
opaque inference split; no gold field or unexpected manifest field is accepted.
Evaluator gold uses D7's canonical CustodyGold schema. `commitment.json` pins every
file's bytes, role, directory and policy. `verify_export(role,directory,expected_sha)`
checks the exact file set/paths/bytes against the externally pinned commitment;
directory names alone are never trusted. Renewed filesystem approvals require the
same policy plus authentication of an old marker's original approval scope.

`IsolationCapability/v1` pins edition, corpus manifest, filesystem policy, worker
policy, actual enforcement-evidence digest, native platform/mechanism, issuer and
validity interval. `IsolationRequest/v1` is the exact requested binding.
`IsolationVerifier.verify(capability,request)->bool` is the host's Protocol for
verifying actual native process/principal/filesystem enforcement. The implementation
supplies NO pretend verifier or default true. `require_isolation(...)` checks both
authenticated capability and enforcement receipts, native platform, expiry,
revocation and actual verifier result. Missing/unknown proof fails closed.

`IsolationGuard(capability,request,verify_receipt=...,platform_verifier=...)`
rechecks that proof on every activation. D6/D7 must bind the same exact worker-policy
digest, including approved worker/artifact/export inputs. A subprocess, sanitized
environment, private directory or approval-shaped JSON is not actual isolation.
The operating host must supply enforcement and the verifier before held-out use.
This source does not grant rights or launch an isolation process.

`CustodyLifecycle(...,filesystem=...,isolation_guard=...)` requires the guard before
release and on every open/resume/channel export. `CustodyReleaseAuthorization/v2`
authenticates the capability digest; `CustodyRelease/v2` retains capability,
filesystem and worker-policy commitments. D7 still binds the release digest in its
LockedEdition and uses the supplied lifecycle evaluation gate; D6 must check guard
request against its exact worker session policy. Old unisolated v1 receipts cannot
be treated as v2. No actual v1/v2 custody store or release was created in this run.

## Nonauthoring audit handoff

`build_audit_handoff(inventory,plan,assignments,custodian_id=...,
implementation_author_ids=...,bundle=None)` returns `AuditHandoff/v1`: guide,
generator, inventory, ancestry, assignments, plan/selection-rule and optional corpus
commitments; effective component and normal/challenge/class/benign counts;
taxonomy/adjudication totals and unresolved issue codes. It exports no family IDs,
lexicons, templates, raw examples, gold offsets or source paths. With no supplied
corpus, population counts are null and `population_status='not_supplied'`; no
measurements are invented. Both independent verdicts remain literal `pending`.

A separately appointed reviewer receives that immutable packet plus custodian-
controlled access to the actual source/sample via the operating host. The packet
alone cannot perform a semantic audit. Only an externally supplied authenticated
`IndependentAuditVerdict/v1` can be consumed by `verify_independent_audit`: it binds
packet, edition, scope, evidence, reviewer and expiry, excludes implementation and
family authors/the custodian, and rejects unresolved or rejected scopes. The
original packet stays pending and immutable; its implementation never signs or
manufactures a nonauthoring verdict.

The final D5 schema is consumed through `release_from_training_lock(...)`, which
calls D5's canonical `verify_pre_test_lock` and `selection_lock_reference`. Release
checks the experiment-plan/edition and cannot outlive either the lock or native
capability. D4 does not reinterpret development scores or recreate lock receipts.

Future host `tools/data/custody.main(filesystem=claimed_filesystem)` adds
`audit-handoff --inventory <private> --plan <private> --assignments <private>
--custodian-id <id> --implementation-author <id> [--bundle-directory <private>]`.
It prints only that value-free packet. Private inventory/bundle inspection requires
the same authenticated filesystem. `capability --capability <file> --request <file>`
prints digests with `platform_enforcement_verified=false` and
`status='shape_only_not_authorized'`; it never claims native enforcement. The split
audit's future host entrypoint likewise accepts `filesystem=...` for sealed data.
Read-only store inspection verifies path/chain shape but issues no authorization.

The optional [Windows qualifier](data-native.md) supplies lazy read-only token,
process and per-object access inspection source. It keeps shared-P prepared-policy
verification separate from exact-PID/full-L postlaunch qualification. It still
requires actual current native control evidence and never applies permissions,
starts a process or treats any-job/handle-count observations as full isolation.
Its CLI defaults to validation only. No native qualification ran in construction.

## Post-primary timing continuation

`m7.data.timing.CustodyTimingAuthority(lifecycle, edition, authorization,
resources=..., verify_process=...)` implements D7's canonical
`TimingContinuationAuthority`. Its `prepare(primary, plan)` is nonconsuming;
`authorize(request)` writes `CustodyTimingConsumed/v1` before returning a
`TimingPhasePermit`; `current(request, permit)` reauthenticates before every
message; `finish(request, completed=...)` appends `CustodyTimingTerminal/v1`.
No method invokes release/open, exports gold, resets a worker or calls inference.
The original private custody hashchain and writer lock hold all phase records.
A fresh timing directory or authority object cannot erase prior consumption.

The separately externally authenticated `CustodyTimingAuthorization/v1` binds the
original release, full edition/run, experiment plan, corpus and selection lock,
closed primary accounting, preregistered timing plan/population/order/arm pins,
shared profile P, exact surviving warm identity/full launch L commitments,
capability/filesystem, D5 resource authorization and UTC expiry. All four original
arm pins and the full population remain fixed. `backends` is a unique ordered
subset of actual surviving original workers; missing arms remain unavailable in
D7's fixed denominator. No invented identity, cold replacement, extra warmup,
selection change, or all-success primary prerequisite is allowed. Closed negative
and interrupted-unknown terminal outcomes remain committed; unresolved primary
begins cannot qualify. Phase completion means accounting/protocol completion,
not successful predictions or independent acceptance.

The trusted lifecycle verifier must authenticate `primary_accounting` against the
actual original immutable closed D7 journal, its head/cells/quality and zero
unresolved begins; shape or a hash alone is insufficient. It must also authenticate
`custody_timing_authorization`, `evaluation_authorization`,
`warm_backend_attestation` and the original current release receipts. D5's
`TimingResourceAuthority.prepare/qualify/current` supplies fresh cash/cap/retry
qualification; the returned receipt must match the exact request and the pinned
resource authorization. Existing training/primary/uncertain liabilities remain
D5's responsibility, never implicitly zero. No resource or custody approval is
created by declaration validation.

`WindowsTimingProcessGuard(lifecycle, process_verifier, policies)` is the concrete
callback adapter for `verify_process`. Every explicit callback checks current
capability and canonical P/member/L/bootstrap bindings, then invokes
`WindowsWorkerProcessVerifier.verify(pid, start_identity, launch_spec, verified,
policy)` including its mandatory real native control verifier. The real D6 host
must retain the original borrowed contexts, current exact-process approvals and
actual environment/network/lifetime/handle evidence. Prepared-policy qualification
cannot substitute for running-process proof. Other host callbacks must satisfy
that same actual-enforcement contract; there is no permissive fallback.

Wire `authority.verify_receipt` into D7/D6's parent receipt verifier for
`timing_custody_continuation`; it recognizes only an unfinished live original
permit and rechecks current guards. Other kinds delegate to the lifecycle's
trusted verifier. Do not replace the lifecycle verifier with this adapter, which
would recurse. No custody/store paths or gold cross the worker wire.

Each arm consumes ordinals1..3 in order; parent namespaces use D7's canonical
`{primary, plan, identity, ordinal}` digest. Only one phase may be outstanding per
edition. Duplicate consumption, changed authority/backend/launch or advancing an
aborted arm fails closed. An unmatched consumed record requires investigation;
there is no resume, clear, recovery authorization, or new-journal bypass. A live
issuer instance is required for messages and completed termination. An explicit
abort can be appended even after expiry/revocation/lost ownership, preserving the
original request and never granting another call. It cannot retry that phase or
advance that arm. A crash during append remains uncertain. No automatic repair
or deletion is provided. Original revocation/supersession immediately blocks new
phases/current checks/completion, while permitting honest abort accounting.

`CustodyLifecycle.inspect()` now reports consumed/completed/aborted/uncertain
ordinals for every original arm. Inspection remains mechanical and value-free;
empty history is not evidence of measured zero latency/cost or authorization.
Construction ran no native qualification, timing, worker, store or model action.
