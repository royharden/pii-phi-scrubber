# Local synthetic validation

## W2 combined-candidate checkpoint — 2026-10-26

INT ran the full combined `check_local.ps1` gate on staged tree
`27f5c33975600bff0b55981c62d8d8f1f88356b8`, using Windows PowerShell,
Python 3.12.13, Pydantic 2.12.3, pytest 8.4.2 and Ruff 0.14.2:

- **687 tests passed**, with zero failures, errors or skips: 505 accepted-baseline
  cases plus 84 RV1-authored and 98 RV2-authored cases. This is one full combined
  execution, distinct from the earlier standalone 505- and 98-case runs.
- Root Ruff across `src`, `scripts`, `tests` and `evals` was clean.
- Eight host public-development controls passed, zero failed. Their summary
  records `model_execution=false`, `held_out_result=false` and
  `product_acceptance=false`.

The staged inputs were D9 `7d490898`, D10 `08adff02`, D11 `a07b6cea`,
D8 `7c1bb28d`, RV1 `f6e8bd85` and RV2 `a42b6157`. W2 source is not yet installed
on `main` at this checkpoint; the fresh Docker check is pending. These host tests
validate local fictional/mock/readiness behavior. They establish no real-model,
scientific, privacy, deployment or formal W8 product acceptance. Later candidate
changes require their affected checks and review.

Effie's delegated decision of 2026-10-25 permits H1 public no-login, read-only
metadata/licence/terms lookups, with source URL and retrieval time recorded. This
is a delegated decision, not Roy's personal signature. Model, weight, backbone
and tokenizer downloads remain restricted. Metadata permission does not supply
approved artifact rights, immutable revisions/hashes, a size cap, actual weights
or execution authority. H2 actual-model training/evaluation, H3 live frontier,
H4 new custody/auditor staffing and sealed access, H5 real native qualification,
and H6 formal acceptance remain restricted. No final acceptance reviewer is
appointed; scientific readiness and the product packet stay **NOT_READY**.
See the [W8 inventory](acceptance/README.md) for unmet prerequisites.

D8 reran only the bounded keyless fictional demo twice for this new walkthrough.
Both runs exited zero, reported eight records and one suppression card, and
produced identical HTML bytes; see [demo](demo.md) for the command and digest.
This is repeatability evidence, not a second full-suite claim, actual-model result
or human timed rehearsal. No held operation was attempted.

## Historical wave1 candidate checkpoint — 2026-10-25

PB-M7-R03 is in normal mode. INT observed the following on its combined candidate
tree `bddbb0466911613b64079502f307b5891572832b`, using Windows PowerShell,
Python 3.12.13, Pydantic 2.12.3, pytest 8.4.2 and Ruff 0.14.2:

- `check_local.ps1`: 505 tests passed; zero failures, errors or skips. The JUnit
  XML and command log were inspected for these counts.
- Ruff: zero findings across `src`, `scripts`, `tests` and `evals`, as recorded by INT.
- `public_eval.py`: eight development checks passed, zero failed. Its summary
  explicitly records `model_execution=false`, `held_out_result=false` and
  `product_acceptance=false`.

The test suite covers local synthetic contracts and failure paths with fixtures
and test doubles. The public controls cover exact spans, wrong labels, partial
spans, failed-record denominators, insufficient independent blocks, escaped leak
suppression, a SQLite cap race/durable liability, and the public demo/eval CLI
journey. Development HTML was generated; this is not a timed demo rehearsal.

At that historical checkpoint, bootstrap portability review and combined Docker
verification were still pending. Wave1 was subsequently accepted locally at main
`8c23fce`; that does not imply W2 installation or full product acceptance. The
earlier standalone Docker eight-check run does not validate the W2 combined tree.
Maintainer-held logs, JUnit XML and public-control summaries preserve these dated
observations; they are evidence receipts, not product runtime dependencies.

## Reproduce after integration

Run these from the product checkout containing the reviewed R03 scripts and
lockfile. Commands are shown for PowerShell. `python` must be 3.11+ for the
stdlib bootstrap launcher, and uv must be exactly 0.11.19. Bootstrap installs the
locked Python 3.12.13 environment locally; it does not install global tools or
load model weights. Package/interpreter installation requires registry access.

```powershell
python scripts/bootstrap.py
python scripts/bootstrap.py --check
pwsh -NoProfile -File scripts/check_local.ps1 -EvidenceDirectory .agent-work/validation/local-run-01
.\.venv\Scripts\python.exe -m ruff check src scripts tests evals
.\.venv\Scripts\python.exe evals/public_eval.py --out .agent-work/validation/public-run-01
```

Use a new `public-run-01` output directory name for each run; existing evidence is
preserved. Inspect the emitted JUnit XML and `summary.json`, not exit codes alone.
`check_local.ps1` runs all tests and its selected reviewer-test lint scope; the
separate Ruff command above checks the complete source/script/test/eval scope.
The check and public-eval commands make no live provider calls and require no API
keys or credential files. The public CLI journey uses only the fictional development
fixture; fake predictions validate arithmetic rather than model performance.

## Gates still open

No actual frontier/base/fine-tuned model execution, real training checkpoint,
sealed-family experiment, license/spend approval, invoice reconciliation or native
OS custody qualification follows from these checks. Model weights, real host
services, independent family/label audits, locked four-arm evaluation, real-model
timing and nonauthoring product acceptance remain separate requirements. No privacy,
clinical compliance, superiority or deployment claim is established. See
[limitations](LIMITATIONS.md), [model card](model-card.md) and [demo](demo.md).
