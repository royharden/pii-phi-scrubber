# Windows worker host source — runtime unverified

`m7.providers.native_launcher.WindowsIsolatedLauncher` implements future native
creation; `native_launch_api` contains lazy Win32 bindings. Construction/validation
never constructs Win32LaunchApi, inspects a token or creates a process/job. No native path
has run. Definition-only CLI: `python scripts/infer.py --validate-native-host
--context-approval <json> --policy <json> --profile <json>`. It reads bounded strict
JSON and reports native_operations_performed/actual_token_verified/authority_issued
as false. No token-handle, password or provider-key CLI argument exists.

The host supplies PreprovisionedWindowsContext: an explicit BORROWED primary-token
handle and authenticated NativeLaunchApproval binding P/L/bootstrap/capability/root
policy plus token/current-caller-privilege/resource receipt digests and validity.
D6 never discovers/logs/serializes/closes that borrowed handle. No account creation,
logon, credential lookup, privilege adjustment, ACL provisioning or same-user
subprocess fallback exists. Missing rights/session/context causes unavailable.

`WindowsIsolatedLauncher(context,policy,profile,*,isolation_guard,host,
process_verifier,allow_execution=False)` implements `launch(spec,VerifiedIsolation,
timeout=...)`. WindowsLaunchHost.verify_context must inspect the actual prepared
restricted nonadmin low-integrity token, namespace/network/session rights and
already-enabled caller privileges. Mandatory receipt kinds are native_launch_context,
native_launch_token, native_launch_caller_privileges and native_launch_resources.
A receipt-shaped flag alone cannot establish these facts.

