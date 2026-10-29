# M7 synthetic-log redaction experiment

Source construction scaffold, runtime unverified. This local experiment asks whether
fine-tuning a small entity detector improves redaction on unfamiliar fictional
developer logs. A negative measured outcome is valid. No model has been trained or
downloaded by this construction, and no held-out result or production privacy claim
is established.

The supported task is English NAME, EMAIL, PHONE and ACCOUNT_ID spans in one decoded
JSON `message` field, at most 1,024 Python Unicode codepoints. Other log fields are
preserved. This is not a real PHI processor, upload service or compliance product.

## Offline development journey

The following are intended commands for a later authorized runtime validation phase.
They have **not been run** during Dirty Mode. Python 3.12+ and Pydantic 2 are required;
the dependency environment and exact lockfile remain to be established. No `uv.lock`
is fabricated. The scripts resolve the source tree themselves.

```powershell
python scripts/demo.py --offline --out report/demo.html
python scripts/eval.py --edition development --arms regex --out report/development.html
python scripts/eval.py --edition development --arms none --out report/unrun.html
python scripts/audit_split.py --manifest path/to/declared-manifest.json
python scripts/train.py --validate-only --plan path/to/plan.json --authorization path/to/permit.json
```

Outputs use exclusive creation: choose a fresh filename for each edition. No command
starts a listener or accesses a model provider. Evaluation supports public development
fixtures only; a sealed evaluation executor is not implemented. The training wrapper
validates a proposed plan and always reports execution disallowed. It never trains.

The eight raw examples in `data-development/public-fictional.json` are explicitly
public fictional development fixtures, the sole source-text publication exception.
All share one development provenance block. They are not independent test families.
The `dev-008` uncued-name miss remains a scored leak and its example is suppressed by
the gold-aware publication gate. Frontier, base and fine-tuned arms remain unmeasured
without approved real backends. Unrun/null results never mean zero failures.

## Architecture

`m7.contracts` freezes strict span and log boundaries. Detectors receive records
without gold. `m7.render` unions intervals after exact detection scoring.
`m7.eval` reports exact matching, failures, residual sensitive characters,
overredaction and provenance-block uncertainty. `m7.runner` keeps the intended
population visible. `m7.publish` checks complete gold-mask coverage, unchanged safe
fields, exact replacements and escaped value variants before rendering any example.
Reports accept only explicit numeric aggregate fields, never arbitrary result text.
Source values and provider completions must not enter diagnostics or ledgers.

The gate uses in-memory gold and can conservatively suppress coincidental matches.
It does not detect arbitrary PII. Publication suppression cannot improve scores.

## Remaining acceptance gates

- Runtime/unit/contract/integration validation and a real offline rehearsal.
- Exact dependency/model/tokenizer rights, immutable revisions and hardware feasibility.
- Independent held-out custody, ancestry and labeling audit, and pre-test locks.
- Approved bounded resources; actual training and all four real arms on identical inputs.
- Reconciled costs, controlled timing, sufficient independent blocks, safe artifacts,
  and nonauthoring product acceptance.

Read [model card](docs/model-card.md), [limits](docs/LIMITATIONS.md),
[demo](docs/demo.md), [annotation guide](docs/annotation-guide.md), and
[vendoring and rights](VENDORED.md). Newly authored source is MIT licensed; model,
data and dependency rights require their own review.
