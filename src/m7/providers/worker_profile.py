"""Pure profile/launch models and canonical membership. No I/O or runtime imports.

INT SEAM-DECISION-WORKER-PROFILE-R1: P contains member hashes excluding ONLY P;
full L includes P. Never place full L back into the profile and create a hash cycle.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from m7.contracts import Arm, Boundary, Digest, Identifier


class _FrozenMembers(dict):
    def _locked(self, *args, **kwargs):
        raise TypeError("immutable_worker_members")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _locked


class WorkerProfile(Boundary):
    schema_version: Literal["WorkerProfile/v1"] = "WorkerProfile/v1"
    profile_id: Identifier
    members: Annotated[dict[Arm, Digest], Field(min_length=1, max_length=4)]

    @model_validator(mode="after")
    def immutable_members(self) -> WorkerProfile:
        object.__setattr__(self, "members", _FrozenMembers(self.members))
        return self


class WorkerLaunchMember(Boundary):
    """Complete pre-profile launch fields; never an activation authorization."""
    schema_version: Literal["WorkerLaunchPolicy/v2"] = "WorkerLaunchPolicy/v2"
    arm: Arm
    edition_id: Identifier
    corpus_manifest_sha256: Digest
    filesystem_policy_sha256: Digest
    bootstrap_sha256: Digest
    application_manifest_sha256: Digest
    runtime_environment_sha256: Digest
    executable: Annotated[str, Field(min_length=1, max_length=4096)]
    executable_sha256: Digest
    entrypoint: Annotated[str, Field(min_length=1, max_length=4096)]
    entrypoint_sha256: Digest
    working_directory: Annotated[str, Field(min_length=1, max_length=4096)]
    artifact_root: Annotated[str, Field(min_length=1, max_length=4096)] | None = None
    windows_directory: Annotated[str, Field(min_length=1, max_length=4096)] | None = None
    startup_timeout_seconds: Annotated[float, Field(gt=0, le=120, allow_inf_nan=False)] = 30.0
    close_timeout_seconds: Annotated[float, Field(gt=0, le=10, allow_inf_nan=False)] = 2.0
    lifetime_seconds: Annotated[float, Field(gt=0, le=21600, allow_inf_nan=False)] = 3600.0


class WorkerLaunchPolicy(WorkerLaunchMember):
    profile_sha256: Digest


class WorkerMembership(Boundary):
    arm: Arm
    profile_sha256: Digest
    member_sha256: Digest
    launch_sha256: Digest
    bootstrap_sha256: Digest


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def launch_member_digest(policy: WorkerLaunchMember) -> str:
    return _digest(policy.model_dump(mode="json", exclude={"profile_sha256"}))


def worker_profile_digest(profile: WorkerProfile) -> str:
    return _digest(profile.model_dump(mode="json"))


def validate_worker_membership(profile: WorkerProfile, policy: WorkerLaunchPolicy) -> WorkerMembership:
    # Reparse to reject bypassed scalar types/extras; no authority implied by shape.
    profile = WorkerProfile.model_validate_json(profile.model_dump_json())
    policy = WorkerLaunchPolicy.model_validate_json(policy.model_dump_json())
    digest, member = worker_profile_digest(profile), launch_member_digest(policy)
    if policy.profile_sha256 != digest or profile.members.get(policy.arm) != member:
        raise ValueError("worker_profile_membership_mismatch")
    return WorkerMembership(arm=policy.arm, profile_sha256=digest, member_sha256=member,
                            launch_sha256=_digest(policy.model_dump(mode="json")),
                            bootstrap_sha256=policy.bootstrap_sha256)


def parse_worker_profile_json(raw: bytes) -> WorkerProfile:
    """Bounded duplicate-key-rejecting standalone profile parser; no file reads."""
    if type(raw) is not bytes or len(raw) > 32768:
        raise ValueError("worker_profile_byte_limit")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_worker_profile_key")
            result[key] = value
        return result
    value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")))
    return WorkerProfile.model_validate(value)
