"""Host composition root (inert wiring only; runtime unverified)."""
from .compose import (
    ArmRoutingLauncher, build_campaign_host, build_custody, build_operator_host, build_training_host,
    compose_timing_authority,
)
from .services import HostServiceMissing, HostServices
from .unavailable import HostUnavailable

__all__ = ['ArmRoutingLauncher', 'HostServiceMissing', 'HostServices', 'HostUnavailable', 'build_campaign_host',
           'build_custody', 'build_operator_host', 'build_training_host', 'compose_timing_authority']
