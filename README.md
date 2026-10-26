# M7 synthetic-log redaction experiment

R03 has executed the local synthetic development journey and test-double failure
paths. The trusted operator host and real receipt, native-isolation and provider
services remain outside this checkout. **Scientific outcomes remain unverified**:
local checks do not establish actual training, model inference, sealed evaluation,
real-model timing, reconciled spending, privacy protection or product acceptance.
A negative measured result is valid.

The task is English fictional NAME, EMAIL, PHONE and ACCOUNT_ID spans in one decoded
JSON `message`, at most 1,024 Python Unicode codepoints. The other three log fields
are preserved. This is a bounded local experiment with CLI/static reports. It is
not a real PHI processor, upload service or compliance product.

## Observed local validation

At the 2026-10-25 R03 combined-candidate checkpoint `bddbb046`, INT recorded **505 tests
passed**, with zero failures, errors or skips, and zero Ruff findings across
`src`, `scripts`, `tests` and `evals`. Eight public development controls passed;
that is a count of checks, not records or real-model results. Their summary records
`model_execution=false`, `held_out_result=false` and `product_acceptance=false`.
The tests use fictional fixtures and injected doubles. Generated development HTML
is not a timed two-minute demo rehearsal.

Later independent reviews verified the combined Docker candidate's eight controls
with a nonroot user, read-only filesystem, disabled networking and no published
ports. The Windows bootstrap candidate `545ff00` passed independent Extra High
review of clean setup, repeat setup from the checkout, OUTER-directory invocation,
no-install checks and offline wheel build/import. POSIX marker behavior was modeled
on Windows; native Linux/macOS execution is unverified.

These are separate candidate checks, not a claim that the final combined tree has
been accepted or merged to `main`. INT owns integration and combined acceptance;
full M7 product acceptance remains open. See the [validation checkpoint and
reproduction guide](docs/VALIDATION.md) for the pinned combined-test checkpoint and
commands after integration. Its bootstrap/Docker pending notes describe that
earlier checkpoint; the independent reviews above occurred afterward.

## Reproducible development environment

Prerequisites: Python 3.11+ for the stdlib bootstrap launcher and **uv 0.11.19**
on PATH. The product interpreter is **CPython 3.12.13** (`.python-version`).
`uv.lock` pins runtime, test, lint and build dependencies, including their artifact
hashes. The initial lock selects Pydantic 2.12.3, pytest 8.4.2, Ruff 0.14.2,
Hatchling 1.27.0 and editables 0.5.

From the checkout, run:

```powershell
.\scripts\bootstrap.ps1
.\scripts\bootstrap.ps1 -Check
.\.venv\Scripts\python.exe -m pytest --junitxml .agent-work/pytest.xml
.\.venv\Scripts\ruff.exe check scripts/bootstrap.py
```

The portable Python entrypoint is `python scripts/bootstrap.py`, followed by
`python scripts/bootstrap.py --check`; on POSIX use `.venv/bin/python` for tests.
These POSIX commands have not been executed natively in R03.
Bootstrap resolves its checkout from the script path, so it also works from another
directory. It downloads Python into `.agent-work/python`, uses `.agent-work/uv-cache`
and creates `.venv` in that checkout. It does not create a global Python shim or
registry entry. Every invocation requires the exact uv version; install that tool
separately through your approved public-package workflow.

Bootstrap installs the locked build group first, then builds the editable package
without an isolated resolver. It never updates the lock, installs model libraries,
downloads model weights, loads credential files or calls a provider. `-Check` /
`--check` performs no installation and verifies the interpreter, installed project
and locked dependency versions selected for its platform, including the `dev` extra
and `build` group. A fresh bootstrap needs internet access to public Python/PyPI
artifacts; a fully populated cache can support subsequent offline checks. Changing
pins is an explicit maintenance action requiring a new lock and validation.

## Offline development journeys

The commands below use the bootstrapped interpreter (`.venv/Scripts/python.exe` on
Windows, `.venv/bin/python` on POSIX), rather than an unrelated system Python.
Optional model libraries and exact versions must be approved/staged separately;
the offline commands never install or download weights. R03's public controls
execute the fictional development demo/eval CLI journey. This is local validation,
not a held-out four-arm experiment.

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

