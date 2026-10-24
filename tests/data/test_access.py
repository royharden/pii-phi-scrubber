"""Role-scoped custody paths and the isolation capability gate (no real OS sandbox is claimed)."""
from datetime import datetime, timezone

import pytest

from m7.data.access import require_isolation

from .custody_fixtures import TrustedHost, custody_filesystem, digest, isolation_guard


def refused(message, call, *args, **kwargs):
    with pytest.raises(ValueError, match=message):
        call(*args, **kwargs)


def test_inference_context_cannot_reach_evaluator_root(tmp_path):
    filesystem = custody_filesystem(tmp_path, TrustedHost())
    roots = filesystem.roots()
    refused('path_outside_custody_role', filesystem.require_path, 'inference',
            roots['evaluator'] / 'gold-export', must_exist=False)
    refused('path_outside_custody_role', filesystem.require_path, 'inference',
            roots['private'] / 'journal', must_exist=False)
    # The role root itself is never a writable export target either.
    refused('path_outside_custody_role', filesystem.require_path, 'inference', roots['inference'])
    assert filesystem.require_path('inference', roots['inference'] / 'export-1', must_exist=False) \
        == roots['inference'] / 'export-1'


def test_inference_export_into_evaluator_root_is_refused(tmp_path):
    filesystem = custody_filesystem(tmp_path, TrustedHost())
    refused('path_outside_custody_role', filesystem.write_export, 'inference',
            filesystem.roots()['evaluator'] / 'export-1', (), export_id='export-1')
    assert list(filesystem.roots()['evaluator'].iterdir())[0].name == '.custody-root-policy.json'


def test_traversal_into_evaluator_root_is_refused(tmp_path):
    filesystem = custody_filesystem(tmp_path, TrustedHost())
    sneaky = str(filesystem.roots()['inference']) + '/../evaluator/gold-export'
    refused('custody_path_traversal', filesystem.require_path, 'inference', sneaky, must_exist=False)


def test_unapproved_filesystem_policy_refuses_every_path(tmp_path):
    filesystem = custody_filesystem(tmp_path, TrustedHost())
    filesystem.verify_receipt = TrustedHost()  # host no longer vouches for the policy approval
    refused('filesystem_policy_not_authenticated_or_current', filesystem.require_path, 'inference',
            filesystem.roots()['inference'] / 'export-1', must_exist=False)


def guard_for(tmp_path, host=None):
    host = host or TrustedHost()
    filesystem = custody_filesystem(tmp_path, host)
    return isolation_guard(filesystem, host, edition_id='ed-1', manifest_sha256=digest('manifest')), host


def test_isolation_guard_refuses_other_edition_or_manifest(tmp_path):
    guard, _ = guard_for(tmp_path)
    assert guard.require_current('ed-1', digest('manifest')).capability_sha256 == guard.sha256
    refused('isolation_activation_binding_mismatch', guard.require_current, 'ed-2', digest('manifest'))
    refused('isolation_activation_binding_mismatch', guard.require_current, 'ed-1', digest('other'))


def test_isolation_requires_authenticated_platform_enforcement(tmp_path):
    guard, host = guard_for(tmp_path)
    refused('authenticated_actual_platform_enforcement_required', require_isolation, guard.capability,
            guard.request, verify_receipt=host, platform_verifier=None)
    refused('authenticated_actual_platform_enforcement_required', require_isolation, guard.capability,
            guard.request, verify_receipt=TrustedHost(), platform_verifier=guard.platform_verifier)


def test_expired_isolation_capability_is_refused(tmp_path):
    guard, host = guard_for(tmp_path)
    late = datetime(2100, 1, 1, tzinfo=timezone.utc)  # capability expires 2099-01-01
    refused('isolation_capability_expired', require_isolation, guard.capability, guard.request,
            verify_receipt=host, platform_verifier=guard.platform_verifier, now=late)
