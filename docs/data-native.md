# Windows read-only enforcement qualification

This is SOURCE for future qualification, not a qualified machine or tested OS
sandbox. No native probe, target process, token, ACL, job, account or permission was
inspected/created/modified during Dirty Mode construction. Validation and imports
never load a Windows DLL or start a worker. No model, provider, deployment or spend
authority is implied.

## Two phases and exact bindings

`WindowsIsolationVerifier(filesystem,profile,evidence,verify_receipt=...,
control_verifier=...)` implements D4's shared-profile prelaunch Protocol. It verifies
canonical P via D6 `worker_profile_digest`, authenticated current prepared-control
and WindowsPolicyEvidence receipts, exact capability/request/filesystem bindings
and the current descriptor closure. It requires no running worker and makes no
claim about the rights of a future process.

`WindowsWorkerProcessVerifier(filesystem,profile,approvals,verify_receipt=...,
control_verifier=...)` implements D6's exact postlaunch
`verify(pid,start_identity,spec,verified_isolation,policy)->bool`. It calls D6's
canonical `validate_worker_membership` and `launch_spec`; shared profile P is
different from full per-arm launch digest L. Member hashes exclude ONLY
`profile_sha256`, full L includes P. No hashing algorithm is copied into D4.

`WindowsProcessApproval/v1` authenticates one exact externally authorized PID,
creation FILETIME (decimal count of 100 ns ticks since Windows epoch), approved
image/entrypoint hashes, P, full L, bootstrap, capability/root policy, exact
worker/custodian SID, token ID/modified ID, handle count, descriptor closure and
process-control evidence/expiry. A policy-shaped JSON is not permission to inspect
an arbitrary PID. The trusted issuer must authenticate that exact approval before
`OpenProcess` is reached. Neither current/newest process lookup nor PID-only reuse
is supported. The launcher must supply the same FILETIME convention.

Capability `enforcement_evidence_sha256` points to independent prepared-control
evidence, not to WindowsPolicyEvidence's own digest. Supplemental policy evidence
can then bind the capability digest without a hash cycle. No full launch hashes
are placed inside profile contents.

## Read-only native source

The lazy ctypes backend uses `OpenProcess(QUERY_LIMITED_INFORMATION)`,
`QueryFullProcessImageNameW`, `GetProcessTimes`, `GetExitCodeProcess`,
`GetProcessHandleCount`, `OpenProcessToken(QUERY|DUPLICATE)`, `GetTokenInformation`,
`GetNamedSecurityInfoW` and `AccessCheck`. It opens query handles only. AccessCheck
needs an impersonation token; `DuplicateToken` creates a temporary check token
which is never applied to a thread/process, elevated, or used to launch anything.
All allocated descriptors/handles are released. No AdjustTokenPrivileges,
SetSecurityInfo, account creation, process launch/kill, ACL edits, credential reads
or policy application exist in this adapter.

It rejects elevated/UIAccess, service/system/custodian identity, enabled admin
groups, missing restrictions/restricting SIDs, integrity above low and held
privileges beyond SeChangeNotifyPrivilege (including disabled-but-enableable
privileges). AppContainer tokens are explicitly unsupported by this bounded
classic-restricted-token implementation. Job membership is queried but is never
called proof of a particular job or its limits.

Every descendant of raw/evaluator/training/inference/artifact/scratch roots is
checked, bounded at 10,000 objects. Private/evaluator/training read/list and mutation
bits must be denied separately (not as a combined request which could hide a
granted read). Inference/artifacts must be readable and immutable to the worker;
scratch is explicitly disjoint/writable without ACL/owner control. Sensitive-root
ancestors cannot grant DELETE_CHILD/WRITE_DAC/WRITE_OWNER escape. Approved image
and entrypoint bytes/ACLs are checked separately. Paths reject traversal,
reparse/junction/symlink and hardlink ambiguity using D4's canonical path policy.

The descriptor commitment is the canonical set of `(role,is_directory,descriptor
SHA256)` across a complete scan. It does not emit filenames, raw descriptors,
individual SID hashes or source values. New protected journal files with an
identical ACL need no different profile; each actual descendant is still checked.
Self-relative descriptors are committed, never absolute memory pointers. Token
and process identity/handle count are rechecked before returning an observation.

Supported DACLs contain only standard allow/deny ACEs. Conditional/object-specific
ACL forms, ambiguous labels, unsupported mandatory read/execute-up restrictions,
uninspectable descriptors, excessive inventory, process/token changes and denied
query access fail closed. For supported integrity policy, unlabeled objects are
treated as medium and no-write-up is applied in addition to native DACL checks.
ABI/layout and Windows access behavior remain unexecuted, not asserted passed.