The preferred isolated entrypoint consumes D5's joined `WorkerLaunchBundle/v1` or
`WorkerLaunchHandoff/v1`. Default mode validates operator definitions only:

```powershell
python scripts/eval.py --launch-bundle C:/approved/campaign.workers.json `
  --lock C:/approved/locked-edition.json --authorization C:/approved/evaluation-authorization.json
```

No operator module, receipt service, raw/gold export, database, model or worker is
used by validation. It checks the canonical D5 bundle and immutable edition; it is
never authority or process proof. Future explicit isolated primary evaluation:

```powershell
python scripts/eval.py --launch-bundle C:/approved/campaign.workers.json --execute-campaign `
  --lock C:/approved/locked-edition.json --authorization C:/approved/evaluation-authorization.json `
  --operator-host approved_m7_host:create_campaign_host `
  --custody-lifecycle C:/private-custody/lifecycle --journal C:/evaluator-private/edition-journal `
  --inference-export C:/inference-only/edition --inference-export-sha256 <custodian-export-sha256> `
  --gold-export C:/evaluator-private/edition-gold --gold-export-sha256 <custodian-gold-export-sha256> `
  --out report/generated/edition
```

`create_campaign_host(bundle, edition)` returns `IsolatedCampaignHost`: original
receipt verification/revocation, D4 filesystem/native guard, actual restricted native
launcher and exact-process verifier, parent-only per-arm ledgers, authenticated
training accounting and billing reconciliation. No permissive launcher, fake OS
proof or provider/model fallback is supplied. Missing real prerequisites fail explicitly.
Workers receive approved bootstrap/configuration and opaque records, never gold,
provenance, custody/export/ledger paths, host modules or inherited credentials.

D6's canonical shared profile P contains member hashes excluding only `profile_sha256`;
full exact per-arm L includes P. Campaign/capability/release/guard bind the same P.
Profile qualification is prelaunch. Exact PID/start/image/native-rights checks bind
P+L after launch and before messages. A subprocess alone is not isolation.
Pre-channel `authority + require_released` never consumes open; `execute_edition`
alone first-opens after corpus preflight. Owned workers close on all exit paths;
unverified cleanup writes a private investigation marker and blocks automatic reuse.
Closed-edition replay starts no worker. See [the consumer contract](docs/experiment.md).

The isolated campaign also has an explicit retained-worker timing continuation.
Supply `--run-timing --timing-plan path/to/isolated-timing-plan.json
--timing-resources path/to/timing-resource-schedule.json
--timing-out C:/evaluator-private/new-timing-directory` on the **initial**
`--execute-campaign` invocation above. Real-model campaign timing has not run;
local timing tests exercise injected doubles. Without `--execute-campaign`, the
plan is structurally validated without loading a host, reading held-out channels,
querying native controls or launching.

The preregistered `IsolatedTimingPlan/v1` pins original record order/hashes, all
four model/config/checkpoint pins, hardware/environment/library commitments,
length partitions, concurrency 1 and exactly three passes. Its hash excludes the
full edition/profile/launch digests to avoid a hashing cycle. A later authenticated
post-primary receipt binds those actual identities, immutable closed primary
accounting, current custody/native authority and worst-case resources/expiry.
The trusted host supplies `timing_authority_factory(custody=..., bundle=...,
edition=..., primary=..., plan=..., resources=..., identities=...)`, implementing the narrow D4 continuation/D5
resource contract in [the timing protocol](docs/experiment.md). No receipt file
can authorize itself. Missing real worker phase support remains unavailable.

Timing retains the original loaded backend and process. Each pass resets only
logical caches/controllers and has a distinct parent-brokered attempt namespace.
It sends the same original bounded record IDs/content, retains gold in the evaluator,
and never opens held-out custody again. Closed-primary replay cannot request warm
timing because its original workers have exited. Dead/failed arms remain in all
three fixed denominators; the coordinator never respawns them as warm. Interrupted
phases/unknown cleanup require investigation, not a fresh directory or retry.

Primary quality stays frozen. Campaign cash totals include timing/retries and
unresolved liabilities; per-arm primary-quality cost rows remain primary-only.
Cold figures measure process/init handshake, not pure model-load time; provider
server startup remains unknown. Warm latency includes the supervised detector,
validation and renderer call boundary, including required transport/guard costs.
Evaluator gold safety/scoring/bootstrap overhead is separate. All samples remain
private; numeric/enum aggregates pass the existing whole-artifact gold scan.

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

The lower-level `--execute-locked` path remains a qualified-host integration seam.
Use the isolated campaign continuation above for authoritative worker timing.
Legacy `TimingPlan/v1` in-process timing is not isolated-worker evidence.

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

## Host composition root

Execution needs an operator-built host. `m7.host` is an inert composition root: it
only wires existing adapters to host services the operator supplies, and it
provides no trust services, verifiers or credentials of its own. Its default module
always refuses. Without real host services, `--operator-host
m7.host.unavailable:campaign_host` (or `scripts/train.py campaign --training-host
m7.host.unavailable:training_host`) is designed to report `status: unavailable`,
which is the honest unavailable state without those services. Local host tests
exercise injected success/refusal branches; they do not qualify a real operator
host or native isolation service.

## Tests

`tests/` holds pytest source for contracts, rendering, scoring/bootstrap, the
reservation ledger, the offline runner, detectors, providers, training, corpus
custody data, the experiment journal and result projection, publication gates and
the static report.
Expected values are derived by hand from the plan and contracts and the derivation
is written beside each case. R03 executed and repaired the inherited synthetic
suite; the combined checkpoint results above do not imply that an isolated branch
contains every combined repair. A failure must be traced against the plan before
either code or expectation changes. Reviewers
own regression/evaluation tests and independent verdicts. From this directory:

```powershell
.venv/Scripts/python.exe -m pytest
```

`pyproject.toml` sets `pythonpath = ["src"]` and `testpaths = ["tests"]`. Paths
that need a real model, provider or native host are exercised only through
injected stubs (success and fail-closed branches), so a passing suite would not
establish those integrations. Ledger tests use a local temporary SQLite file.

In reports, `N/A (n/d)` marks an undefined metric with a zero denominator (macro:
`N/A (d/c classes defined)`), `insufficient` (in an Interval column) an interval
with fewer than 20 blocks or 1,800 valid draws, `unknown` a cost status that is not reconciled, and
`not measured` any value that is unavailable (never run, not reconciled or not
computed). None is zero.

## Still required

INT's final integration and combined-tree acceptance; actual platform-enforced
custody and independent family/label audit; licensed immutable models/data and
approved resource/provider terms; actual bounded training, dev locks, four real
arms, controlled real-model timing and reconciled receipts; clean timed offline
rehearsal and nonauthoring finished-product acceptance. Local unit/control tests
and the isolated development Docker checks close none of these scientific gates.
No production deployment, remote publication or clinical/privacy certification
follows from this work.

Newly authored source is MIT. Model/data/dependency rights are separate; see
[VENDORED.md](VENDORED.md). The shell's historical name expands none of this scope.

Timing survivor rule R1: resource/custody authorizations pin only actual surviving
original warm identities and explicitly mark unavailable arms. The immutable plan
retains all four launch pins, worst-case caps and all 12 arm/pass denominators.
Missing identity is never replaced, fabricated or treated as zero cost/latency.

The timing host factory returns canonical D4 CustodyTimingAuthority over the supplied
original lifecycle/edition, with canonical D5 TimingResourceAuthority over the
supplied bundle/schedule. Both authorities must bind exactly the verified actual
survivor identity set. D7 supplies authority.verify_receipt as a parent-only
keyword to D6 begin_timing_phase; this authenticates live consumed custody permits.
It is never sent to the worker or installed as the independent lifecycle verifier.
Whole-phase elapsed time/throughput includes authorization and durable bookkeeping;
call-boundary latency and parent-control overhead remain separately labeled.

As-built D6-E integration: the host also supplies warm_attestor(claim,physical_calls)
for actual independent original backend/process attestation. D7 forwards it on the
ORIGINAL launch. Bootstrap timing_plan_sha256 and timing_order_sha256 must already
be pinned before profile/launch approval; null means unsupported. The actual
begin_timing_phase(...,verify_receipt=...) source API is consumed directly; the
optional bind_timing_authority bridge is not required by this consumer.
The returned D4 authority uses WindowsTimingProcessGuard over the same original
lifecycle, host process verifier and exact campaign launch policies. No native
probe occurs during construction; every future message requires current proof.
