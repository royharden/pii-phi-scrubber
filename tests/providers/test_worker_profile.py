"""Canonical P / member / L digests per agentops SEAM-DECISION-WORKER-PROFILE-R1 (pure, no I/O).

Expected digests are re-derived from the seam rule itself (sorted keys, compact separators,
ensure_ascii, allow_nan=False over model_dump(mode=json)), not by calling the helpers under test.
"""
import hashlib
import json

import pytest

from m7.providers.contracts import config_digest
from m7.providers.worker_profile import (
    WorkerLaunchPolicy, WorkerProfile, launch_member_digest, parse_worker_profile_json, validate_worker_membership,
    worker_profile_digest,
)

from .worker_fixtures import bootstrap, launch_member, profile_and_policy


def seam_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def test_member_digest_excludes_only_the_profile_field(tmp_path):
    profile, policy = profile_and_policy(tmp_path, bootstrap())
    dumped = policy.model_dump(mode='json')
    without_p = {key: value for key, value in dumped.items() if key != 'profile_sha256'}
    assert set(dumped) - set(without_p) == {'profile_sha256'}
    assert launch_member_digest(policy) == seam_digest(without_p)
    # Changing P alone leaves the member digest unchanged ...
    assert launch_member_digest(policy.model_copy(update={'profile_sha256': '0' * 64})) == seam_digest(without_p)
    # ... while any other launch field (here the exact bootstrap pin) changes it.
    assert launch_member_digest(policy.model_copy(update={'bootstrap_sha256': '0' * 64})) != seam_digest(without_p)


def test_profile_digest_and_full_launch_digest_bind_p(tmp_path):
    profile, policy = profile_and_policy(tmp_path, bootstrap())
    p = seam_digest({'schema_version': 'WorkerProfile/v1', 'profile_id': 'profile-1',
                     'members': {'frontier': launch_member_digest(policy)}})
    assert worker_profile_digest(profile) == p == policy.profile_sha256
    membership = validate_worker_membership(profile, policy)
    full_l = seam_digest(policy.model_dump(mode='json'))  # L includes P
    assert (membership.profile_sha256, membership.launch_sha256) == (p, full_l)
    assert membership.member_sha256 == launch_member_digest(policy) != full_l
    assert full_l == config_digest(policy)  # the seam's L = config_digest(policy)


def test_unlike_hashes_are_never_equated(tmp_path):
    profile, policy = profile_and_policy(tmp_path, bootstrap())
    full_l = seam_digest(policy.model_dump(mode='json'))
    # A profile that pins the FULL launch digest (instead of the member digest) is not membership.
    wrong_profile = WorkerProfile(profile_id='profile-1', members={'frontier': full_l})
    wrong_policy = policy.model_copy(update={'profile_sha256': worker_profile_digest(wrong_profile)})
    with pytest.raises(ValueError, match='worker_profile_membership_mismatch'):
        validate_worker_membership(wrong_profile, wrong_policy)
    # A launch whose P is some other profile's digest is refused.
    with pytest.raises(ValueError, match='worker_profile_membership_mismatch'):
        validate_worker_membership(profile, policy.model_copy(update={'profile_sha256': '0' * 64}))
    # A member for another arm does not cover this arm.
    other = WorkerProfile(profile_id='profile-1', members={'base': launch_member_digest(policy)})
    with pytest.raises(ValueError, match='worker_profile_membership_mismatch'):
        validate_worker_membership(other, policy.model_copy(update={'profile_sha256': worker_profile_digest(other)}))


def test_profile_members_are_immutable_and_closed(tmp_path):
    profile, _ = profile_and_policy(tmp_path, bootstrap())
    with pytest.raises(TypeError):
        profile.members['base'] = '0' * 64
    with pytest.raises(ValueError):
        WorkerProfile(profile_id='p', members={'gpt-x': '0' * 64})  # unknown arm
    with pytest.raises(ValueError):
        WorkerProfile(profile_id='p', members={})  # at least one member


def test_profile_json_parser_is_strict():
    with pytest.raises(ValueError, match='duplicate_worker_profile_key'):
        parse_worker_profile_json(b'{"profile_id":"p","profile_id":"q","members":{"regex":"' + b'0' * 64 + b'"}}')
    with pytest.raises(ValueError, match='worker_profile_byte_limit'):
        parse_worker_profile_json(b' ' * 32769)
    parsed = parse_worker_profile_json(b'{"profile_id":"p","members":{"regex":"' + b'0' * 64 + b'"}}')
    assert dict(parsed.members) == {'regex': '0' * 64}


def test_launch_policy_requires_p(tmp_path):
    member = launch_member(tmp_path, bootstrap())
    with pytest.raises(ValueError):
        WorkerLaunchPolicy(**member.model_dump())  # profile_sha256 is required for activation
