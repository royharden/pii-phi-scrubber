"""Static composition-root cases (R2 proposal section 3; R4 grant guards).

Leaf services are recording stubs that raise if called: construction must be
inert. Native/timing classes are replaced with recorders only to check the exact
wiring; the real campaign.py/timing_native.py checks are not reimplemented here.
Instances of source classes are made with object.__new__ to obtain the right
type without approval records (no validation runs, nothing executes).
"""
from types import SimpleNamespace

import pytest

from m7.data.access import IsolationGuard
from m7.data.filesystem import CustodyFilesystem
from m7.data.native_windows import WindowsWorkerProcessVerifier
from m7.experiment.isolated import IsolatedCampaignHost
from m7.host import (
    ArmRoutingLauncher, HostServiceMissing, HostServices, HostUnavailable, build_campaign_host,
    build_operator_host, build_training_host, compose_timing_authority,
)
from m7.host import unavailable
from m7.providers.contracts import AdapterFault
from m7.training.campaign import CampaignHost


def forbidden(name):
    def call(*args, **kwargs):
        raise AssertionError(name + " called during construction")
    return call


def filesystem():
    return object.__new__(CustodyFilesystem)


def verifier_over(fs):
    verifier = object.__new__(WindowsWorkerProcessVerifier)
    verifier.filesystem = fs
    return verifier


def services(**overrides):
    fs = overrides.pop("custody_filesystem", None) or filesystem()
    fields = dict(verify_receipt=forbidden("verify_receipt"), custody_filesystem=fs,
                  isolation_guard=object.__new__(IsolationGuard), process_verifier=verifier_over(fs),
                  launch_host=SimpleNamespace(verify_context=forbidden("verify_context"),
                                              prepare_suspended=forbidden("prepare_suspended")),
                  launch_contexts={"base": "ctx-base", "frontier": "ctx-frontier"},
                  ledgers={"base": "L-b", "finetuned": "L-f", "frontier": "L-fr"},
                  training_summary=forbidden("training_summary"), cancelled=forbidden("cancelled"))
    fields.update(overrides)
    return HostServices(**fields)


def bundle(arms=("base", "frontier")):
    policies = {arm: SimpleNamespace(arm=arm, name="policy-" + arm) for arm in arms}
    return SimpleNamespace(campaign=SimpleNamespace(launch_policies=policies, worker_profile="profile-1"))


def missing(exc):
    return str(exc.value)


# --- HostServices requirements -----------------------------------------------------

def test_noncallable_receipt_verifier_refused():
    with pytest.raises(HostServiceMissing) as exc:
        services(verify_receipt=None).require_core()
    assert missing(exc) == "host_service_missing:verify_receipt"


def test_wrong_type_guard_refused():
    with pytest.raises(HostServiceMissing) as exc:
        services(isolation_guard=SimpleNamespace(require_current=forbidden("guard"))).require_core()
    assert missing(exc) == "host_service_missing:isolation_guard"


def test_protocol_only_process_verifier_refused_for_campaign():
    # A duck-typed verify() object is not the concrete WindowsWorkerProcessVerifier.
    fake = SimpleNamespace(verify=forbidden("verify"), filesystem=None)
    with pytest.raises(HostServiceMissing) as exc:
        services(process_verifier=fake).require_campaign(timing=False)
    assert missing(exc) == "host_service_missing:process_verifier"


def test_verifier_over_different_filesystem_refused_at_build_time():
    # Equal-looking but distinct filesystem objects must be refused (identity, not equality).
    with pytest.raises(HostServiceMissing) as exc:
        services(process_verifier=verifier_over(filesystem())).require_campaign(timing=False)
    assert missing(exc) == "host_service_mismatch:process_verifier.filesystem"


def test_ledgers_must_cover_exactly_three_model_arms():
    with pytest.raises(HostServiceMissing) as exc:
        services(ledgers={"base": "L", "finetuned": "L"}).require_campaign(timing=False)
    assert missing(exc) == "host_service_missing:ledgers"
    with pytest.raises(HostServiceMissing):
        services(ledgers={"base": "L", "finetuned": "L", "frontier": "L", "regex": "L"}).require_campaign(timing=False)


