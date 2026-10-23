"""Control qualification SOURCE CLI: pure policy validation unless explicitly activated."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from m7.data.filesystem import checked_path, strict_json
from m7.data.native_controls_models import WindowsControlPolicy, ControlQualificationReport
from m7.data.provenance import canonical_bytes, commitment


def main(*, host=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--stage', choices=('prepared', 'process'), default='prepared')
    parser.add_argument('--pid', type=int)
    parser.add_argument('--start-identity')
    parser.add_argument('--activate', action='store_true')
    args = parser.parse_args()
    if args.policy is None:
        report = ControlQualificationReport(status='unqualified' if args.activate else 'validation_only', stage=args.stage,
                                            unknown_facts=('control_policy_required', 'trusted_native_host_required'))
    else:
        with checked_path(args.policy).open('rb') as stream:
            raw = stream.read(32769)
        if len(raw) > 32768:
            raise ValueError('control_policy_too_large')
        policy = WindowsControlPolicy.model_validate_json(canonical_bytes(strict_json(raw)))
        if not args.activate:
            report = ControlQualificationReport(status='validation_only', stage=args.stage,
                profile_sha256=policy.profile_sha256, unknown_facts=('native_queries_not_requested',
                    'context_provider_and_external_observer_required', 'authenticated_policy_and_context_required'))
        elif host is None:
            report = ControlQualificationReport(status='unqualified', stage=args.stage,
                                                unknown_facts=('trusted_native_host_required',))
        else:
            from m7.data.native_controls import ReadOnlyWindowsControlVerifier
            if type(host.control_verifier) is not ReadOnlyWindowsControlVerifier or commitment(host.control_verifier.policy) != commitment(policy):
                raise ValueError('native_control_host_policy_mismatch')
            if args.stage == 'prepared':
                if args.pid is not None or args.start_identity is not None:
                    raise ValueError('prepared_control_qualification_has_no_pid')
                report = host.control_verifier.qualify_policy(host.policy_evidence, host.capability,
                    host.request, host.profile, allow_native_queries=True)
            else:
                if (args.pid is None or args.start_identity is None or args.pid != host.process_approval.pid
                        or args.start_identity != host.process_approval.start_identity):
                    raise ValueError('exact_process_control_qualification_required')
                report = host.control_verifier.qualify_process(host.process_approval, host.native_observation,
                    host.launch_spec, host.launch_policy, allow_native_queries=True)
    print(json.dumps(report.model_dump(mode='json'), allow_nan=False, sort_keys=True))
    return 2 if report.status == 'unqualified' else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('{"status":"unqualified","unknown_facts":["control_qualification_input_unavailable"],"authority_issued":false}')
        raise SystemExit(2) from None
