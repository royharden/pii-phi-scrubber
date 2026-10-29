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
| `storage.write_bundle(bundle, destination, private_root=...)` | Custodian; new directory, separate JSON channels, manifest completion marker last |
| `storage.read_bundle(directory)` | Custodian/evaluator only; bounded read, strict schema and commitment verification |

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

The future host entrypoint `tools/data/seal.main(verify_receipt=trusted_verifier)`
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

`CustodyLifecycle(root, verify_receipt=trusted_verifier)` uses an existing private
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
   `ReleaseAuthorization` additionally binds run, experiment-plan hash, exact
   population, audit and expiry. Only one release is allowed per edition.
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
   holdout. Histories and prior failures remain intact.

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
`write_released_channels` can later materialize these into new directories under
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