def test_timing_requires_attestor_and_snapshot_provider():
    with pytest.raises(HostServiceMissing) as exc:
        services(timing_snapshot_provider=forbidden("snap")).require_campaign(timing=True)
    assert missing(exc) == "host_service_missing:warm_attestor"
    with pytest.raises(HostServiceMissing) as exc:
        services(warm_attestor=forbidden("attest")).require_campaign(timing=True)
    assert missing(exc) == "host_service_missing:timing_snapshot_provider"


# --- routing launcher ---------------------------------------------------------------

class RecordingLauncher:
    def __init__(self):
        self.calls = []

    def launch(self, spec, verified_isolation, *, timeout):
        self.calls.append((spec, verified_isolation, timeout))
        return "worker"


def test_router_sends_exact_spec_to_its_launcher_unchanged():
    a, b = RecordingLauncher(), RecordingLauncher()
    router = ArmRoutingLauncher({"base": ("spec-a", a), "frontier": ("spec-b", b)})
    assert router.launch("spec-b", "iso-1", timeout=7.5) == "worker"
    assert (a.calls, b.calls) == ([], [("spec-b", "iso-1", 7.5)])


def test_router_refuses_unknown_spec_without_trying_launchers():
    a = RecordingLauncher()
    router = ArmRoutingLauncher({"base": ("spec-a", a)})
    with pytest.raises(AdapterFault):
        router.launch("spec-z", "iso-1", timeout=1.0)
    assert a.calls == []


def test_router_refuses_ambiguous_duplicate_spec():
    a, b = RecordingLauncher(), RecordingLauncher()
    router = ArmRoutingLauncher({"base": ("same", a), "frontier": ("same", b)})
    with pytest.raises(AdapterFault):
        router.launch("same", "iso-1", timeout=1.0)
    assert a.calls == [] and b.calls == []


def test_router_requires_routes():
    with pytest.raises(HostServiceMissing):
        ArmRoutingLauncher({})


# --- campaign host wiring -------------------------------------------------------------

@pytest.fixture
def recorded_launchers(monkeypatch):
    made = []

    class FakeWindowsLauncher:
        def __init__(self, context, policy, profile, **kwargs):
            made.append(SimpleNamespace(context=context, policy=policy, profile=profile, **kwargs))
            self.policy = policy

    monkeypatch.setattr("m7.providers.native_launcher.WindowsIsolatedLauncher", FakeWindowsLauncher)
    monkeypatch.setattr("m7.providers.worker_transport.launch_spec", lambda policy: "spec-" + policy.arm)
    return made


def test_campaign_host_shares_guard_and_verifier_and_has_no_timing_by_default(recorded_launchers):
    s = services(warm_attestor=forbidden("attest"))
    host = build_campaign_host(s, bundle())
    assert isinstance(host, IsolatedCampaignHost)
    assert [m.context for m in recorded_launchers] == ["ctx-base", "ctx-frontier"]
    for made in recorded_launchers:
        assert made.isolation_guard is s.isolation_guard and made.process_verifier is s.process_verifier
        assert made.host is s.launch_host and made.allow_execution is True and made.profile == "profile-1"
    assert host.process_verifier is s.process_verifier and host.custody_filesystem is s.custody_filesystem
    assert host.isolation_guard is s.isolation_guard and host.verify_receipt is s.verify_receipt
    # Primary-only: no factory and the attestor is not forwarded.
    assert host.timing_authority_factory is None and host.warm_attestor is None
    assert isinstance(host.launcher, ArmRoutingLauncher)


def test_built_router_maps_each_arm_spec_to_that_arms_launcher(recorded_launchers, monkeypatch):
    calls = []

    def record_launch(self, spec, verified_isolation, *, timeout):
        calls.append((self.policy.arm, spec))
        return "worker-" + self.policy.arm

    import m7.providers.native_launcher as native_launcher
    # The fixture already replaced WindowsIsolatedLauncher with its recorder class.
    monkeypatch.setattr(native_launcher.WindowsIsolatedLauncher, "launch", record_launch, raising=False)
    arms = ("regex", "frontier", "base", "finetuned")
    s = services(launch_contexts={arm: "ctx-" + arm for arm in arms})
    host = build_campaign_host(s, bundle(arms))
    for arm in arms:
        assert host.launcher.launch("spec-" + arm, "iso", timeout=1.0) == "worker-" + arm
    assert calls == [(arm, "spec-" + arm) for arm in arms]


