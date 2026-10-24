"""Inert composition root: wires existing source adapters around operator inputs.

Construction reads no files, starts no process, opens no network or edition and
calls no service. The campaign/timing checks in experiment.campaign and
data.timing_native remain authoritative; this module only satisfies them.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Mapping

from .services import HostServiceMissing, HostServices

if TYPE_CHECKING:
    from m7.training.launch_bundle import WorkerLaunchBundle


class ArmRoutingLauncher:
    """One IsolatedLauncher over per-arm WindowsIsolatedLaunchers.

    IsolatedCampaignHost.launcher is shared by all arms, while each
    WindowsIsolatedLauncher accepts only its own policy's spec. Route by exact spec
    equality to exactly one launcher; anything else is refused, never retried
    on another launcher. The chosen launcher still re-checks spec/approvals.
    """
    def __init__(self, routes: Mapping[str, tuple[object, object]]):
        if not routes:
            raise HostServiceMissing('host_service_missing:launch_routes')
        self._routes = tuple((arm, spec, launcher) for arm, (spec, launcher) in sorted(routes.items()))

    def launch(self, spec, verified_isolation, *, timeout: float):
        from m7.providers.contracts import AdapterFault
        matches = [launcher for _, expected, launcher in self._routes if expected == spec]
        if len(matches) != 1:
            raise AdapterFault('permit_required')
        return matches[0].launch(spec, verified_isolation, timeout=timeout)


def build_custody(capability, request, policy, approval, *, verify_receipt: Callable[[str, str], bool], platform_verifier):
    """Optional helper: one CustodyFilesystem and IsolationGuard from approved records.

    Build the WindowsWorkerProcessVerifier over the returned filesystem instance.
    """
    from m7.data.access import IsolationGuard
    from m7.data.filesystem import CustodyFilesystem
    filesystem = CustodyFilesystem(policy, approval, verify_receipt=verify_receipt)
    guard = IsolationGuard(capability, request, verify_receipt=verify_receipt, platform_verifier=platform_verifier)
    return filesystem, guard


def compose_timing_authority(services: HostServices, custody_authorization, resource_authorization):
    """Factory with the exact keywords experiment.campaign calls after primary sealing."""
    if custody_authorization is None or resource_authorization is None:
        raise HostServiceMissing('host_service_missing:timing_authorizations')

    def factory(*, custody, bundle, edition, primary, plan, resources, identities):
        from m7.data.timing import CustodyTimingAuthority
        from m7.data.timing_native import WindowsTimingProcessGuard
        from m7.training.timing_resources import TimingResourceAuthority
        # primary/plan/identities are checked by the authorities and campaign.py, not here.
        del primary, plan, identities
        if custody.filesystem is not services.process_verifier.filesystem:
            raise HostServiceMissing('host_service_mismatch:process_verifier.filesystem')
        guard = WindowsTimingProcessGuard(custody, services.process_verifier, bundle.campaign.launch_policies)
        options = {} if services.timing_clock is None else {'clock': services.timing_clock}
        authority = TimingResourceAuthority(bundle, resources, resource_authorization,
            verify_receipt=services.verify_receipt, snapshot_provider=services.timing_snapshot_provider, **options)
        return CustodyTimingAuthority(custody, edition, custody_authorization,
                                      resources=authority, verify_process=guard)
    return factory


def build_campaign_host(services: HostServices, bundle: WorkerLaunchBundle, *, timing_authorizations=None):
    """IsolatedCampaignHost for scripts/eval.py campaign activation.

    timing_authorizations=(CustodyTimingAuthorization, TimingResourceAuthorization)
    enables timing; omitted means primary-only (no factory, no attestor).
    """
    from m7.experiment.isolated import IsolatedCampaignHost
    from m7.providers.native_launcher import WindowsIsolatedLauncher
    from m7.providers.worker_transport import launch_spec
    timing = timing_authorizations is not None
    services.require_campaign(timing=timing)
    policies, profile = bundle.campaign.launch_policies, bundle.campaign.worker_profile
    if set(services.launch_contexts) != set(policies):
        raise HostServiceMissing('host_service_mismatch:launch_contexts')
    routes = {}
    for arm, policy in policies.items():
        # Same guard and verifier object for every arm; execution is allowed only here.
        launcher = WindowsIsolatedLauncher(services.launch_contexts[arm], policy, profile,
            isolation_guard=services.isolation_guard, host=services.launch_host,
            process_verifier=services.process_verifier, allow_execution=True)
        routes[arm] = (launch_spec(policy), launcher)
    factory = None
    if timing:
        custody_authorization, resource_authorization = timing_authorizations
        factory = compose_timing_authority(services, custody_authorization, resource_authorization)
    return IsolatedCampaignHost(verify_receipt=services.verify_receipt,
        custody_filesystem=services.custody_filesystem, isolation_guard=services.isolation_guard,
        launcher=ArmRoutingLauncher(routes), process_verifier=services.process_verifier,
        ledgers=dict(services.ledgers), training_summary=services.training_summary,
        cancelled=services.cancelled, reconcile_verifier=services.reconcile_verifier,
        diagnostic_sink=services.diagnostic_sink, economic_allocation=services.economic_allocation,
        timing_authority_factory=factory, warm_attestor=services.warm_attestor if timing else None)


def build_operator_host(services: HostServices, *, registry_factory, cost_summary, timing_factories=None):
    """OperatorHost for scripts/eval.py execute_locked (primary only)."""
    from m7.experiment.activation import OperatorHost
    services.require_core()
    if not callable(registry_factory) or not callable(cost_summary):
        raise HostServiceMissing('host_service_missing:registry_factory_or_cost_summary')
    return OperatorHost(verify_receipt=services.verify_receipt, registry_factory=registry_factory,
        cost_summary=cost_summary, custody_filesystem=services.custody_filesystem,
        isolation_guard=services.isolation_guard, timing_factories=timing_factories,
        cancelled=services.cancelled, economic_allocation=services.economic_allocation)


def build_training_host(services: HostServices):
    """CampaignHost for scripts/train.py campaign; same verifier/guard objects as eval."""
    from m7.training.campaign import CampaignHost
    services.require_core()
    return CampaignHost(verify_receipt=services.verify_receipt, isolation_guard=services.isolation_guard)
