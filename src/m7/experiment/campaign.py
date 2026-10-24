"""D5 joined launch bundle -> D4 channels -> D6 isolated sessions -> safe report.

No function is invoked on import. Validation is the default CLI behavior; actual
execution requires explicit activation and externally enforced native controls.
"""
from __future__ import annotations

from pathlib import Path
import os
from typing import TYPE_CHECKING

from .activation import policy_from_selection_lock
from .authorization import EvaluationAuthorization, ReceiptAuthority
from .costing import cost_report, merge_cost_authorizations
from .executor import execute_edition
from .isolated import IsolatedCampaignHost, IsolatedRegistry, validate_definitions
from .journal import EditionJournal
from .models import LockedEdition, canonical, commitment
from .released import read_released_channels
from .timing_contracts import IsolatedTimingPlan
from .isolated_timing import (primary_accounting, retained_timing_identities,
                             run_isolated_timing, validate_timing_plan, validate_timing_records)
from .adoption import adoption_report

if TYPE_CHECKING:
    from m7.training.launch_bundle import WorkerLaunchBundle
    from m7.training.timing_resources import TimingResourceSchedule


class CampaignPrerequisiteError(ValueError):
    """Safe fixed diagnostics; never expose model/validation/native exception text."""
    def __init__(self, code: str):
        allowed = {'native_campaign_host_required', 'campaign_prelaunch_qualification_unavailable',
                   'released_channels_unavailable_or_changed', 'worker_or_journal_unavailable',
                   'owned_worker_cleanup_unverified'}
        self.code = code if code in allowed else 'campaign_prelaunch_qualification_unavailable'
        super().__init__(self.code)


def validate_campaign_inputs(bundle: WorkerLaunchBundle, edition: LockedEdition,
                              authorization: EvaluationAuthorization) -> dict:
    """Pure structural join. No host import, receipt query, files, DB or worker."""
    from m7.training.launch_bundle import d7_worker_definitions, validate_campaign_edition
    result = validate_campaign_edition(bundle, edition)
    spec = bundle.campaign
    ReceiptAuthority.validate_binding(authorization, edition)
    definitions = d7_worker_definitions(bundle)
    launches = {arm: membership.launch_sha256 for arm, membership in bundle.memberships.items()}
    validate_definitions(edition, spec.worker_profile, definitions, launches)
    return {**result, 'status': 'campaign_edition_structure_valid_not_authorized',
            'edition_sha256': edition.sha256, 'runtime_executed': False,
            'heldout_channels_read': False, 'worker_started': False}


def _accounting(bundle: WorkerLaunchBundle, host: IsolatedCampaignHost, *, spend_guard: bool) -> dict:
    spec = bundle.campaign
    training = host.training_summary()
    if (training.get('training_run_closeout_sha256') != spec.selected.training_run_closeout_sha256
            or host.verify_receipt('training_accounting_snapshot', commitment(training)) is not True):
        raise ValueError('training_accounting_not_bound_to_campaign')
    training_report = cost_report(training)
    declared_training = spec.budget.prior_known_training_cash_micros + spec.budget.prior_unknown_training_liability_micros
    current_training = training_report['known_provider_cash_micros'] + training_report['unresolved_liability_micros']
    if spend_guard and current_training > declared_training:
        raise ValueError('training_liability_requires_new_campaign_authority')
    summaries = [training]
    live_over_cap = False
    for arm in ('base', 'finetuned', 'frontier'):
        ledger = host.ledgers[arm]
        allocation = spec.budget.allocations[arm]
        if ledger.authorization_id != allocation.authorization_id or ledger.cap != allocation.cash_cap_micros:
            raise ValueError('campaign_parent_ledger_allocation_mismatch')
        snapshot = ledger.summary()
        live_over_cap = live_over_cap or cost_report(snapshot)['over_cap']
        summaries.append(snapshot)
    total = merge_cost_authorizations(tuple(summaries), currency=spec.budget.currency)
    # The campaign cap includes actual/unknown historical training plus separately
    # authorized inference allocations, not the unused original training cap.
    total['cap_micros'] = spec.budget.total_authorized_cash_micros
    total['remaining_micros'] = max(0, total['cap_micros'] - total['known_provider_cash_micros']
                                     - total['unresolved_liability_micros'])
    total['scope_complete'] = True
    if spend_guard and (live_over_cap or
            total['known_provider_cash_micros'] + total['unresolved_liability_micros'] > total['cap_micros']):
        raise ValueError('campaign_cash_authority_exhausted')
    return total


