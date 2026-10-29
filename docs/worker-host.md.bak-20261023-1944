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
