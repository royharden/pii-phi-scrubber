"""Shipped refusing host: the honest blocked path for demos and docs.

Every factory raises; none returns a host object. Example:
    python scripts/eval.py ... --operator-host m7.host.unavailable:campaign_host
"""
from __future__ import annotations


class HostUnavailable(Exception):
    """Fixed refusal; an Exception (not BaseException) so CLI guards catch it."""


def campaign_host(bundle, edition):
    raise HostUnavailable('host_composition_not_provisioned')


def operator_host(edition):
    raise HostUnavailable('host_composition_not_provisioned')


def training_host():
    raise HostUnavailable('host_composition_not_provisioned')
