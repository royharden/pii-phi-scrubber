"""Test-only worker scaffolding: one frontier-arm bootstrap, launch/profile pins and in-memory fakes.

Nothing here spawns a process, opens a pipe, reads a credential or contacts a provider. The
scripted child is a queue of wire lines; the guard/verifier are explicit allowlist stand-ins.
"""
from __future__ import annotations

from pathlib import Path

from m7.contracts import Boundary
from m7.providers.contracts import AttemptPolicy, ExecutionPermit, FrontierConfig, config_digest
from m7.providers.frontier import PROMPT_SHA256
from m7.providers.worker_profile import (
    WorkerLaunchMember, WorkerLaunchPolicy, WorkerProfile, launch_member_digest, worker_profile_digest,
)
from m7.providers.worker_wire import WorkerBootstrap, WorkerLimits, WorkerPin, WorkerReply, encode_line

RUN, SESSION = 'test-run', 'session-1'


def frontier_config() -> FrontierConfig:
    return FrontierConfig(model_id='frontier-test', provider_model='stub-model', model_revision_sha256='5' * 64,
                          endpoint='https://example.invalid/v1/chat', provider_terms_sha256='6' * 64,
                          prompt_sha256=PROMPT_SHA256, token_counter_sha256='7' * 64,
                          max_input_tokens=1000, max_output_tokens=100, context_window_tokens=2000)


def attempt_policy() -> AttemptPolicy:
    return AttemptPolicy(policy_id='policy-1', authorization_id='auth-1', rate_receipt_sha256='8' * 64,
                         max_transient_retries=1, authorization_cap_micros=100, worst_case_micros=10,
                         max_records=10, input_micros_per_million_tokens=0, output_micros_per_million_tokens=0)


def regex_bootstrap() -> WorkerBootstrap:
    # The regex arm needs no config/permit/policy (and has no ledger or paid call).
    pin = WorkerPin(arm='regex', model_id='context-regex-v1', artifact_sha256='4' * 64,
                    configuration_sha256='3' * 64)
    return WorkerBootstrap(session_id=SESSION, run_id=RUN, pin=pin, limits=WorkerLimits(max_records=5),
                           configs={}, permits={}, policies={})


def bootstrap() -> WorkerBootstrap:
    config, policy = frontier_config(), attempt_policy()
    permit = ExecutionPermit(permit_id='permit-1', run_id=RUN, model_id=config.model_id, scope='frontier_inference',
                             config_sha256=config_digest(config), authorization_sha256='9' * 64,
                             license_receipt_sha256='a' * 64, resource_receipt_sha256='b' * 64,
                             issued_at='2020-01-01T00:00:00Z', expires_at='2099-01-01T00:00:00Z', approved=True,
                             attempt_policy_sha256=config_digest(policy))
    pin = WorkerPin(arm='frontier', model_id=config.model_id, artifact_sha256=config.model_revision_sha256,
                    configuration_sha256=config_digest(config))
    return WorkerBootstrap(session_id=SESSION, run_id=RUN, pin=pin, limits=WorkerLimits(max_records=5),
                           configs={'frontier': config}, permits={'frontier': permit},
                           policies={'frontier': policy})


def launch_member(base: Path, boot: WorkerBootstrap, **overrides) -> WorkerLaunchMember:
    values = dict(arm=boot.pin.arm, edition_id='ed-1', corpus_manifest_sha256='c' * 64,
                  filesystem_policy_sha256='d' * 64, bootstrap_sha256=config_digest(boot),
                  application_manifest_sha256='e' * 64, runtime_environment_sha256='f' * 64,
                  executable=str(base / 'python.exe'), executable_sha256='1' * 64,
                  entrypoint=str(base / 'worker.py'), entrypoint_sha256='2' * 64,
                  working_directory=str(base / 'work'))
    values.update(overrides)
    return WorkerLaunchMember(**values)


def profile_and_policy(base: Path, boot: WorkerBootstrap):
    member = launch_member(base, boot)
    profile = WorkerProfile(profile_id='profile-1', members={boot.pin.arm: launch_member_digest(member)})
    policy = WorkerLaunchPolicy(**member.model_dump(), profile_sha256=worker_profile_digest(profile))
    return profile, policy


class AllowGuard:
    """Stands in for IsolationGuard: records activations, vouches only for listed receipt kinds."""
    KINDS = {'worker_profile_approval', 'worker_launch_approval', 'worker_application_manifest',
             'worker_runtime_environment'}

    def __init__(self):
        self.activations = []

    def require_current(self, edition_id, manifest_sha256, *, filesystem_policy_sha256=None,
                        worker_policy_sha256=None):
        self.activations.append((edition_id, manifest_sha256, filesystem_policy_sha256, worker_policy_sha256))
        return 'verified-isolation'

    def verify_receipt(self, kind, digest):
        return kind in self.KINDS


class AllowProcessVerifier:
    def verify(self, pid, start_identity, spec, verified, policy):
        return pid == 4242 and start_identity == 'start-1' and verified == 'verified-isolation'


class ScriptedChild:
    """OwnedWorker fake: each receive() pops the next scripted line or raises the scripted error."""

    def __init__(self, *script):
        self.pid, self.start_identity = 4242, 'start-1'
        self.script, self.sent = list(script), []
        self.terminated = self.waited = 0

    def send(self, raw: bytes, timeout: float) -> None:
        self.sent.append(raw)

    def receive(self, limit: int, timeout: float) -> bytes:
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return encode_line(step, limit=limit) if isinstance(step, Boundary) else step

    def terminate(self) -> None:
        self.terminated += 1

    def wait(self, timeout: float) -> None:
        self.waited += 1


class RecordingLedger:
    authorization_id, cap = 'auth-1', 100

    def __init__(self):
        self.reserved, self.reconciled = [], []

    def reserve(self, attempt_id, worst_case_micros, *, category):
        self.reserved.append((attempt_id, worst_case_micros, category))

    def reconcile(self, attempt_id, *, actual_micros, state, usage_units=None, receipt_id=None,
                  compute_seconds=None):
        self.reconciled.append((attempt_id, actual_micros, state, usage_units))


def reply(seq: int, status: str, **fields) -> WorkerReply:
    return WorkerReply(session_id=SESSION, seq=seq, status=status, **fields)


def preflight_script(count: int = 1):
    """One preflight_ok per record (seq 1..count), then sealed (seq count + 1)."""
    return [reply(seq, 'preflight_ok') for seq in range(1, count + 1)] + [reply(count + 1, 'sealed')]
