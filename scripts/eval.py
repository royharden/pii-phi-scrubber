"""Public development evaluation or nonexecuting sealed-lock validation.

Authorized execution hosts call m7.experiment.execute_edition with a trusted
receipt verifier; a CLI JSON file cannot grant itself custody/provider authority.
"""

import argparse
import importlib
import re
from pathlib import Path

from _common import approved_result, copy_approved_report, emit, guarded, load_boundary
from demo import development_records
from m7.detectors.regex import detect_regex
from m7.publish import artifact_is_safe, gate_record, write_report
from m7.runner import run_offline
from m7.experiment import (EditionJournal, EvaluationAuthorization, LockedEdition,
    OperatorHost, ReceiptAuthority, channels_from_bundle,
    execute_edition, policy_from_selection_lock)
from m7.publish import write_locked_artifacts


def campaign_mode(args):
    """Validate by default; never import the operator host until explicit execution."""
    from m7.training.launch_bundle import load_launch_bundle
    from m7.experiment.campaign import CampaignPrerequisiteError, execute_isolated_campaign, validate_campaign_inputs
    from m7.experiment.isolated import IsolatedCampaignHost
    if args.lock is None or args.authorization is None:
        raise ValueError('campaign_edition_and_authorization_definitions_required')
    bundle = load_launch_bundle(args.launch_bundle)
    edition = load_boundary(args.lock, LockedEdition)
    authorization = load_boundary(args.authorization, EvaluationAuthorization)
    validation = validate_campaign_inputs(bundle, edition, authorization)
    from m7.experiment.timing_contracts import IsolatedTimingPlan
    from m7.experiment.isolated_timing import validate_timing_plan
    timing_plan = load_boundary(args.timing_plan, IsolatedTimingPlan) if args.timing_plan else None
    from m7.training.timing_resources import TimingResourceSchedule, validate_timing_resources
    timing_resources = load_boundary(args.timing_resources, TimingResourceSchedule) if args.timing_resources else None
    if timing_plan is not None:
        validate_timing_plan(edition, timing_plan)
        validation['timing_plan_structure_valid_not_authorized'] = True
        if timing_resources is not None:
            validation['timing_resource_schedule'] = validate_timing_resources(bundle, timing_plan, timing_resources)
    elif timing_resources is not None:
        raise ValueError('timing_resource_schedule_requires_plan')
    if args.run_timing and (timing_plan is None or timing_resources is None):
        emit({'status': 'unavailable', 'reason': 'locked_timing_plan_and_resource_schedule_required',
              'worker_started': False, 'product_acceptance': False})
        return 3
    if not args.execute_campaign:
        if args.out is not None:
            raise ValueError('validation_cannot_write_artifacts')
        emit(validation)
        return 0
    required = ('operator_host', 'custody_lifecycle', 'journal', 'inference_export', 'gold_export',
                'inference_export_sha256', 'gold_export_sha256', 'out')
    missing = [key for key in required if getattr(args, key) is None]
    if args.validate_only or missing:
        emit({'status': 'unavailable', 'reason': 'explicit_campaign_activation_inputs_required',
              'missing_fields': missing, 'product_acceptance': False})
        return 3
    if args.run_timing:
        if timing_plan is None or timing_resources is None or args.timing_out is None:
            emit({'status': 'unavailable', 'reason': 'explicit_locked_timing_plan_and_directory_required',
                  'worker_started': False, 'product_acceptance': False})
            return 3
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*', args.operator_host):
        raise ValueError('trusted_operator_module_required')
    module, factory = args.operator_host.split(':')
    try:
        host = getattr(importlib.import_module(module), factory)(bundle, edition)
    except Exception:
        emit({'status': 'unavailable', 'reason': 'authenticated_operator_host_unavailable', 'product_acceptance': False})
        return 3
    if not isinstance(host, IsolatedCampaignHost):
        emit({'status': 'unavailable', 'reason': 'native_campaign_host_required', 'product_acceptance': False})
        return 3
    try:
        result = execute_isolated_campaign(bundle, edition, authorization, host=host,
            lifecycle_root=args.custody_lifecycle, journal_directory=args.journal,
            inference_directory=args.inference_export, gold_directory=args.gold_export,
            inference_export_sha256=args.inference_export_sha256, gold_export_sha256=args.gold_export_sha256,
            artifact_directory=args.out, timing_plan=timing_plan if args.run_timing else None,
            timing_directory=args.timing_out if args.run_timing else None,
            timing_resources=timing_resources if args.run_timing else None)
    except CampaignPrerequisiteError as error:
        emit({'status': 'unavailable', 'reason': error.code, 'product_acceptance': False})
        return 3
    emit(result)
    return 0 if (result['edition_state'] == 'closed' and result['comparison_status'] == 'fully_attempted'
                 and result['timing_status'] in ('not_requested', 'measured')) else 3


