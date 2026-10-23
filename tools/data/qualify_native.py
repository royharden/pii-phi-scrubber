"""Safe Windows qualifier: validate-only default, explicit trusted-host activation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from m7.data.filesystem import checked_path, strict_json
from m7.data.provenance import canonical_bytes, commitment
from m7.data.native_windows_models import NativeQualificationResult, WindowsProcessApproval
from m7.providers.worker_profile import WorkerLaunchPolicy, parse_worker_profile_json, validate_worker_membership
from m7.providers.worker_transport import launch_spec


def _read(path: Path) -> bytes:
    with checked_path(path).open('rb') as source:
        raw = source.read(32769)
    if len(raw) > 32768:
        raise ValueError('qualification_input_too_large')
    return raw


def main(*, host=None) -> int:
    """Host exposes existing guard and WindowsWorkerProcessVerifier; creates neither.

    No arbitrary module/plugin loading. The operator's already approved entrypoint
    calls main(host=...) and passes --activate for the exact externally approved PID.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--pid', type=int)
    parser.add_argument('--start-identity')
    parser.add_argument('--activate', action='store_true')
    args = parser.parse_args()
    missing = tuple('missing_' + name for name in ('profile', 'policy', 'approval', 'pid', 'start_identity')
                    if getattr(args, name) is None)
    if missing:
        result = NativeQualificationResult(status='unqualified' if args.activate else 'validation_only',
                                          reason_codes=missing)
    else:
        profile = parse_worker_profile_json(_read(args.profile))
        policy = WorkerLaunchPolicy.model_validate_json(canonical_bytes(strict_json(_read(args.policy))))
        approval = WindowsProcessApproval.model_validate_json(canonical_bytes(strict_json(_read(args.approval))))
        member = validate_worker_membership(profile, policy)
        if (approval.pid != args.pid or approval.start_identity != args.start_identity
                or approval.profile_sha256 != member.profile_sha256 or approval.launch_sha256 != member.launch_sha256):
            raise ValueError('qualification_input_binding_mismatch')
        if not args.activate:
            result = NativeQualificationResult(status='validation_only', reason_codes=(
                'shape_and_membership_only_not_authorized', 'native_inspection_not_run',
                'trusted_native_host_and_controls_required'))
        elif host is None:
            result = NativeQualificationResult(status='unqualified', reason_codes=('trusted_native_host_required',))
        else:
            from m7.data.access import IsolationGuard
            from m7.data.native_windows import WindowsWorkerProcessVerifier
            if type(host.process_verifier) is not WindowsWorkerProcessVerifier or type(host.guard) is not IsolationGuard:
                raise ValueError('native_qualifier_host_contract_required')
            # File shape cannot add an authorization to the host's trusted store.
            if not any(commitment(a) == commitment(approval) for a in host.process_verifier.approvals):
                raise ValueError('host_process_approval_mismatch')
            try:
                verified = host.guard.require_current(policy.edition_id, policy.corpus_manifest_sha256,
                    filesystem_policy_sha256=policy.filesystem_policy_sha256, worker_policy_sha256=member.profile_sha256)
                result = host.process_verifier.qualify(args.pid, args.start_identity, launch_spec(policy), verified,
                                                       policy, allow_native_inspection=True)
            except Exception:
                result = NativeQualificationResult(status='unqualified', reason_codes=('native_activation_unavailable',),
                                                   native_inspection_performed=None)
    print(json.dumps(result.model_dump(mode='json'), sort_keys=True, allow_nan=False))
    return 2 if result.status == 'unqualified' else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('{"status":"unqualified","reason_codes":["native_qualification_input_unavailable"],"native_inspection_performed":false,"authority_issued":false}')
        raise SystemExit(2) from None
