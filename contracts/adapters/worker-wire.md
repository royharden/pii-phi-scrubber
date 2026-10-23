# Isolated worker/session source v1

Source only, runtime unverified. `m7.providers.worker` is the parent session,
`worker_wire` the strict wire, `worker_service` the child, `worker_transport` the
native-launch/pipe contract and `worker_profile` the pure canonical policy models.
Importing these sources does not launch workers, open databases or load models.

`WorkerSessionProtocol` exposes `arm`, `model_id`, `artifact_sha256`,
`configuration_sha256`, `last_attempts`, `cleanup_status`,
`preflight(tuple[LogRecord,...])`, `predict(LogRecord)->Prediction`, `cancel()` and
`close()`. D7 constructs `AdapterBinding(pin,session.predict,session.preflight)`;
it retains gold/custody itself and closes/cancels its owned sessions in finally.
No bundle, directory, gold, family, provenance or training channel enters requests.

## Shared profile P and exact launch L

The binding source decision is `SEAM-DECISION-WORKER-PROFILE-R1` in private operator
records. Product models/hashes live only in `m7.providers.worker_profile`, which has
no custody/launcher/training imports. Consumers must import these helpers:

- `WorkerProfile(schema_version='WorkerProfile/v1',profile_id,members)` is a closed,
  immutable arm-to-member mapping. Only regex/frontier/base/finetuned keys exist;
  no wildcard and no shaped approval boolean. JSON readers reject duplicate keys.
- `WorkerLaunchMember` holds every exact launch field except the shared profile
  digest. It lets an exporter calculate member hashes without a fabricated placeholder.
- `WorkerLaunchPolicy/v2` adds required `profile_sha256` to the complete member fields.
- `launch_member_digest(policy)` hashes the canonical launch object excluding ONLY
  profile_sha256. It accepts either complete member fields or a full launch policy.
- `worker_profile_digest(profile)` is P. `validate_worker_membership(profile,policy)`
  checks P and the arm's member hash, returning WorkerMembership(P,member,L,arm,bootstrap).
  L is canonical full policy hash, including P. All hashing uses sorted keys, compact
  separators, ensure_ascii=True, allow_nan=False. Full L is never embedded back into P.

Prepare member descriptions, compute their digests, create the enumerated profile,
compute P, then create exact full launches with P and compute L. Campaign exports
pin each full L separately and require profile members to equal actual launched
arms. D4's existing worker_policy_sha256 means P. The full per-arm policy additionally
pins exact bootstrap/config/permit/quota, executable, entrypoint, approved application
manifest/runtime environment, directories, deadlines and lifetime. No unlike hashes
are equated and no process/environment/resource field is dropped from membership.

## Validation and explicit activation

`validate_worker_spec(bootstrap,policy,*,profile)` checks definitions, membership,
bootstrap/config/permit/policy pins, expiry and lexical local paths without spawning,
reading artifact/code files or opening a ledger. CLI:
`python scripts/infer.py --validate-worker --bootstrap <json> --policy <json>
--profile <json>`. It explicitly reports spawned/isolation_verified/artifact_files_checked=false.
No example approved receipt, actual hash or native enforcement result is fabricated.

`launch_worker(bootstrap,policy,*,profile,isolation_guard,launcher,process_verifier,
ledgers,allow_execution=False,reconcile_verifier=None,diagnostic_sink=None)` is future
explicit activation. D4 IsolationGuard.require_current binds edition/corpus/root
policy and shared P, authenticates the isolation capability and inspects actual OS
enforcement. D6 additionally authenticates worker_profile_approval(P),
worker_launch_approval(L), worker_application_manifest and worker_runtime_environment.
Missing authority or mismatch fails closed; no default-true verifier exists.

