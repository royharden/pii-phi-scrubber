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

## Primary API references

- [AccessCheck](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-accesscheck) and [DuplicateToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-duplicatetoken): mapped rights and impersonation-token requirements.
- [GetTokenInformation](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-gettokeninformation) and [TOKEN_STATISTICS](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-token_statistics): query permissions and token mutation identity.
- [GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes): exact creation identity.
- [GetNamedSecurityInfoW](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getnamedsecurityinfow), [MakeSelfRelativeSD](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-makeselfrelativesd), [file access](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights): descriptor ownership, serialization and per-child ACLs.
- [Mandatory Integrity Control](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control) and [privilege constants](https://learn.microsoft.com/en-us/windows/win32/secauthz/privilege-constants): additional restrictions and bypass privileges.
- [IsProcessInJob](https://learn.microsoft.com/en-us/windows/win32/api/jobapi/nf-jobapi-isprocessinjob): NULL job handle tests any-job membership only.
