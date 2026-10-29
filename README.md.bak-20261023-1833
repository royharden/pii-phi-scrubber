# M7 synthetic-log redaction experiment

Source construction is complete for the currently assigned implementation scope;
**runtime and scientific outcomes remain unverified**. Nothing in this checkout
establishes actual training, model inference, sealed evaluation, timing, spending,
privacy protection or product acceptance. A negative measured result is valid.

The task is English fictional NAME, EMAIL, PHONE and ACCOUNT_ID spans in one decoded
JSON `message`, at most 1,024 Python Unicode codepoints. The other three log fields
are preserved. This is a bounded local experiment with CLI/static reports. It is
not a real PHI processor, upload service or compliance product.

## Intended journeys after runtime activation is authorized

The commands below describe future use. They have not been run during Dirty Mode.
Use an independently approved, locked Python 3.12+/Pydantic 2 environment. Optional
model libraries and exact versions must be approved/staged separately; the source
never installs dependencies or downloads weights. No `uv.lock` is fabricated.

Public fictional development fixture, with a deliberately scored and suppressed miss:

```powershell
python scripts/demo.py --offline --out report/development-demo.html
python scripts/eval.py --edition development --arms regex --out report/development.html
python scripts/eval.py --edition development --arms none --out report/unrun.html
python scripts/eval.py --validate-lock path/to/locked-edition.json
```

The eight public examples share one development block. They cannot establish a
held-out comparison or confidence interval. The last command checks shape/expiry
only: it does not authenticate, seal, open, train or execute an edition.

## Custody, training and inference source

`m7.data` builds original family/lexicon/scenario ancestry and generator-defined gold,
audits whole connected blocks and separates records, gold and provenance.
`CustodyLifecycle` freezes, seals, releases, opens once, revokes and supersedes an
edition. Actual authenticated native isolation, disjoint claimed filesystem roots,
and independent custody/label audit are required for a held-out release. Shipped
development families do not supply 20 independent held-out units.

`m7.training` implements future bounded local training with at most three trials,
explicit artifact/license/resource permits, reservation-before-attempt, failure/OOM/
cancellation receipts and checkpoint lineage. Its dev-only selection, exported
checkpoint/parity checks, target justification and `PreTestSelectionLock` freeze
configuration and approved numerical floors before held-out access. Validation is
not execution. See [training](docs/training.md) and [permits](docs/permits.md).

`m7.detectors.registry.build_registry` builds regex/frontier/base/fine callables
without I/O. D6 bindings check exact run/model/artifact/configuration pins. Calls
need explicit activation and current permits. A shared controller allows at most
one declared transient transport retry, never malformed-content repair; physical
attempts, usage, failures and unknown liabilities are retained. See
[adapters](docs/adapters.md). No provider, credential, tokenizer or paid account is
automatically selected. Provider credentials are injected in memory by a later
trusted operator; no credential files are read by the evaluation CLI.

## One locked edition, one durable evaluation

The [executor contract](docs/experiment.md) fixes identical record/hash populations
and all four arm pins. It gives adapters only standalone inference records. The
trusted evaluator separately holds gold and block/slice metadata. Pre-test D5 locks,
D4 release/isolation and current externally authenticated receipts are checked before
held-out channels are read and again before new logical calls.

Future trusted operator activation (all paths/receipts are operator-provided, not
supplied approved artifacts):

```powershell
python scripts/eval.py --execute-locked `
  --lock path/to/locked-edition.json --authorization path/to/evaluation-authorization.json `
  --selection-lock path/to/pre-test-lock.json --targets path/to/numerical-targets.json `
  --custody-bundle C:/private-custody/edition --custody-lifecycle C:/private-custody/lifecycle `
  --journal C:/evaluator-private/edition-journal `
  --operator-host approved_m7_host:create_host --out report/generated/edition