## Mandatory real host evidence

`WindowsControlVerifier` is required. `verify_policy(...)` confirms actual current
preprovisioned native controls for shared P. `verify_process(approval,observation,
spec,policy)` confirms the exact owned job/limits, inherited handle inventory,
sanitized environment, network restrictions, descendant/lifetime restrictions,
approved code/runtime closure and resistance to mutation/races for this P+L/PID.
The supported read-only APIs above cannot independently establish all those facts.
No implementation is supplied that substitutes a job flag, handle count, same-user
path names, a receipt-shaped flag or a subprocess for actual enforcement. Missing
or unverifiable host controls return false. The operating host must supply real
native-backed evidence and current issuer/revocation checks; this adapter neither
provisions nor invents it. A quiescent exact process/handle snapshot may be needed;
volatile handles or ACL inventory changes require requalification, never a bypass.

Return values are fixed reason enums, numeric counts, opaque token/process IDs and
aggregate commitments only. Raw SID/ACL/path/exception bodies are discarded. A
`qualified_snapshot` can only result from future activated native observation plus
the mandatory host checks. It issues no capability, reviewer verdict or experiment
acceptance, and expires operationally with the bound authorization/control state.

## Future operator entrypoints, not run

`python tools/data/qualify_native.py` defaults to validation only and reports missing
inputs without any native query. With `--profile <P.json> --policy <L.json>
--approval <private-process-approval.json> --pid <exact-id>
--start-identity <creation-filetime>` it validates shape/membership, still no probe.

Native inspection additionally requires `--activate` through the already authorized
host entrypoint `qualify_native.main(host=...)`. Host has an existing `guard` and
`process_verifier`; there is no arbitrary plugin loader or automatically trusted
approval file. Standalone activation fails with `trusted_native_host_required`.
The adapter never creates/locates/starts a target. Non-Windows, missing/inconsistent
approval, unsupported access policy and inaccessible processes fail closed with
value-free results. Actual qualification is outside this Dirty Mode grant.

## Concrete native job/control qualifier

`ReadOnlyWindowsControlVerifier(control_policy, context_provider, external_observer,
profile=profile, verify_receipt=authority)` is the reference WindowsControlVerifier
implementation. It uses D6's canonical shared-profile/member/full-launch helpers
and implements the existing `verify_policy`/`verify_process` signatures. Imports,
construction and the default qualification methods never query native state.
No native queries, contexts, jobs, processes or handle duplicates were created in
this source construction.

Prepared policy qualification leases a real approved empty prepared job, checks
its native applied limits and current native-host observations, and never requires
a running worker. This prepared job qualifies a native creation context/template;
it does not prove membership of a later worker. Exact process qualification then
leases that launch's actual job/process/handle references and queries
`IsProcessInJob(process,exact_job)`, the job PID list, limits and mitigations.

`WindowsControlPolicy/v1` explicitly binds P and the filesystem policy. The baseline
requires kill-on-last-job-close, active-process limit one, no breakaway and child
process restriction. Memory/user-CPU-time/CPU-rate/UI limits are optional declared
receipt scope: if requested, their actual flag/value must enforce that bound; if
None, no enforcement of that optional resource is claimed. Thus D6's existing
0x2008 job baseline is not silently replaced by invented mandatory memory/CPU
settings. Unsupported flags/modes/query results fail closed. CPU hard caps are
distinguished from weight/audit modes; process user CPU time is not wall lifetime.
Wall lifetime still needs real host observation of the owner timer/watchdog.

The qualifier supports the declared child, strict-handle, extension-point and
image-load mitigation flag structures only. Child creation restriction is required;
secure-child override is rejected. Optional strict-handle checking, if requested,
must be permanently enabled. It never sets a mitigation. The exact borrowed
process lease must grant limited query and DUP_HANDLE. Mitigation queries use a
separate temporary QUERY_INFORMATION handle to the exact approved PID, checked for
the same kernel object and creation FILETIME before use. It is closed by the
qualifier; the lease is never widened or changed. If ordinary query access is
unavailable, qualification blocks without elevation or rights repair.

`NativeControlContextProvider.lease_prepared(P)` and
`.lease_process(pid,start_identity,L)` return context managers yielding
`BorrowedNativeContext`. Its NativeContextBinding authenticates context identity,
P, control/root-policy commitments and stage; the process stage also includes exact
PID/FILETIME/L/bootstrap. Numeric handles remain private in memory, never JSON or
worker wire. D6 owns all resources and their lifetimes; the provider stabilizes
them for the complete query lease. Missing or ambiguous context fails closed.

