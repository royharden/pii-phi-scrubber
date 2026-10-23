# Gated local training source

Canonical code is `m7.training`; this directory contains a compatibility shim and
unapproved plan/config/environment templates. [Training](../docs/training.md) and
[permits](../docs/permits.md) describe the future execution API and trust boundary.

The source now includes an executor and lazy local GLiNER integration. No training,
backend call, dependency install, model download or runtime check has run. Dirty
Mode forbids execution. v1 remains validation-only; v2 adds exact local artifact,
permit expiry, resource/environment, cost reservation and actual-outcome lineage.
There is no automatic approval, selected-checkpoint lock or acceptance claim.