Native `IsolatedLauncher.launch(spec,VerifiedIsolation,timeout=...)` must launch a NEW
restricted process/job under the approved principal with bounded startup/lifetime,
no inherited custody/credential handles, no shell or server, and cleanup on failed
start. The spec uses absolute executable plus `-I -B <pinned-entrypoint> --worker`,
an explicit scratch cwd, pipes, discarded stderr and close_fds. Environment is built
from an allowlist, never inherited: offline/telemetry flags, fixed locale, scratch
TEMP/TMP, and optional approved Windows system directory. No HOME/USERPROFILE,
PATH/PYTHONPATH, credential, provider or token variables are forwarded.

`WorkerProcessVerifier.verify(pid,start_identity,spec,VerifiedIsolation,exact_policy)`
must attest the actual process birth/image, P plus full L/bootstrap/member pins,
approved imported application/runtime manifests, handles, native filesystem/network
rights and descendant/lifetime policy. PID, directory naming, signatures alone or
Popen existence do not prove enforcement. WindowsIsolatedLauncher now provides
concrete creation source; real preprovisioned context and native verification remain
explicit activation dependencies, with no permissive fallback. `PipedWorker`
only wraps an owned already-restricted process handle and native owned-job termination;
it never creates a process or changes OS rights. Code files are hashed before launch;
approved artifacts/runtime must remain immutable and enforcement must address TOCTOU.

## Wire, preflight and accounting

Bootstrap is at most 2,000,000 bytes; subsequent record/control lines at most 32,768;
worker replies at most 262,144. UTF-8 decode is strict, surrogate/nonfinite/duplicate/
extra keys are rejected, JSON depth is bounded and oversized data is rejected before
schema parsing. Sessions/sequences/RPC counters and run/record/hash/model pins must
match. Fields have strict enums/types, finite counters and bounded collections.

Only init accepts a preapproved bootstrap. Artifact root paths within those approved
model configs must equal the exact launch policy artifact root. Subsequent commands
contain a single opaque split_id=inference LogRecord, or a bounded control/preflight
seal. There is no request field for paths, module names, arbitrary environment,
provider secrets, custody, gold, provenance or code. The child retains preflight IDs/
input hashes, seals their canonical population digest and refuses prediction for any
other record/hash. It receives original decoded Unicode text; offsets stay codepoints.

The child calls RemoteLedger, not SQLite. Parent authorizes each reserve atomically
through its existing ledger API, permits at most the policy's initial plus one retry,
and brokers reconciliation. The existing AttemptController still owns retry rules.
Only an authenticated parent's actual first reserve BudgetExceeded, with no approved
physical request, can propagate as unattempted. Budget rejection is cached for the
session. A sent/uncertain call, timeout/crash or rejected retry becomes failed/cancelled
Prediction with unresolved liability. Ledger errors never silently reopen a call.

Child cash claims never release parent liability without a parent receipt verifier.
Attempt events contain IDs, input hash, fixed enums, offsets/usage counters and timings
only. Parent attributes events to current reservations and its own reconciliation
facts, emits conservative value-free events for uncertain calls, and preserves unknown
liability if worker/sink/ledger fails. Worker prints/stderr are discarded; direct native
stdout noise fails strict parsing and is never logged as an exception/response body.

Each exchange has a bounded deadline and the native job must enforce idle lifetime.
Cancel retires the session, terminates only its owned job tree and conservatively
reconciles outstanding reservations. cleanup_status=cleanup_unverified means cleanup
could not be confirmed; no process-termination or OS-isolation success is implied.
No polling/watcher is installed. The sealed session caches logical outcomes; cache
replay is never a timing sample. D7 owns separate authorized fresh-controller timing
passes against an approved warmed backend.

CLI `--worker` is the pipe-service entrypoint for the verified native launcher, not
a standalone custody/isolation certification. The fixed source factory implements
active-only regex/local/frontier construction; frontier needs actual trusted-host
counter/provider/credential qualification. It cannot be selected via an
arbitrary module/path on the wire. Missing vendor/native dependencies return explicit
unavailable errors, never fake four-arm results. No worker, model, provider, database,
native enforcement or CLI journey has been executed during construction.
See `docs/worker-host.md` for concrete Windows creation, D4 managed context leases
and the side-effect-free native-host definition CLI.