`BorrowedContextRegistry` is an optional borrow-only adapter for a D6 application
host. Register only actual created contexts with authenticated origin/binding,
then lease them to the qualifier. Registration is metadata, never proof of native
enforcement. Retire registration before the owner's cleanup closes handles; active
leases block retirement, including reentrant retirement. No ID can be reused.
The registry itself never creates/closes/terminates an OS resource. Existing D6
registries can instead implement the Protocol directly; there is no second native
resource owner or hidden process discovery.

`D6WindowsContextProvider(prepared_lease, verify_receipt=...)` is the concrete bridge
to D6's public `PreparedWindowsProcess`. The trusted
WindowsLaunchHost.prepare_suspended callback registers authenticated binding plus
the ACTUAL returned descriptor via `register_suspended`. `launcher_context_id`
binds its original native context; per-process lease identity separately binds
PID/start/P/L/bootstrap. `lease_process` enters that descriptor's public
`lease_handles()` each time, maps BorrowedWindowsHandles.process_handle/job_handle/
stdio_expected/child_handle_values to the qualifier contract, and releases through
D6's own context manager. No copied handle is cached beyond its lease. D6 alone
closes those query copies. Retire process metadata before owner cleanup; no PID or
context is discovered from ambient machine state. A real prepared-context lease
provider is still required and is independent of a running worker.

Three NativeHandleBinding entries describe child-side stdin/stdout/stderr. D6 must
retain noninheritable local references to the exact child-side objects before
closing initial launch handles; opposite parent pipe endpoints are not suitable
identity references. The qualifier duplicates each approved child handle into its
own process with SAME_ACCESS and NEVER CLOSE_SOURCE, compares kernel-object
identity using CompareObjectHandles, checks noninheritability/type and closes only
the duplicate it created. It does not consume pipe bytes or alter shared offsets,
flags or borrowed handles. This checks the standard objects, not the complete
child handle table; complete safe inventory remains an explicit external fact.

`NativeExternalObservationProvider.observe_prepared/observe_process` must perform
actual current authorized native observations and return an authenticated
ExternalControlObservation. Each observation binds exact context and control
policy, has bounded freshness/expiry, and includes the closed stage-specific fact
set. Process facts cover exact environment, network enforcement, complete child
handle inventory, wall lifetime, runtime/code closure, race protection and actual
context-handle ownership. Prepared observations replace process environment/
inventory with prepared token/namespace facts; no future process proof is inferred.
No raw process credentials/environment secrets or unrelated process access is
permitted. If a fact cannot be safely observed, return unknown/unsupported. A
declared environment/network policy or a signed shaped flag is insufficient.

Every observation and observed fact's evidence is issuer/revocation authenticated;
missing, duplicate, stale, unsupported or unknown required facts block qualification.
Supported facts and opaque snapshot commitments are reported separately from
unknown facts. Job limits, process identity and mitigations are rechecked after
external observations. The report issues no authority or independent verdict.
Exceptions have fixed enums; a failing external lease may leave query-attempt
status null rather than falsely reporting no host observation.

Future `python tools/data/qualify_controls.py --policy <private-policy.json>` is
validation only. Later explicit `--activate --stage prepared` requires trusted host
policy_evidence/capability/request/profile/control_verifier; process stage also
requires exact `--pid`/`--start-identity`, original process approval, native
observation, launch spec and exact policy. The entrypoint is
`qualify_controls.main(host=already_approved_host)`. No plugin loader, process lookup,
host provisioning or permissive fallback exists. ABI, leases, query rights and all
native/worker effects remain unexecuted and require later authorized validation.

Additional primary references: [QueryInformationJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject),
[extended limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information),
[CPU rate](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_cpu_rate_control_information),
[GetProcessMitigationPolicy](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocessmitigationpolicy),
[GetHandleInformation](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-gethandleinformation),
[DuplicateHandle](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle) and
[CompareObjectHandles](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-compareobjecthandles).

## Token/process/ACL API references

- [AccessCheck](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-accesscheck) and [DuplicateToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-duplicatetoken): mapped rights and impersonation-token requirements.
- [GetTokenInformation](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-gettokeninformation) and [TOKEN_STATISTICS](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-token_statistics): query permissions and token mutation identity.
- [GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes): exact creation identity.
- [GetNamedSecurityInfoW](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getnamedsecurityinfow), [MakeSelfRelativeSD](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-makeselfrelativesd), [file access](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights): descriptor ownership, serialization and per-child ACLs.
- [Mandatory Integrity Control](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control) and [privilege constants](https://learn.microsoft.com/en-us/windows/win32/secauthz/privilege-constants): additional restrictions and bypass privileges.
- [IsProcessInJob](https://learn.microsoft.com/en-us/windows/win32/api/jobapi/nf-jobapi-isprocessinjob): NULL job handle tests any-job membership only.
