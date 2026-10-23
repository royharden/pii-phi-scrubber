# Training permits and trust boundary

No template here grants permission. Approval, licensed local artifacts, independent
custody/audit, resource authority, actual spend cap and Dirty Mode closure are
separate prerequisites. Hash checks prevent mismatched bytes; local JSON is not a
signature, legal opinion or authenticated approval channel. A future operator
must obtain the permit from INT/Roy's authorized, access-controlled record and
verify its issuer. Do not accept a user-uploaded or model-generated approval file.

`ExecutionPermit/v2` requires exact keys (extras rejected): schema/version,
authorization ID, `approved=true`, `training_allowed=true`, exact canonical plan
hash/edition, license/custody hashes, resource ID, integer `cap_micros`, currency,
UTC `issued_at`/`expires_at` and approver ID. It must be current at launch and every
training heartbeat; issue time is inclusive and expiry is exclusive. No key,
token, provider account or credential is read. The plan hash covers every path,
artifact digest, trial setting and cap. Any changed byte/settings requires a new
reviewed plan/permit; it cannot silently reset an edition's three-trial allowance.

The license packet must explicitly permit training and derivatives for the exact
model/tokenizer/train/dev hashes. An approved TrainingCustody/v1 must identify
distinct author and auditor, pin train/dev data, restrict allowed splits to
`['train','dev']` and deny test access. These are scope checks of supplied records,
not author-created independent verdicts. The training custodian export is distinct
from D4's sealed CorpusBundle and must be prepared outside the training worker.

The cap must cover all planned worst-case reservations. Accounting uses integer
microcurrency and one immutable authorization/currency per ledger. Do not reuse
the same authorization ID for a different plan/currency/cap or bypass the retained
accounting by changing staging roots. Unknown and interrupted liabilities stay
charged until an authoritative cost receipt reconciles them. Failed trials count
toward the three planned slots. There is no automatic spending or retry approval.

Fill the unapproved JSON templates only after real decisions, hashes and timestamps
exist. Null digests, equal UNAPPROVED author/auditor IDs, false approvals and absent
environment versions deliberately prevent execution. Keep real approval receipts
outside public demo artifacts; never put credentials or model response bodies here.

The promoted plan's licensed training, held-out experiment, numerical target lock
and independent product gates remain open. This source provides no approval and
does not assert that any trial or training receipt exists.

## Selection locks and recovery authority

Selection policy and actual development evaluations must be authenticated and
registered before observation, with the same finite threshold rule for base/fine.
The selection-rule hash pinned by custody is the pure DevSelectionRule/v1 digest;
the DevSelectionPolicy separately pins exact dev and training artifacts. No
custody or evaluation process duplicates selection arithmetic.

PreTestLockApproval/v1 authorizes only `lock_targets_before_heldout` for the exact
`binding_sha256` returned by `lock_binding`. It requires authenticated INT approval,
current UTC window and development-justified target rationale. Approval is separate
from `pre_test_selection_lock` admission, `pre_test_lock_binding` projection
admission, custody release and evaluation authorization. The unapproved template
contains `approved=false`, null hashes/times and cannot produce a lock.

TrainingRecoveryAuthorization/v1 authorizes only
`account_interrupted_no_restart`, tied to the exact original run/plan/permit and
an authenticated stopped-worker receipt. No callback defaults to true; no PID
recency or missing heartbeat proves that a worker stopped. Recovery preserves
originals and unknown liabilities, cannot turn a partial checkpoint into completed
training, and starts no new trial. Its template grants nothing.

## Campaign inference authority

CampaignSpec/v1 requires separate local inference-license and hardware receipts,
provider license/resource/terms receipts, a combined cash authorization that retains
prior training liabilities, and original custody/evaluation/independent-audit
references. Model training license permission is not inferred to cover inference
or redistribution. Three adapter permits must bind the exact run/model/config,
attempt-policy hash and allocated cap; all remain subject to issuer/current
revocation checks in the real host authority store.

The campaign pins D4 filesystem/worker-policy and actual isolation-capability
digests. CampaignHost has no default verifier and requires D4 IsolationGuard's
actual platform enforcement check before preparing a handoff. This source never
installs or modifies that enforcement. A subprocess/path alone is not evidence.
Unapproved templates contain no real hashes or permits; validate-only never grants
activation. The host-injected --activate path fails explicitly if the real host
is absent, and never runs a training/model/evaluation workload itself.

## Joined worker handoff qualification

WorkerLaunchBundle/v1/WorkerLaunchHandoff/v1 do not authenticate themselves.
Preparation additionally requires current worker_launch_bundle and worker_bootstrap
approvals. Shared profile P and every exact member/full L/bootstrap/application/
runtime/root pin must match the existing campaign/capability. D7 receives the typed
prepared bundle and exact descriptors, not a second selection validator.

D4 WindowsIsolationVerifier's authenticated prepared-policy qualification is
prelaunch and requires no running worker. Exact PID/start/image/P+L native process
proof belongs to WindowsWorkerProcessVerifier only after D6's owned launch and
before messages. No prelaunch campaign can satisfy or fabricate that process proof.
Default CLI remains nonexecuting and structural validity grants no source/model/
provider/native authority. Prior prepared receipts must be freshly requalified.