def execute_locked(args):
    """Future trusted operator activation. No automatic host/provider selection."""
    if args.run_timing:
        emit({'status': 'unavailable', 'reason': 'isolated_campaign_timing_required',
              'worker_started': False, 'product_acceptance': False})
        return 3
    required = ('lock', 'authorization', 'selection_lock', 'targets', 'custody_bundle',
                'custody_lifecycle', 'journal', 'operator_host', 'out')
    if any(getattr(args, key) is None for key in required):
        raise ValueError('locked_execution_inputs_required')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*', args.operator_host):
        raise ValueError('trusted_operator_module_required')
    edition = load_boundary(args.lock, LockedEdition)
    authorization = load_boundary(args.authorization, EvaluationAuthorization)
    # Explicit operator-supplied trusted code. Construction must not load models,
    # read credentials or perform inference; it only provides factories/verifier.
    module, factory = args.operator_host.split(':')
    try:
        host = getattr(importlib.import_module(module), factory)(edition)
    except Exception:
        emit({'status': 'unavailable', 'reason': 'authenticated_operator_host_unavailable', 'product_acceptance': False})
        return 3
    if not isinstance(host, OperatorHost):
        raise ValueError('operator_host_contract_required')
    if (not callable(host.verify_receipt) or host.custody_filesystem is None
            or host.isolation_guard is None):
        emit({'status': 'unavailable', 'reason': 'authenticated_operator_host_unavailable',
              'product_acceptance': False})
        return 3
    from m7.data.lifecycle import CustodyLifecycle
    from m7.data.storage import read_bundle
    from m7.training.selection_models import NumericalTargets, PreTestSelectionLock
    selection_lock = load_boundary(args.selection_lock, PreTestSelectionLock)
    targets = load_boundary(args.targets, NumericalTargets)
    policy_from_selection_lock(edition, selection_lock, targets, verify_receipt=host.verify_receipt)
    custody = CustodyLifecycle(args.custody_lifecycle, verify_receipt=host.verify_receipt,
                              filesystem=host.custody_filesystem, isolation_guard=host.isolation_guard)
    authority = ReceiptAuthority(authorization, verify_receipt=custody.verify_release_receipt)
    authorize = custody.evaluation_gate(authority)
    def preflight_authority(candidate, resume):
        authority(candidate, resume)
        custody.require_released(candidate)
    journal = EditionJournal(args.journal, filesystem=host.custody_filesystem)
    # Authenticate current release/isolation BEFORE any held-out gold is read.
    # Do not consume D4 open here: execution opens exactly once after preflight.
    with journal.writer():
        edition.require_current()
        journal.seal(edition)
        preflight_authority(edition, journal.opened)
    inference, gold = channels_from_bundle(edition, read_bundle(args.custody_bundle,
                                                              filesystem=host.custody_filesystem))
    registry = host.registry_factory()
    bundle = execute_edition(edition, inference, gold, registry, journal,
        authorize=authorize, cancelled=host.cancelled, cost_summary=host.cost_summary,
        economic_allocation=host.economic_allocation, verify_receipt=host.verify_receipt,
        authorize_preflight=preflight_authority)
    by_id = {row.record_id: row.spans for row in gold}
    disposition = write_locked_artifacts(bundle, args.out,
        sources=tuple((record, by_id[record.record_id]) for record in inference))
    emit({**disposition, 'edition_state': bundle['edition_state'], 'corpus_N': bundle['corpus_N']})
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--readiness', action='store_true',
                        help='read-only missing/held scientific prerequisites; never executes')
    parser.add_argument("--edition", choices=("development",))
    parser.add_argument("--validate-lock", type=Path,
                        help="inspect a future lock only; never opens its edition")
    parser.add_argument('--execute-locked', action='store_true')
    parser.add_argument('--launch-bundle', type=Path, help='D5 WorkerLaunchBundle/Handoff; validation is default')
    parser.add_argument('--validate-only', action='store_true')
    parser.add_argument('--execute-campaign', action='store_true')
    parser.add_argument('--inference-export', type=Path)
    parser.add_argument('--gold-export', type=Path)
    parser.add_argument('--inference-export-sha256')
    parser.add_argument('--gold-export-sha256')
    parser.add_argument('--lock', type=Path)
    parser.add_argument('--authorization', type=Path)
    parser.add_argument('--selection-lock', type=Path)
    parser.add_argument('--targets', type=Path)
    parser.add_argument('--custody-bundle', type=Path)
    parser.add_argument('--custody-lifecycle', type=Path)
    parser.add_argument('--journal', type=Path)
    parser.add_argument('--operator-host', help='trusted reviewed module:factory; no host is auto-selected')
    parser.add_argument('--run-timing', action='store_true')
    parser.add_argument('--timing-plan', type=Path)
    parser.add_argument('--timing-resources', type=Path, help='preregistered D5 TimingResourceSchedule; no approval implied')
    parser.add_argument('--timing-out', type=Path)
    parser.add_argument('--view-result', type=Path)
    parser.add_argument('--result-sha256')
    parser.add_argument('--approved-report', type=Path)
    parser.add_argument('--report-sha256')
    parser.add_argument("--arms", choices=("regex", "none"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if sum((args.readiness, bool(args.validate_lock), args.execute_locked, bool(args.view_result), bool(args.edition), bool(args.launch_bundle))) != 1:
        parser.error('choose_exactly_one_mode')
    if args.readiness:
        if any(value is not None and value is not False for key, value in vars(args).items()
               if key != 'readiness'):
            parser.error('readiness_is_nonexecuting_and_takes_no_other_inputs')
        from m7.experiment.readiness import assess_readiness
        emit(assess_readiness().model_dump(mode='json'))
        return 3
    if args.arms is None:
        args.arms = 'none'
    if args.execute_campaign and not args.launch_bundle:
        parser.error('campaign_execution_requires_launch_bundle')
    if (args.run_timing or args.timing_plan or args.timing_resources or args.timing_out) and not args.launch_bundle:
        parser.error('isolated_campaign_timing_required')
    if args.launch_bundle:
        return campaign_mode(args)
    if args.validate_only:
        parser.error('validate_only_is_a_campaign_mode')
    if args.execute_locked:
        return execute_locked(args)
    if args.view_result:
        if args.out is None or not args.result_sha256 or not args.approved_report or not args.report_sha256:
            parser.error('offline_replay_requires_approved_aggregate_and_report_hashes')
        approved_result(args.view_result, args.result_sha256)
        copy_approved_report(args.approved_report, args.report_sha256, args.out)
        emit({'status': 'offline_approved_aggregate_rendered', 'product_acceptance': False})
        return 0
    if args.validate_lock:
        if args.edition or args.out:
            parser.error("lock_validation_is_separate_from_development")
        edition = load_boundary(args.validate_lock, LockedEdition)
        edition.require_current()
        emit({"status": "lock_shaped_not_authorized", "edition_sha256": edition.sha256,
              "corpus_N": len(edition.population), "execution_allowed": False})
        return 0
    if args.edition != "development" or args.out is None:
        parser.error("development_requires_edition_and_out")
    records = development_records()
    adapters = {"regex": lambda record: detect_regex(record, run_id="development")} if args.arms == "regex" else {}
    bundle = run_offline(records, adapters, publication_gate=lambda r, g, v: gate_record(r, g, v).as_dict())
    approved = write_report(bundle, args.out, approve_artifact=lambda document: artifact_is_safe(
        document, tuple((row.record, row.gold) for row in records)))
    emit({"status": "development_report_written" if approved else 'artifacts_suppressed',
          "corpus_N": len(records), "held_out_result": False})
    return 0


if __name__ == "__main__":
    guarded(main)
