# Local synthetic validation

## R03 candidate checkpoint — 2026-10-25

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

This is a candidate checkpoint, not a statement that these changes have landed on
`main`. This documentation branch alone does not contain all combined repairs or
the new bootstrap/check/eval scripts. Final integration and combined-tree acceptance
belong to INT. At this checkpoint, the bootstrap portability repair awaits High
review, and combined Docker image rebuild/verification remains pending. The earlier
standalone Docker eight-check run does not validate the combined repairs.

Private run evidence is retained outside the product repo under
`agentops/runs/PB-M7-R03/`: `evidence/INT3-local-check-r2.log`,
`evidence/INT3-public-eval-r2.log` and the INT integration worktree's JUnit XML
`pytest-ff53ba45a7ac4d679d686905ab175232.xml`. These are run receipts, not portable
product dependencies. The counts above describe that checkpoint; a later candidate
requires fresh checks.

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