def test_campaign_host_refuses_contexts_not_matching_policies(recorded_launchers):
    with pytest.raises(HostServiceMissing) as exc:
        build_campaign_host(services(launch_contexts={"base": "ctx-base"}), bundle())
    assert missing(exc) == "host_service_mismatch:launch_contexts"
    assert recorded_launchers == []


def test_campaign_host_with_timing_forwards_attestor_and_factory(recorded_launchers):
    attestor = forbidden("attest")
    s = services(warm_attestor=attestor, timing_snapshot_provider=forbidden("snap"))
    host = build_campaign_host(s, bundle(), timing_authorizations=("custody-auth", "resource-auth"))
    assert host.warm_attestor is attestor and callable(host.timing_authority_factory)


# --- timing authority factory ------------------------------------------------------------

def test_timing_factory_requires_both_authorizations():
    with pytest.raises(HostServiceMissing):
        compose_timing_authority(services(), None, "resource-auth")


def test_timing_factory_refuses_custody_over_other_filesystem(monkeypatch):
    for target in ("m7.data.timing.CustodyTimingAuthority", "m7.data.timing_native.WindowsTimingProcessGuard",
                   "m7.training.timing_resources.TimingResourceAuthority"):
        monkeypatch.setattr(target, forbidden(target))
    factory = compose_timing_authority(services(), "custody-auth", "resource-auth")
    custody = SimpleNamespace(filesystem=filesystem())
    with pytest.raises(HostServiceMissing):
        factory(custody=custody, bundle=bundle(), edition="E", primary="P", plan="T", resources="S", identities={})


def test_timing_factory_wires_canonical_classes_exactly(monkeypatch):
    seen = {}

    def recorder(name):
        def make(*args, **kwargs):
            seen[name] = (args, kwargs)
            return name
        return make

    monkeypatch.setattr("m7.data.timing_native.WindowsTimingProcessGuard", recorder("guard"))
    monkeypatch.setattr("m7.training.timing_resources.TimingResourceAuthority", recorder("resources"))
    monkeypatch.setattr("m7.data.timing.CustodyTimingAuthority", recorder("authority"))
    snap = forbidden("snap")
    s = services(timing_snapshot_provider=snap, warm_attestor=forbidden("attest"))
    custody, b = SimpleNamespace(filesystem=s.custody_filesystem), bundle()
    result = compose_timing_authority(s, "custody-auth", "resource-auth")(
        custody=custody, bundle=b, edition="E", primary="P", plan="T", resources="S", identities={})
    assert result == "authority"
    # Policies come from the passed bundle (equal to campaign spec.launch_policies), not a pre-bound copy.
    assert seen["guard"] == ((custody, s.process_verifier, b.campaign.launch_policies), {})
    # No clock supplied -> the authority's own default clock is kept.
    assert seen["resources"] == ((b, "S", "resource-auth"), {"verify_receipt": s.verify_receipt, "snapshot_provider": snap})
    assert seen["authority"] == ((custody, "E", "custody-auth"), {"resources": "resources", "verify_process": "guard"})


# --- operator / training hosts --------------------------------------------------------

def test_training_host_reuses_same_verifier_and_guard():
    s = services()
    host = build_training_host(s)
    assert isinstance(host, CampaignHost)
    assert host.verify_receipt is s.verify_receipt and host.isolation_guard is s.isolation_guard


def test_operator_host_requires_registry_and_cost_callables():
    with pytest.raises(HostServiceMissing):
        build_operator_host(services(), registry_factory=None, cost_summary=forbidden("cost"))
    host = build_operator_host(services(), registry_factory=forbidden("reg"), cost_summary=forbidden("cost"))
    assert host.timing_factories is None


# --- shipped refusing host ---------------------------------------------------------------

def test_unavailable_factories_always_raise_catchable_exception():
    assert issubclass(HostUnavailable, Exception)
    for call in (lambda: unavailable.campaign_host("bundle", "edition"),
                 lambda: unavailable.operator_host("edition"), unavailable.training_host):
        with pytest.raises(HostUnavailable):
            call()
