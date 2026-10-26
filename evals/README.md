# Public development checks

`python evals/public_eval.py --out <new-directory>` runs eight offline controls:
exact spans, wrong labels, partial spans, failed-record denominators, insufficient
independent blocks, escaped leak suppression, SQLite reservation racing and durable
liability, and the public demo/eval CLI journey. The output directory must be new;
prior evidence is preserved. `summary.json` contains names and pass/fail values.

Fixtures are explicitly fictional development examples. Fake predictions exercise
the arithmetic; they are not frontier/base/fine-tuned model results. CLI commands
use only `data-development/public-fictional.json`. No hidden families, held-out
specifications, model downloads, provider requests or credentials are needed.
Neither a green run nor Docker packaging constitutes full M7 product acceptance.

`scripts/check_docker.ps1` builds a pinned Python image and runs the same checks
with networking disabled, SQLite inside the container and no published ports.
It requires an existing `m7/r03-rv2` agent-ports claim, preserves the stopped
container and prints its immutable image ID and logs. Container logs contain the
value-free summary. Image pulls/dependency installation occur during the build;
the actual evaluation runs with `--network none`.
