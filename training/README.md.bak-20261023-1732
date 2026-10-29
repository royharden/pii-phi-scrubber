# Gated training source

No training has run. `validate_training_plan(plan, permit)` checks a hash-pinned
TrainingPlan/v1, at most three trials, three epochs and 1,000 optimizer steps,
dev-only selection and a matching explicit license/custody/spend permit. It always
returns `execution_allowed_now: false`; no executor is implemented in Dirty Mode.

The future authorized executor must validate permit expiry at launch, reserve the
worst-case cost atomically before each trial, retain failed/OOM/cancelled work and
unknown liabilities, enforce the same base/fine tokenizer and decoder, and write
actual environment/config/data/model/checkpoint pins. A smoke run cannot close
M7-02. A receipt shape pass is not an independent audit or proof of execution.

Hashes must be computed from actual artifacts. No example success receipt or
invented checkpoints are supplied. The plan's selection rule is
`dev_macro_exact_f1_then_recall_then_lower_cost`; sealed test access is false.
