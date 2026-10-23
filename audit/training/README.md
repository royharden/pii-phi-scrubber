# Actual training receipts pending

No real model, training trial, compute time, checkpoint or result is recorded.
The canonical `m7.training` executor writes actual outcomes only in a future
authorized staging area, under `runs/<edition_id>`, with the shared reservation
ledger under `accounting/`. No fake receipt is supplied here.

TrainingReceipt/v2 preserves plan/permit/model/tokenizer/data/config/environment,
trial/seed and checkpoint lineage. Failures/OOM/cancellations never become a
successful checkpoint. Missing billing remains unknown with liability retained.
`validate_training_receipt` is a structural check and leaves independent audit and
M7-02 acceptance pending. See [training](../../docs/training.md).