The adapter duplicates only that approved token, creates a new anonymous one-process
kill-on-close job and stdio pipes/NUL stderr, and starts the child suspended. Explicit
startup attributes inherit exactly three child-side handles, assign the job AT
CREATION and restrict descendants. The environment is the sanitized launch_spec
allowlist; image/arguments/cwd are exact approved local values, with no shell.
Nothing attaches to or mutates an unrelated existing process/job.
The [isolated `-I` interpreter](https://docs.python.org/3.12/using/cmdline.html#cmdoption-I)
omits the script directory from its search path;
infer.py derives and adds only its own pinned scripts directory before _common.
It never adds cwd, PYTHONPATH or a wire-provided directory to recover imports.

Actual creation FILETIME supplies start_identity. PreparedWindowsProcess exposes
pid/start/P/L/bootstrap/context ID and managed lease_handles(). The host's
prepare_suspended must publish REAL exact-process/native-control approval for D4's
WindowsWorkerProcessVerifier, which runs before ResumeThread. The parent session
rechecks the running process before messages; no static approval is assumed to
remain valid as Python/model loading changes native state.

`OwnedWindowsContextProvider(profile,control_policy_sha256,filesystem_policy_sha256,
*,prepared_lease,verify_receipt)` implements D4's NativeControlContextProvider.
register_process(prepared,binding,policy) authenticates exact P/L/PID/start/bootstrap;
lease_process(pid,start,L) yields query copies of the owned process/job and retained
references to the EXACT CHILD-SIDE stdin/stdout/NUL kernel objects. Opposite parent
pipe endpoints are never expected objects. D4 closes no originals. D6 owns/closes
its query duplicates after each lease. lease_prepared(P) borrows an externally owned,
preprovisioned EMPTY prepared-job context; D6 never attaches or modifies it. Every
new running worker job receives separate actual process qualification.

Host wiring requires `ReadOnlyWindowsControlVerifier(...,profile=profile,
verify_receipt=authority)` with this provider and a mandatory actual external
observer. Use it for D4 WindowsIsolationVerifier (prepared P) and
WindowsWorkerProcessVerifier (exact PID/start/P/L). Unknown environment, network,
complete handle inventory, runtime closure, lifetime or race facts block qualification.
Prepared-profile checks never require a running worker. No positive observer or
dynamic signed process approval is fabricated by this package.

An owned unnamed waitable timer and one blocking native wait enforce startup/lifetime;
kill-on-job-close protects host failure. Cleanup terminates only the owned job and
closes only newly created/duplicated handles, never borrowed originals/pseudo handles.
Unconfirmed cleanup/observer leases remain cleanup_unverified; uncertain billing
stays in the parent ledger. The native creator sets one-process/kill-on-close/child-
process controls. Additional requested memory/CPU/UI/mitigation controls it does not
set must fail actual host qualification, never be claimed present. Unsupported
platform/job nesting/privilege contexts fail without a fallback.

## Worker compute telemetry and parent accounting

The child ledger proxy accepts `RemoteLedger.reconcile(..., compute_seconds=...)`.
It carries the value in the optional `ReconcileRequest.compute_seconds` wire field;
the parent `WorkerSession` broker forwards it to its `ReservationLedger.reconcile`.
Legacy omission and explicit JSON `null` mean unknown compute time. Numeric zero
means a known zero time proxy. Supplied numbers must be finite and in the inclusive
range 0 to 1,000,000,000 seconds; booleans, numeric strings, negative or nonfinite
values and values above that bound are rejected by the strict wire schema. See the
[wire contract](../contracts/adapters/worker-wire.md) for the accounting boundary.

This worker-reported operation wall time is a compute proxy. It does not attest
native process activity, CPU/GPU consumption, warm timing qualification or economic
cost. Unknown compute must remain distinct from measured zero. The parent ledger
stores known seconds and unknown-attempt counts separately under its existing
reconciliation and replay/conflict rules.

The host's `reconcile_verifier` remains the only route for authenticating actual
cash and receipt identity: the parent requires a matching `CashReceipt`. A known
compute value never makes child cash claims trustworthy or clears unresolved
liability. Missing/invalid cash evidence preserves the reservation's unresolved
liability, independently of compute telemetry. No new path, credential, custody or
gold access, process authority, or execution permission is added by this field.
This contract describes source behavior; it does not establish real worker/native,
provider or model execution.

## Fixed worker runtime

`FixedWorkerFactory(frontier_runtime=None)` is fixed application source for all arms.
Only the active adapter and RemoteLedger are constructed. Fine's immutable base
configuration is parity metadata only: no inactive path read/probe/loader/registry/
preflight. D5's accepted active-only equality fix in worker.py is retained; locked
configs are not rewritten and OS scope remains the active artifact root.

QualifiedFrontierRuntime supplies an approved ACTUAL TokenCounter, in-memory
credential callable, FrontierWorkerQualification and mandatory FrontierRuntimeVerifier.
Qualification binds model/run/config/provider/terms/counter/factory-source hash with
expiry and authenticated runtime/counter/credential-boundary receipts. The transport
is fixed HttpsChatTransport. No guessed token/framing counts, default provider,
auto-download, auth-file/environment key reader or wire-selected plugin/import exists.
Unsupported counter/provider/credential qualification is explicitly unavailable.

The default CLI worker calls the fixed factory without a frontier runtime; frontier
therefore remains unavailable until an approved FIXED source entrypoint supplies
serve_worker(...,registry_factory=FixedWorkerFactory(runtime)) through the trusted
host boundary. Runtime/credential objects are not pickled or sent on the record wire,
command line or inherited arbitrary environment. A real provider/key is not selected
by source construction. Definition validation does not authenticate such a runtime.

Read-only primary references used for independently written API bindings:

- [CreateProcessAsUserW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasuserw): explicit token and privilege prerequisites; no logon fallback is used here.
- [Startup attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute): explicit inherited handle/job/descendant attributes.
- [Job limits](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-setinformationjobobject) and [extended layout](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information).
- [DuplicateTokenEx](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-duplicatetokenex) and [redirected stdio](https://learn.microsoft.com/en-us/windows/win32/procthread/creating-a-child-process-with-redirected-input-and-output).
- [Waitable timer](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createwaitabletimerw), [ResumeThread](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-resumethread), [Microsoft SDK header metadata](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/WinBase.h).

Later activation must verify native ABI/handle/thread/timer/privilege/cleanup/race
behavior and actual qualified provider/model/tokenizer semantics. No native probe,
worker/model/provider call, test, DB/service, rights change, environment setup or
independent verdict has occurred. Source and receipts alone are not product acceptance.

## Explicit retained-backend timing continuation

`WorkerBootstrap.timing_plan_sha256` and `timing_order_sha256` are an optional paired preregistration. Both default null (primary-only). D5 must set these before calculating bootstrap/member/P/L/edition pins. Do not insert a plan or mutate a locked launch after primary access. D7's pure plan avoids cycles through those later hashes.

`launch_worker(..., warm_attestor=..., timing_authority=None)` retains the original session. `WarmBackendAttestor(claim: dict, physical_calls: int) -> str` receives a value-free JSON-compatible identity claim and activity count, and must return a genuinely authenticated `warm_backend_attestation` digest based on actual original process/backend observation. Child testimony alone, a hash of it, or an approval-shaped boolean is insufficient. No default observer/attestation is supplied. Local identities require the original loaded backend and prior physical entry; frontier identities mean the original client/transport/counter only. Provider server warmth and startup remain unknown.

After primary terminal accounting, D7 gathers only surviving `session.timing_identity()` values, builds its authenticated continuation authority, and calls `session.bind_timing_authority(authority)` once (or injects that same deferred authority at original launch). D7 calls durable `authorize(request)` BEFORE `begin_timing_phase(request, permit)`. D6 calls `current`, never `authorize` or `finish` on that authority; D7 owns consume/completion/abort. Receipt kinds are `timing_custody_continuation` and `timing_resource_receipt`. Missing authority/attestor/receipts is unavailable. The host must wire these callbacks through its own public constructors; this module cannot approve itself.

The exact D7 `WarmTimingSession` methods are implemented by `WorkerSession`: identity, begin, predict, finish. Identity binds original PID/creation identity, canonical P/full L/bootstrap, model/config/artifact, sealed population and original terminal order. Negative primary outputs may remain terminal; there is no all-success prerequisite. Missing, dead, unsupported or cold workers cannot be replaced to satisfy a warm identity. D7 retains all four intended arms and reports unavailable cells for missing workers.

Only three sequential single-concurrency passes over the same original codepoint-exact IDs/hashes/order are accepted. Each begin burns its namespace before a bounded wire reset; uncertainty terminates the owned session and cannot retry/reset/resume. Only the logical prediction caches and AttemptController change. The loaded backend, active root, package/config/decoder pins, original ledgers, all issued physical IDs, settled reservations and unknown liabilities survive. Physical IDs are `t-<full phase digest>-<fresh UUID>`; no reservation is transferred or reused. BudgetExceeded still means only an actual first-reserve denial before any physical call. Denied retries/uncertain sent calls remain failed with liability.

Native/current continuation checks precede messages, records and new reservations. Existing byte, record, retry, token, response, timeout, lifetime, expiry and cancellation bounds apply unchanged. Wire commands carry only strict phase request/permit identities, never gold/custody/ledger paths, plugins or import selectors. Regex timing emits fresh value-free attempt metadata without inventing measured cash; frontier transport retains network labels. D7 owns validation/rendering measurement and separate control/scoring overhead. This source has not run a phase, worker, native probe or model/provider call.
D4-F receipt bridge: the bound continuation authority must additionally expose `verify_receipt(kind,digest)` as canonical `CustodyTimingAuthority` does. D6 authenticates its original custody-chain consumption through that bridge. Do not recursively feed it into lifecycle/native IsolationGuard verification; native/current guard remains independent.
As-built D7 bridge: `begin_timing_phase(request, permit, verify_receipt=authority.verify_receipt)` directly supplies the canonical live D4 receipt verifier; `bind_timing_authority` is optional on this path. The callback is retained only in the parent and rechecked before phase messages, records and reserves. Canonical D4 verification of the consumed custody receipt invokes `current(request,permit)`, including current native/revocation/expiry/cash checks. A static receipt lookup is insufficient. The callback never crosses the child wire or replaces the independent lifecycle verifier.

## Host composition root (`m7.host`) - runtime unverified

`m7.host` is inert wiring, not a trust service. An operator supplies `HostServices`:
the external receipt verifier, `WindowsLaunchHost`, one preprovisioned launch context
per worker arm in `bundle.campaign.launch_policies` (all of them, including regex),
the three model-arm `ReservationLedger`s, `training_summary`, and for timing
the `WarmBackendAttestor` and signed cash snapshot provider. The operator also builds
`CustodyFilesystem`/`IsolationGuard` (optionally via `build_custody`) and a
`WindowsWorkerProcessVerifier` over that same filesystem instance; the root refuses
a different filesystem object because the timing process guard would.
`build_campaign_host(services, bundle, timing_authorizations=None)` returns an
`IsolatedCampaignHost` whose single launcher routes each exact launch spec to the one
per-arm `WindowsIsolatedLauncher` built for it (any other spec is `permit_required`).
`build_operator_host` and `build_training_host` return `OperatorHost` and
`CampaignHost` over the same verifier and guard. Construction reads no files and
starts nothing; `experiment.campaign` and `data.timing_native` checks still decide.
The operator's `--operator-host` factory `(bundle, edition)` typically returns
`build_campaign_host(services, bundle)` over services it constructed.

`m7.host.unavailable` is the shipped refusing host. Its factories always raise
`HostUnavailable`, so `scripts/eval.py --operator-host m7.host.unavailable:campaign_host`
(or `:operator_host` for locked execution) and
`scripts/train.py campaign --training-host m7.host.unavailable:training_host ...` report
`status: unavailable` (exit 3). No allow-all or development verifier exists. Frontier,
local-loader and training-engine injection through the host is not provided.
