"""Concrete query-only WindowsControlVerifier joined to leased launcher context."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from .access import _time
from .filesystem import checked_path
from .native_controls_models import (
    ControlQualificationReport, ExternalControlObservation, NativeControlContextProvider,
    NativeExternalObservationProvider, WindowsControlPolicy,
)
from .provenance import commitment

PREPARED_FACTS = frozenset(('prepared_token_policy', 'prepared_namespace_policy', 'network_enforced',
                          'lifetime_enforced', 'runtime_code_closure', 'race_protection', 'context_handle_ownership'))
PROCESS_FACTS = frozenset(('environment_exact', 'network_enforced', 'complete_child_handle_inventory',
                         'lifetime_enforced', 'runtime_code_closure', 'race_protection', 'context_handle_ownership'))


def _need(value: bool) -> None:
    if not value:
        raise ValueError('native_control_qualification_failed')


class ReadOnlyWindowsControlVerifier:
    """Does not create, provision, apply, resume, terminate or close host resources.

    Providers lease stable authorized application-owned context and perform real
    current external observations. No ordinary-Popen/name/JSON/true fallback exists.
    """
    def __init__(self, policy: WindowsControlPolicy, context_provider: NativeControlContextProvider,
                 external_observer: NativeExternalObservationProvider, *, profile,
                 verify_receipt: Callable[[str, str], bool]):
        self.policy, self.context_provider, self.external_observer = policy, context_provider, external_observer
        self.verify_receipt = verify_receipt
        self.profile = profile
        self.last_report = ControlQualificationReport(status='validation_only', stage='prepared',
                                                      unknown_facts=('native_activation_not_requested',))

    def _auth(self, kind: str, digest: str) -> None:
        _need(self.verify_receipt(kind, digest) is True)

    def _binding(self, context, stage: str, *, profile_sha256: str):
        from .native_controls_models import NativeContextBinding
        binding = NativeContextBinding.model_validate_json(context.binding.model_dump_json())
        policy = WindowsControlPolicy.model_validate_json(self.policy.model_dump_json())
        _need(binding.stage == stage and binding.profile_sha256 == profile_sha256 == policy.profile_sha256
            and binding.control_policy_sha256 == commitment(policy)
            and binding.filesystem_policy_sha256 == policy.filesystem_policy_sha256)
        self._auth('windows_control_policy', commitment(policy))
        self._auth('native_context_authority', binding.context_authority_sha256)
        self._auth('native_context_binding', commitment(binding))
        return binding

    def _job(self, api, context, *, pid: int | None):
        snapshot = api.job_snapshot(context.job_handle)
        policy = self.policy
        required = 0x2000 | 0x8  # D6's required close-kill / one-process boundary.
        supported = required | 0x100 | 0x200 | 0x2 | 0x400
        _need(snapshot['limit_flags'] & required == required and not snapshot['limit_flags'] & ~supported
            and not snapshot['limit_flags'] & (0x800 | 0x1000)
            and snapshot['active_process_limit'] == 1
            and snapshot['cpu_control_flags'] in (0, 5)  # Disabled or ENABLE|HARD_CAP.
            and not snapshot['ui_restrictions'] & ~255
            and snapshot['pids'] == (() if pid is None else (pid,)))
        # Only explicitly approved/requested resource bounds are required; None
        # means outside this receipt's scope, never a claim that a limit is set.
        for field, flag in (('process_memory_limit', 0x100), ('job_memory_limit', 0x200), ('process_user_time_100ns', 0x2)):
            requested = getattr(policy, field)
            if snapshot['limit_flags'] & flag:
                _need(snapshot[field] > 0)
            if requested is not None:
                _need(snapshot['limit_flags'] & flag and 0 < snapshot[field] <= requested)
        if snapshot['cpu_control_flags'] == 5:
            _need(0 < snapshot['cpu_rate_hundredths'] <= 10000)
        if policy.cpu_rate_hundredths is not None:
            _need(snapshot['cpu_control_flags'] == 5 and 0 < snapshot['cpu_rate_hundredths'] <= policy.cpu_rate_hundredths)
        if policy.ui_restrictions is not None:
            _need(snapshot['ui_restrictions'] & policy.ui_restrictions == policy.ui_restrictions)
        return snapshot

    def _external(self, context, observation: ExternalControlObservation, required: frozenset[str]):
        observation = ExternalControlObservation.model_validate_json(observation.model_dump_json())
        point = datetime.now(timezone.utc)
        _need(observation.context_binding_sha256 == commitment(context.binding)
            and observation.control_policy_sha256 == commitment(self.policy)
            and _time(observation.observed_at) <= point < _time(observation.expires_at)
            and (point - _time(observation.observed_at)).total_seconds() <= self.policy.max_external_age_seconds)
        facts = {fact.name: fact for fact in observation.facts}
        _need(len(facts) == len(observation.facts) and set(facts) == required)
        self._auth('native_external_observation', commitment(observation))
        unknown = []
        for name in sorted(required):
            fact = facts[name]
            if fact.status != 'observed' or fact.evidence_sha256 is None:
                unknown.append(name)
            else:
                self._auth('native_external_' + name, fact.evidence_sha256)
        return observation, tuple(unknown)

    def verify_policy(self, evidence, capability, request, profile) -> bool:
        return self.qualify_policy(evidence, capability, request, profile,
                                   allow_native_queries=True).status == 'qualified_snapshot'

    def qualify_policy(self, evidence, capability, request, profile, *, allow_native_queries: bool = False):
        if not allow_native_queries:
            return ControlQualificationReport(status='validation_only', stage='prepared',
                                               unknown_facts=('native_activation_not_requested',))
        attempted, binding_sha = False, None
        try:
            from m7.providers.worker_profile import worker_profile_digest
            from .native_job_api import Win32ControlReadOnly
            profile_sha = worker_profile_digest(profile)
            _need(profile_sha == request.worker_policy_sha256 == self.policy.profile_sha256
                and profile_sha == worker_profile_digest(self.profile)
                and evidence.profile_sha256 == profile_sha
                and evidence.capability_sha256 == commitment(capability)
                and evidence.request_sha256 == commitment(request)
                and capability.enforcement_evidence_sha256 == evidence.prepared_controls_sha256
                and request.filesystem_policy_sha256 == self.policy.filesystem_policy_sha256)
            point = datetime.now(timezone.utc)
            _need(_time(evidence.issued_at) <= point < _time(evidence.expires_at)
                and _time(capability.issued_at) <= point < _time(capability.expires_at))
            self._auth('windows_policy_qualification', commitment(evidence))
            self._auth('isolation_capability', commitment(capability))
            self._auth('platform_isolation_enforcement', capability.enforcement_evidence_sha256)
            self._auth('worker_profile_approval', profile_sha)
            self._auth('windows_prepared_controls', evidence.prepared_controls_sha256)
            attempted = None  # A failing external lease may itself have queried native ownership.
            with self.context_provider.lease_prepared(profile_sha) as context:
                binding = self._binding(context, 'prepared', profile_sha256=profile_sha)
                binding_sha = commitment(binding)
                _need(context.process_handle is None and not context.inherited_handles)
                api = Win32ControlReadOnly()
                attempted = True
                before = self._job(api, context, pid=None)
                external, unknown = self._external(context,
                    self.external_observer.observe_prepared(context, self.policy, evidence), PREPARED_FACTS)
                _need(self._job(api, context, pid=None) == before)
                self.last_report = ControlQualificationReport(status='unqualified' if unknown else 'qualified_snapshot',
                    stage='prepared', profile_sha256=profile_sha, context_binding_sha256=binding_sha,
                    native_snapshot_sha256=commitment(before), external_observation_sha256=commitment(external),
                    supported_facts=('prepared_exact_job_limits', 'prepared_job_empty'), unknown_facts=unknown,
                    native_queries_attempted=True)
        except Exception:
            self.last_report = ControlQualificationReport(status='unqualified', stage='prepared',
                context_binding_sha256=binding_sha, unknown_facts=('prepared_native_control_unavailable',),
                native_queries_attempted=attempted)
        return self.last_report

    def verify_process(self, approval, observation, spec, policy) -> bool:
        return self.qualify_process(approval, observation, spec, policy,
                                    allow_native_queries=True).status == 'qualified_snapshot'

    def qualify_process(self, approval, observation, spec, policy, *, allow_native_queries: bool = False):
        if not allow_native_queries:
            return ControlQualificationReport(status='validation_only', stage='process',
                                               unknown_facts=('native_activation_not_requested',))
        attempted, binding_sha = False, None
        try:
            from m7.providers.worker_profile import validate_worker_membership
            from m7.providers.worker_transport import launch_spec
            from .native_job_api import Win32ControlReadOnly
            from .native_windows_models import WindowsProcessApproval, NativeObservation
            approval = WindowsProcessApproval.model_validate_json(approval.model_dump_json())
            observation = NativeObservation.model_validate_json(observation.model_dump_json())
            membership = validate_worker_membership(self.profile, policy)
            launch_sha = membership.launch_sha256
            _need(spec == launch_spec(policy) and approval.launch_sha256 == launch_sha == observation.launch_sha256
                and approval.profile_sha256 == policy.profile_sha256 == observation.profile_sha256 == self.policy.profile_sha256
                and approval.filesystem_policy_sha256 == policy.filesystem_policy_sha256 == self.policy.filesystem_policy_sha256
                and approval.pid == observation.pid and approval.start_identity == observation.start_identity
                and approval.image_sha256 == observation.image_sha256 == policy.executable_sha256
                and policy.lifetime_seconds <= self.policy.max_wall_lifetime_seconds)
            point = datetime.now(timezone.utc)
            _need(_time(approval.issued_at) <= point < _time(approval.expires_at))
            self._auth('windows_process_qualification', commitment(approval))
            self._auth('worker_profile_approval', membership.profile_sha256)
            self._auth('windows_process_controls', approval.process_controls_sha256)
            self._auth('worker_launch_approval', launch_sha)
            attempted = None
            with self.context_provider.lease_process(approval.pid, approval.start_identity, launch_sha) as context:
                binding = self._binding(context, 'process', profile_sha256=policy.profile_sha256)
                binding_sha = commitment(binding)
                _need(binding.pid == approval.pid and binding.start_identity == approval.start_identity
                    and binding.launch_sha256 == launch_sha and binding.bootstrap_sha256 == policy.bootstrap_sha256
                    and context.process_handle is not None)
                api = Win32ControlReadOnly()
                attempted = True
                handle = context.process_handle
                _need(not api.flags(handle) & 1 and api.get_pid(handle) == approval.pid)
                identity = api.process_identity(handle)
                _need(identity[0] == approval.start_identity
                    and checked_path(identity[1]) == checked_path(policy.executable)
                    and identity[2] == observation.handle_count
                    and api.exact_job_member(handle, context.job_handle))
                before = self._job(api, context, pid=approval.pid)
                names = tuple(row.name for row in self.policy.mitigations)
                mitigations = api.mitigation_snapshot(handle, names, pid=approval.pid, start_identity=approval.start_identity)
                known = {'strict_handles': 3, 'child_process': 7, 'extension_points': 1, 'image_load': 31}
                for requirement in self.policy.mitigations:
                    actual = mitigations[requirement.name]
                    _need(not actual & ~known[requirement.name]
                        and actual & requirement.required_mask == requirement.required_mask
                        and not actual & requirement.forbidden_mask)
                _need(not mitigations['child_process'] & 4)  # No secure-child override.
                inherited = {item.role: item for item in context.inherited_handles}
                _need(len(inherited) == len(context.inherited_handles) == 3
                    and set(inherited) == {'stdin', 'stdout', 'stderr'}
                    and len({item.child_handle for item in inherited.values()}) == 3)
                for role, item in inherited.items():
                    _need(api.compare_child_handle(handle, item.child_handle, item.expected_local_handle, role))
                external, unknown = self._external(context,
                    self.external_observer.observe_process(context, self.policy, approval, spec, observation), PROCESS_FACTS)
                # Duplicates have been closed; no borrowed handle is changed/closed.
                _need(api.process_identity(handle) == identity and self._job(api, context, pid=approval.pid) == before
                    and api.mitigation_snapshot(handle, names, pid=approval.pid, start_identity=approval.start_identity) == mitigations)
                snapshot = {'job': before, 'mitigations': mitigations, 'standard_handle_objects_match': True}
                self.last_report = ControlQualificationReport(status='unqualified' if unknown else 'qualified_snapshot',
                    stage='process', profile_sha256=policy.profile_sha256, launch_sha256=launch_sha,
                    context_binding_sha256=binding_sha, native_snapshot_sha256=commitment(snapshot),
                    external_observation_sha256=commitment(external), native_queries_attempted=True,
                    supported_facts=('exact_job_membership', 'declared_job_limits', 'single_process_no_breakaway',
                                     'process_mitigations', 'standard_handle_object_identity'), unknown_facts=unknown)
        except Exception:
            self.last_report = ControlQualificationReport(status='unqualified', stage='process',
                context_binding_sha256=binding_sha, native_queries_attempted=attempted,
                unknown_facts=('exact_native_control_unavailable',))
        return self.last_report