```

The operator module is trusted executable code, reviewed and provisioned outside
this checkout after activation. No permissive host or sample approved receipt is
shipped. `create_host(edition)` returns `OperatorHost` with an inert D6 registry
factory, real receipt verification/revocation, D4 filesystem/isolation capabilities,
complete training/inference cost supplier and optional timing factories. Isolated
worker proxies can supply value-free `AdapterBinding.attempt_metadata`. A factory
must not perform inference or read gold during construction. Native worker/access
enforcement is required; an in-process function signature cannot provide it.

The same command resumes the same edition. A durable begin with no terminal becomes
`interrupted_unknown` and is never reissued. Cancellation leaves never-begun cells
pending. A closed edition reconstructs scores without model calls. Missing arms,
preflight failures and budget rejections are visible; an unrun arm has null metrics.
A new adapter or test-informed change requires a new authorized edition, not erasing
this one's outcomes. The output directory must be new. No command starts a listener.

Add `--run-timing --timing-plan path/to/timing-plan.json --timing-out C:/evaluator-private/timing`
only when a separate current `timing_execution` receipt authenticates that plan and
its costs. The primary edition must first be closed. Timing uses concurrency 1,
three fixed-order warmed passes, fixed length slices and separately measured cold
initialization. Fresh per-pass D6 controllers share the warmed backend, so replay
caches cannot masquerade as timing. Network frontier and offline local timings are
labeled separately. Interrupted timing cannot silently restart; its marker/partial
samples remain for investigation. Hardware/library locks and gold safety/scoring
overhead are displayed separately from detector+validator+renderer latency.

## Results, costs and safe offline replay

Unconditional per-class/micro/macro P/R/F1, normal/challenge/total rows and all intended
failures remain visible. Renderer-unavailable output uses the full gold-sensitive
mask. Benign-only failures are unavailable without invented gold leaks. Whole-block
paired percentile intervals use 2,000 fixed draws, 95%, at least 20 blocks and 1,800
valid draws; undefined draws are counted, not zero-filled. Successful-only scores
are secondary. The report retains negative/no-deploy outcomes and per-class floors;
macro improvement cannot excuse a weak class. Passing engineering gates is only a
candidate for independent review, never deployment or product acceptance.

`ReservationLedger.summary` exposes actual cash, reserved unknown liabilities,
usage, state and training/inference/retry/failed-trial categories. The host combines
distinct training and inference authorizations in one authenticated currency using
`combined_cost_summary(..., currency=...)`. A partial ledger cannot satisfy the
full-cost gate. Verified zero provider invoice cash leaves electricity, hardware
amortization and total economic cost unknown unless separately measured/allocated
and authenticated. Remaining cap is not permission to transfer between authorizations.

Artifact JSON/HTML are assembled in memory, projected through closed fields and
scanned against held-out gold plus exact/escaped/HTML/URL/normalized value surfaces.
Unsafe documents are suppressed without improving upstream quality. No held-out
text, gold/prediction span table, prompt, completion or exception body enters public
reports. Journals and timing samples stay private. No measured report is supplied
by this source-only construction.

After a future report passes that gate, the two-minute offline journey copies its
approved HTML byte-for-byte using its externally recorded SHA256:

```powershell
python scripts/demo.py --offline --approved-report path/to/approved/index.html `
  --report-sha256 <approved-html-sha256> --out report/replay.html
```

This never reopens held-out data or calls a model. Regenerating artifacts with a new
renderer requires custody/gold-aware validation again. See [demo](docs/demo.md),
[model card](docs/model-card.md), [limits](docs/LIMITATIONS.md) and
[construction status](docs/CONSTRUCTION.md).

## Still required

A locked environment and meaningful runtime/import/Unicode/wire/scorer/journal/budget/
privacy/integration checks; actual platform-enforced custody and independent audit;
licensed immutable models/data and approved resource/provider terms; actual bounded
training, dev locks, four real arms, controlled timing and reconciled receipts;
clean offline rehearsal and nonauthoring finished-product acceptance. No CI,
container/environment/deployment scaffolding, remote or publication is supplied.

Newly authored source is MIT. Model/data/dependency rights are separate; see
[VENDORED.md](VENDORED.md). The shell's historical name expands none of this scope.