def execute_isolated_campaign(bundle: WorkerLaunchBundle, edition: LockedEdition,
                               authorization: EvaluationAuthorization, *, host: IsolatedCampaignHost,
                               lifecycle_root: Path, journal_directory: Path,
                               inference_directory: Path, gold_directory: Path,
                               inference_export_sha256: str, gold_export_sha256: str,
                               artifact_directory: Path, timing_plan: IsolatedTimingPlan | None = None,
                               timing_directory: Path | None = None,
                               timing_resources: TimingResourceSchedule | None = None) -> dict:
    """Explicit future activation. Native launcher/verifiers cannot be omitted.

    Reads separately committed D4 exports only after current release checks. Raw
    custody/training paths and ledgers are never sent through the worker protocol.
    Full-L exact process proof is D6's responsibility before init/messages; D4's
    prepared-profile qualification does not require an already-running process.
    """
    from m7.data.lifecycle import CustodyLifecycle
    from m7.training.campaign import CampaignHost
    from m7.training.launch_bundle import d7_worker_definitions, prepare_launch_bundle
    from m7.publish import write_locked_artifacts
    validate_campaign_inputs(bundle, edition, authorization)
    if timing_plan is not None:
        from m7.training.timing_resources import validate_timing_resources
        validate_timing_plan(edition, timing_plan)
        if (timing_directory is None or timing_resources is None or host.timing_authority_factory is None
                or not callable(host.warm_attestor)):
            raise ValueError('explicit_isolated_timing_authority_and_directory_required')
        validate_timing_resources(bundle, timing_plan, timing_resources)
        if any(bootstrap.timing_plan_sha256 != timing_plan.sha256 or
               bootstrap.timing_order_sha256 != timing_plan.order_sha256
               for bootstrap in bundle.bootstraps.values()):
            raise ValueError('timing_bootstrap_pins_must_precede_primary')
    elif timing_directory is not None:
        raise ValueError('timing_directory_requires_locked_plan')
    if (not isinstance(host, IsolatedCampaignHost) or host.launcher is None or host.process_verifier is None
            or host.isolation_guard is None or host.custody_filesystem is None
            or set(host.ledgers) != {'base', 'finetuned', 'frontier'}):
        raise CampaignPrerequisiteError('native_campaign_host_required')
    try:
        prepared = prepare_launch_bundle(bundle,
            host=CampaignHost(verify_receipt=host.verify_receipt, isolation_guard=host.isolation_guard))
    except Exception:
        raise CampaignPrerequisiteError('campaign_prelaunch_qualification_unavailable') from None
    bundle = prepared.bundle  # Fresh canonical snapshot, not mutable caller maps.
    spec, resources = bundle.campaign, bundle.campaign.resources
    profile_digest = prepared.receipt.profile_sha256
    if timing_plan is not None:
        if host.verify_receipt('timing_resource_schedule', timing_resources.sha256) is not True:
            raise ValueError('timing_complete_campaign_cap_not_authorized')
    if (profile_digest != resources.worker_policy_sha256
            or host.custody_filesystem.sha256 != resources.filesystem_policy_sha256
            or host.isolation_guard.sha256 != resources.isolation_capability_sha256):
        raise ValueError('campaign_profile_filesystem_capability_mismatch')
    host.isolation_guard.require_current(edition.edition_id, edition.corpus_manifest_sha256,
        filesystem_policy_sha256=resources.filesystem_policy_sha256, worker_policy_sha256=profile_digest)
    custody = CustodyLifecycle(lifecycle_root, verify_receipt=host.verify_receipt,
        filesystem=host.custody_filesystem, isolation_guard=host.isolation_guard)
    authority = ReceiptAuthority(authorization, verify_receipt=custody.verify_release_receipt)
    policy_from_selection_lock(edition, spec.selection_lock, spec.targets, verify_receipt=host.verify_receipt)

    def pre_channel_authority(candidate, resume):
        authority(candidate, resume)
        release = custody.require_released(candidate)  # NEVER consumes open.
        if (release.worker_policy_sha256 != profile_digest
                or release.filesystem_policy_sha256 != resources.filesystem_policy_sha256
                or release.isolation_capability_sha256 != resources.isolation_capability_sha256):
            raise ValueError('campaign_profile_differs_from_custody_release')
        for kind, digest in (
            ('worker_launch_bundle', bundle.sha256), ('campaign_spec', spec.sha256),
            ('campaign_cash_authorization', resources.cost_authorization_sha256),
            ('license_packet', resources.local_license_packet_sha256),
            ('local_inference_license', resources.local_inference_license_receipt_sha256),
            ('local_hardware', resources.local_hardware_receipt_sha256),
            ('provider_license', resources.provider_license_receipt_sha256),
            ('provider_resource', resources.provider_resource_receipt_sha256),
            ('provider_terms', resources.provider_terms_sha256),
        ):
            if host.verify_receipt(kind, digest) is not True:
                raise ValueError('campaign_resource_or_bundle_revoked')

    pre_channel_authority(edition, False)
    journal = EditionJournal(journal_directory, filesystem=host.custody_filesystem)
    marker = host.custody_filesystem.require_path('evaluator', journal_directory / 'campaign-cleanup-unverified.json',
                                                 must_exist=False)
    if marker.exists():
        raise ValueError('prior_worker_cleanup_requires_investigation')
    with journal.writer():
        journal.seal(edition)
        replay = journal.closed
        if timing_plan is not None and journal.opened:
            raise ValueError('warm_timing_requires_original_live_primary_scope')
        stores = []
        paths = set()
        for arm, ledger in sorted(host.ledgers.items()):
            allocation = spec.budget.allocations[arm]
            if ledger.authorization_id != allocation.authorization_id or ledger.cap != allocation.cash_cap_micros:
                raise ValueError('campaign_parent_ledger_allocation_mismatch')
            path = host.custody_filesystem.require_path('evaluator', Path(ledger.path), must_exist=False)
            if path in paths:
                raise ValueError('campaign_ledger_path_alias')
            paths.add(path)
            stores.append({'arm': arm, 'authorization_id': ledger.authorization_id,
                           'cap_micros': ledger.cap, 'path': str(path)})
        # Private identity binding, NOT another financial store or billing receipt.
        # A resume cannot silently reset a spent authorization in a fresh database.
        binding_path = host.custody_filesystem.require_path('evaluator', journal_directory / 'campaign-ledgers.json',
                                                           must_exist=False)
        binding = canonical({'schema_version': 'CampaignLedgerBinding/v1',
                             'bundle_sha256': bundle.sha256, 'stores': stores})
        try:
            with binding_path.open('xb') as handle:
                handle.write(binding)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            with binding_path.open('rb') as handle:
                existing_binding = handle.read(len(binding) + 1)
            if existing_binding != binding:
                raise ValueError('campaign_ledger_store_changed_investigate') from None
    # All mutable DB setup is below actual external approval, never validation.
    if not replay:
        for ledger in host.ledgers.values():
            ledger.initialize()
        _accounting(bundle, host, spend_guard=True)
    try:
        records, gold = read_released_channels(edition, filesystem=host.custody_filesystem,
            inference_directory=inference_directory, gold_directory=gold_directory,
            inference_export_sha256=inference_export_sha256, gold_export_sha256=gold_export_sha256,
            verify_receipt=host.verify_receipt)
        if timing_plan is not None:
            validate_timing_records(edition, records, timing_plan)
    except Exception:
        raise CampaignPrerequisiteError('released_channels_unavailable_or_changed') from None

    def revalidate():
        pre_channel_authority(edition, True)
        _accounting(bundle, host, spend_guard=True)

    definitions = d7_worker_definitions(prepared.bundle)
    launch_digests = prepared.receipt.launch_sha256_by_arm
    registry = IsolatedRegistry(edition, spec.worker_profile, definitions, launch_digests,
                               host=host, revalidate=revalidate)
    cleanup = {}
    try:
        result = execute_edition(edition, records, gold, registry.bindings, journal,
            authorize=custody.evaluation_gate(authority), authorize_preflight=pre_channel_authority,
            cancelled=host.cancelled, cost_summary=lambda: _accounting(bundle, host, spend_guard=False),
            economic_allocation=host.economic_allocation, verify_receipt=host.verify_receipt)
        if timing_plan is not None:
            # Primary quality is frozen before continuation. Costs remain live:
            # timing reservations/unknown liabilities must enter campaign totals.
            quality = {key: result[key] for key in ('arms', 'paired', 'paired_fine_minus_base',
                                                   'edition_state', 'corpus_digest', 'corpus_N')}
            with journal.writer():
                journal.seal(edition)
                primary = primary_accounting(edition, journal, quality)
            identities = retained_timing_identities(registry, timing_plan, host.verify_receipt)
            continuation = host.timing_authority_factory(custody=custody, bundle=bundle,
                edition=edition, primary=primary, plan=timing_plan, resources=timing_resources,
                identities=dict(identities))
            from m7.data.timing import CustodyTimingAuthority
            from m7.data.timing_native import WindowsTimingProcessGuard
            from m7.training.timing_resources import TimingResourceAuthority
            if (not isinstance(continuation, CustodyTimingAuthority) or continuation.lifecycle is not custody
                    or continuation.edition != edition):
                raise ValueError('canonical_original_custody_timing_authority_required')
            process_guard = continuation.verify_process
            if (not isinstance(process_guard, WindowsTimingProcessGuard)
                    or process_guard.lifecycle is not custody or process_guard.verifier is not host.process_verifier
                    or process_guard.policies != spec.launch_policies):
                raise ValueError('canonical_exact_native_timing_guard_required')
            resource_authority = continuation.resources
            actual_identities = {arm: commitment(row.model_dump(mode='json')) for arm, row in identities.items()}
            custody_identities = {row.arm: row.identity_sha256 for row in continuation.authorization.backends}
            if (not isinstance(resource_authority, TimingResourceAuthority)
                    or resource_authority.bundle.sha256 != bundle.sha256
                    or resource_authority.schedule != timing_resources
                    or resource_authority.authorization.warm_identity_sha256_by_arm != actual_identities
                    or custody_identities != actual_identities):
                raise ValueError('timing_authorities_require_exact_actual_survivor_set')
            if not all(callable(getattr(continuation, method, None))
                       for method in ('prepare', 'authorize', 'current', 'finish', 'verify_receipt')):
                raise ValueError('authenticated_timing_continuation_adapter_required')
            result['timing'] = run_isolated_timing(edition, records, timing_plan, registry,
                primary, journal=journal, authority=continuation, destination=timing_directory,
                identities=identities, verify_receipt=host.verify_receipt, cancelled=host.cancelled)
            if commitment(quality) != primary.quality_sha256:
                raise ValueError('primary_quality_changed_during_timing')
            result['primary_accounting_sha256'] = primary.sha256
            result['cost'] = cost_report(_accounting(bundle, host, spend_guard=False), host.economic_allocation)
            result['adoption'] = adoption_report(result, edition.adoption_policy)
    except Exception:
        raise CampaignPrerequisiteError('worker_or_journal_unavailable') from None
    finally:
        cleanup = registry.close()
        if any(status not in ('closed', 'not_started') for status in cleanup.values()):
            # Persist only statuses/commitments, never process handles or input.
            with marker.open('xb') as handle:
                handle.write(canonical({'bundle_sha256': bundle.sha256, 'cleanup_unverified': True}))
                handle.flush()
                os.fsync(handle.fileno())
    if any(status not in ('closed', 'not_started') for status in cleanup.values()):
        raise CampaignPrerequisiteError('owned_worker_cleanup_unverified')
    truth = {row.record_id: row.spans for row in gold}
    disposition = write_locked_artifacts(result, artifact_directory,
        sources=tuple((record, truth[record.record_id]) for record in records))
    complete = all(row['attempted_N'] == result['corpus_N'] and not row['attempt_metadata_missing_N']
                   and not row['interrupted_unknown_N'] for row in result['arms'])
    return {**disposition, 'campaign_sha256': spec.sha256, 'bundle_sha256': bundle.sha256,
            'worker_profile_sha256': profile_digest, 'edition_state': result['edition_state'],
            'comparison_status': 'fully_attempted' if complete else 'incomplete_or_unknown',
            'adoption_status': result['adoption']['status'],
            'timing_status': ('not_requested' if timing_plan is None else 'measured' if
                all(a['status'] == 'measured' for a in result['timing']['arms']) else 'unavailable_or_partial'),
            'worker_cleanup': 'closed' if not replay else 'no_worker_started_replay',
            'product_acceptance': False}


__all__ = ['CampaignPrerequisiteError', 'validate_campaign_inputs', 'execute_isolated_campaign']
