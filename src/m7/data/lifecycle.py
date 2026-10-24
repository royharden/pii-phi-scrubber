"""Guarded freeze/seal/release/open/revoke lifecycle, inert until explicitly called."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .corpus import verify_bundle
from .custody_journal import CustodyJournal
from .lifecycle_models import (
    CustodyActionAuthorization, CustodyRelease, FreezeReceipt, OpenReceipt,
    ReleaseAuthorization, RevokeReceipt, SealReceipt, SelectionLockReference, SupersedeReceipt,
)
from .models import BlockAssignment, CorpusBundle, CorpusPlan, FamilyInventory, SealAuthorization
from .provenance import audit_inventory, commitment
from .access import IsolationGuard
from .filesystem import CustodyFilesystem
from .timing_models import TimingPhaseConsumed, TimingPhaseTerminal, validate_timing_transition


def utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('invalid_custody_time') from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('custody_timezone_required')
    return parsed.astimezone(timezone.utc)


def population(bundle: CorpusBundle) -> list[dict[str, str]]:
    selected = {p.record_id for p in bundle.provenance if p.split == 'test'}
    return sorted(({'record_id': r.record_id, 'content_sha256': r.content_sha256}
                   for r in bundle.records if r.record_id in selected), key=lambda r: r['record_id'])


def freeze_binding(inventory: FamilyInventory, plan: CorpusPlan,
                   assignments: tuple[BlockAssignment, ...], *, custodian_id: str,
                   supersedes_edition_id: str | None = None) -> dict:
    """Pure authorization payload. No generation, journal write or approval occurs."""
    audit = audit_inventory(inventory, assignments, plan)
    if audit.status != 'mechanical_only':
        raise ValueError('cannot_freeze_blocked_inventory')
    families = {family.family_id: family for family in inventory.families}
    test_families = [families[f] for block in assignments if block.split == 'test' for f in block.family_ids]
    if any(family.author_id != custodian_id for family in test_families):
        raise ValueError('test_families_must_be_custodian_authored')
    ancestors = {a.ancestor_id: a for a in inventory.ancestors}
    lexicons = {x.lexicon_id: x for x in inventory.lexicons}
    pending = [a for family in test_families for a in family.ancestors]
    pending.extend(lexicons[s.lexicon_id].ancestor_id for family in test_families
                   for recipe in family.recipes for s in recipe.segments if s.lexicon_id is not None)
    seen: set[str] = set()
    while pending:
        identity = pending.pop()
        if identity not in seen:
            seen.add(identity)
            pending.extend(ancestors[identity].parents)
    return {'edition_id': plan.edition_id, 'custodian_id': custodian_id,
            'inventory_sha256': commitment(inventory), 'plan_sha256': commitment(plan),
            'guide_sha256': plan.guide_sha256, 'generator_sha256': plan.generator_sha256,
            'assignments_sha256': commitment(assignments), 'selection_rule_sha256': plan.selection_rule_sha256,
            'family_author_ids': tuple(sorted({family.author_id for family in inventory.families})),
            'test_semantic_source_pins': tuple(sorted({ancestors[a].source_sha256 for a in seen})),
            'split_seed': plan.split_seed, 'sampling_seed': plan.sampling_seed,
            'benign_fraction': plan.benign_fraction, 'challenge_fraction': plan.challenge_fraction,
            'supersedes_edition_id': supersedes_edition_id}


@dataclass
class _State:
    freeze: FreezeReceipt
    seal: SealReceipt | None = None
    release: CustodyRelease | None = None
    opened: OpenReceipt | None = None
    revoked: RevokeReceipt | None = None
    superseded: SupersedeReceipt | None = None

    def require_active(self) -> None:
        if self.revoked is not None or self.superseded is not None:
            raise ValueError('custody_revoked_or_superseded')


def _states(events) -> dict[str, _State]:
    states: dict[str, _State] = {}
    replacements: dict[str, str] = {}
    last_time: datetime | None = None
    timing: dict[str, list] = {}
    for event in events:
        receipt = event.receipt
        field = {FreezeReceipt: 'frozen_at', SealReceipt: 'sealed_at', CustodyRelease: 'released_at',
                 OpenReceipt: 'opened_at', RevokeReceipt: 'revoked_at', SupersedeReceipt: 'superseded_at',
                 TimingPhaseConsumed: 'consumed_at', TimingPhaseTerminal: 'finished_at'}[type(receipt)]
        time = utc(getattr(receipt, field))
        if last_time is not None and time < last_time:
            raise ValueError('custody_event_time_regression')
        last_time = time
        state = states.get(receipt.edition_id)
        if isinstance(receipt, FreezeReceipt):
            if state is not None:
                raise ValueError('edition_id_already_frozen')
            if replacements.get(receipt.edition_id) != receipt.supersedes_edition_id:
                raise ValueError('replacement_edition_reservation_mismatch')
            if receipt.supersedes_edition_id is not None:
                prior = states.get(receipt.supersedes_edition_id)
                if (prior is None or prior.superseded is None
                        or prior.superseded.replacement_edition_id != receipt.edition_id
                        or prior.freeze.inventory_sha256 == receipt.inventory_sha256
                        or set(prior.freeze.test_semantic_source_pins) & set(receipt.test_semantic_source_pins)):
                    raise ValueError('invalid_replacement_inventory')
            states[receipt.edition_id] = _State(freeze=receipt)
            continue
        if state is None:
            raise ValueError('custody_event_without_freeze')
        if isinstance(receipt, (TimingPhaseConsumed, TimingPhaseTerminal)):
            prior = timing.setdefault(receipt.edition_id, [])
            validate_timing_transition(receipt, tuple(prior), release=state.release,
                opened=state.opened, active=state.revoked is None and state.superseded is None)
            prior.append(receipt)
            continue
        if isinstance(receipt, SupersedeReceipt):
            if state.superseded is not None or receipt.replacement_edition_id == receipt.edition_id:
                raise ValueError('edition_already_superseded')
            if receipt.replacement_edition_id in states or receipt.replacement_edition_id in replacements:
                raise ValueError('replacement_edition_already_exists')
            state.superseded = receipt
            replacements[receipt.replacement_edition_id] = receipt.edition_id
            continue
        state.require_active()
        if isinstance(receipt, SealReceipt):
            if state.seal is not None or receipt.freeze_sha256 != commitment(state.freeze):
                raise ValueError('invalid_or_repeated_custody_seal')
            state.seal = receipt
        elif isinstance(receipt, CustodyRelease):
            if (state.seal is None or state.release is not None
                    or receipt.freeze_sha256 != commitment(state.freeze)
                    or receipt.seal_sha256 != commitment(state.seal)
                    or receipt.corpus_manifest_sha256 != state.seal.corpus_manifest_sha256
                    or receipt.population_sha256 != state.seal.population_sha256
                    or receipt.independent_audit_sha256 != state.seal.independent_audit_sha256
                    or receipt.custodian_id != state.freeze.custodian_id
                    or utc(receipt.expires_at) <= time):
                raise ValueError('invalid_or_repeated_custody_release')
            state.release = receipt
        elif isinstance(receipt, OpenReceipt):
            if (state.release is None or state.opened is not None
                    or receipt.run_id != state.release.run_id
                    or receipt.custody_release_sha256 != commitment(state.release)
                    or time >= utc(state.release.expires_at)):
                raise ValueError('invalid_or_repeated_custody_open')
            state.opened = receipt
        elif isinstance(receipt, RevokeReceipt):
            state.revoked = receipt
        else:
            raise ValueError('unknown_custody_transition')
    return states


class CustodyLifecycle:
    """Trusted host supplies current, issuer-authenticated receipt verification.

    Digest shape is insufficient. The callback must authenticate exact contents,
    issuer, action scope and current revocation from an external trusted store.
    No permissive callback/default is provided. This journal is not that store.
    """
    def __init__(self, root: Path, *, verify_receipt: Callable[[str, str], bool],
                 clock: Callable[[], datetime] | None = None,
                 filesystem: CustodyFilesystem | None = None,
                 isolation_guard: IsolationGuard | None = None):
        self.journal = CustodyJournal(root, filesystem=filesystem)
        self.filesystem, self.isolation_guard = filesystem, isolation_guard
        self.verifier = verify_receipt
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> str:
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError('custody_timezone_required')
        return now.astimezone(timezone.utc).isoformat()

    def _verify(self, kind: str, digest: str) -> None:
        if self.verifier(kind, digest) is not True:
            raise ValueError('custody_receipt_not_authenticated_or_revoked')

    def _current(self, issued: str, expires: str) -> None:
        if not utc(issued) <= utc(self._now()) < utc(expires):
            raise ValueError('custody_authorization_not_current')

    def _action(self, authorization: CustodyActionAuthorization, edition_id: str,
                action: str, binding: dict) -> None:
        if (authorization.edition_id != edition_id or authorization.action != action
                or authorization.binding_sha256 != commitment(binding)):
            raise ValueError('custody_action_binding_mismatch')
        self._current(authorization.issued_at, authorization.expires_at)
        self._verify('custody_' + action + '_authorization', commitment(authorization))

    def _commit(self, receipt, events):
        # Replay the proposed transition before persistence; never mutate old bytes.
        from .lifecycle_models import CustodyEvent
        event = CustodyEvent(sequence=len(events) + 1,
            previous_sha256=commitment(events[-1]) if events else '0' * 64, receipt=receipt)
        _states((*events, event))
        self.journal.append(receipt, events)
        return receipt

    def freeze(self, inventory: FamilyInventory, plan: CorpusPlan,
               assignments: tuple[BlockAssignment, ...], *, custodian_id: str,
               authorization: CustodyActionAuthorization,
               supersedes_edition_id: str | None = None) -> FreezeReceipt:
        core = freeze_binding(inventory, plan, assignments, custodian_id=custodian_id,
                              supersedes_edition_id=supersedes_edition_id)
        with self.journal.writer():
            events = self.journal.events()
            self._action(authorization, plan.edition_id, 'freeze', core)
            receipt = FreezeReceipt(**core, authorization_sha256=commitment(authorization), frozen_at=self._now())
            return self._commit(receipt, events)

    def validate_seal_inputs(self, inventory: FamilyInventory, plan: CorpusPlan,
                             assignments: tuple[BlockAssignment, ...], authorization: SealAuthorization) -> None:
        """Call BEFORE any held-out generation; freeze and authentic grant required."""
        with self.journal.writer():
            state = _states(self.journal.events()).get(plan.edition_id)
            if state is None:
                raise ValueError('freeze_required_before_generation')
            state.require_active()
            f = state.freeze
            if (f.inventory_sha256 != commitment(inventory) or f.plan_sha256 != commitment(plan)
                    or f.assignments_sha256 != commitment(assignments)
                    or f.custodian_id != authorization.custodian_id
                    or authorization.edition_id != f.edition_id
                    or authorization.inventory_sha256 != f.inventory_sha256
                    or authorization.plan_sha256 != f.plan_sha256):
                raise ValueError('generation_inputs_differ_from_freeze')
            if state.seal is not None:
                raise ValueError('edition_already_sealed_do_not_regenerate')
            self._seal_authority(state, authorization)

    def _seal_authority(self, state: _State, authorization: SealAuthorization) -> None:
        if utc(authorization.expires_at) <= utc(self._now()):
            raise ValueError('seal_authorization_expired')
        implementers = set(authorization.implementation_author_ids)
        if (authorization.custodian_id in implementers
                or authorization.independent_auditor_id in
                   implementers | set(state.freeze.family_author_ids) | {authorization.custodian_id}):
            raise ValueError('custody_seal_role_conflict')
        self._verify('custody_seal_authorization', commitment(authorization))
        self._verify('custody_approval', authorization.approval_receipt_sha256)
        self._verify('independent_audit', authorization.independent_audit_receipt_sha256)

    def seal(self, bundle: CorpusBundle, *, authorization: SealAuthorization) -> SealReceipt:
        verify_bundle(bundle)
        if bundle.manifest.scope != 'custodian_sealed':
            raise ValueError('development_bundle_not_sealable')
        with self.journal.writer():
            events = self.journal.events()
            state = _states(events).get(bundle.manifest.edition_id)
            if state is None:
                raise ValueError('freeze_required_before_seal')
            state.require_active()
            f, m = state.freeze, bundle.manifest
            if (authorization.edition_id != f.edition_id or authorization.custodian_id != f.custodian_id
                    or authorization.plan_sha256 != f.plan_sha256 or authorization.inventory_sha256 != f.inventory_sha256
                    or m.inventory_sha256 != f.inventory_sha256 or m.plan_sha256 != f.plan_sha256
                    or m.guide_sha256 != f.guide_sha256 or m.generator_sha256 != f.generator_sha256
                    or m.assignments_sha256 != f.assignments_sha256):
                raise ValueError('sealed_bundle_differs_from_freeze')
            self._seal_authority(state, authorization)
            if state.seal is not None:
                if (state.seal.corpus_manifest_sha256 == commitment(m)
                        and state.seal.authorization_sha256 == commitment(authorization)):
                    return state.seal
                raise ValueError('edition_already_sealed_with_different_inputs')
            rows = population(bundle)
            return self._commit(SealReceipt(edition_id=f.edition_id, freeze_sha256=commitment(f),
                corpus_manifest_sha256=commitment(m), population_sha256=commitment(rows),
                intended_test_records=len(rows), independent_audit_sha256=authorization.independent_audit_receipt_sha256,
                authorization_sha256=commitment(authorization), sealed_at=self._now()), events)

    def release(self, edition_id: str, *, selection_lock: SelectionLockReference,
                authorization: ReleaseAuthorization) -> CustodyRelease:
        with self.journal.writer():
            events = self.journal.events()
            state = _states(events).get(edition_id)
            if state is None or state.seal is None:
                raise ValueError('sealed_edition_required')
            state.require_active()
            seal, freeze = state.seal, state.freeze
            isolation = self._isolation(edition_id, seal.corpus_manifest_sha256)
            self._current(authorization.issued_at, authorization.expires_at)
            if (authorization.edition_id != edition_id or authorization.custodian_id != freeze.custodian_id
                    or authorization.corpus_manifest_sha256 != seal.corpus_manifest_sha256
                    or authorization.population_sha256 != seal.population_sha256
                    or authorization.selection_lock_sha256 != selection_lock.receipt_sha256
                    or authorization.independent_audit_sha256 != seal.independent_audit_sha256
                    or authorization.isolation_capability_sha256 != isolation.capability_sha256
                    or utc(authorization.expires_at) > utc(self.isolation_guard.capability.expires_at)
                    or selection_lock.edition_id != edition_id
                    or selection_lock.corpus_manifest_sha256 != seal.corpus_manifest_sha256
                    or selection_lock.selection_rule_sha256 != freeze.selection_rule_sha256
                    or not utc(freeze.frozen_at) <= utc(selection_lock.locked_at) <= utc(authorization.issued_at)):
                raise ValueError('pre_test_lock_or_release_binding_mismatch')
            for kind, digest in (
                ('custody_release_authorization', commitment(authorization)),
                ('pre_test_selection_lock', selection_lock.receipt_sha256),
                ('pre_test_lock_binding', commitment(selection_lock)),
                ('independent_audit', seal.independent_audit_sha256),
            ):
                self._verify(kind, digest)
            receipt = CustodyRelease(edition_id=edition_id, run_id=authorization.run_id,
                experiment_plan_sha256=authorization.experiment_plan_sha256,
                freeze_sha256=commitment(freeze), seal_sha256=commitment(seal),
                corpus_manifest_sha256=seal.corpus_manifest_sha256, population_sha256=seal.population_sha256,
                selection_lock_sha256=selection_lock.receipt_sha256,
                selection_lock_reference_sha256=commitment(selection_lock),
                independent_audit_sha256=seal.independent_audit_sha256, authorization_sha256=commitment(authorization),
                isolation_capability_sha256=isolation.capability_sha256,
                filesystem_policy_sha256=isolation.filesystem_policy_sha256,
                worker_policy_sha256=isolation.worker_policy_sha256,
                custodian_id=freeze.custodian_id, released_at=self._now(), expires_at=authorization.expires_at)
            return self._commit(receipt, events)

    def release_from_training_lock(self, lock, *, selection: dict, parity: dict,
                                    justification: dict, approval,
                                    authorization: ReleaseAuthorization) -> CustodyRelease:
        """Use D5's canonical verification/projection, never duplicate selection logic."""
        from m7.training.locking import selection_lock_reference, verify_pre_test_lock
        verify_pre_test_lock(lock, selection=selection, parity=parity, justification=justification,
                             approval=approval, verify_receipt=self.verifier, clock=self.clock)
        if (authorization.edition_id != lock.edition_id
                or authorization.experiment_plan_sha256 != lock.experiment_plan_sha256
                or utc(authorization.expires_at) > utc(lock.expires_at)):
            raise ValueError('training_lock_release_binding_mismatch')
        return self.release(lock.edition_id, selection_lock=selection_lock_reference(lock),
                            authorization=authorization)

    def _isolation(self, edition_id: str, manifest_sha256: str):
        if self.isolation_guard is None or self.filesystem is None:
            raise ValueError('authenticated_actual_isolation_required')
        return self.isolation_guard.require_current(edition_id, manifest_sha256,
            filesystem_policy_sha256=self.filesystem.sha256)

    def _release_current(self, state: _State) -> CustodyRelease:
        state.require_active()
        release = state.release
        if release is None or utc(release.expires_at) <= utc(self._now()):
            raise ValueError('current_custody_release_required')
        isolation = self._isolation(release.edition_id, release.corpus_manifest_sha256)
        if (isolation.capability_sha256 != release.isolation_capability_sha256
                or isolation.filesystem_policy_sha256 != release.filesystem_policy_sha256
                or isolation.worker_policy_sha256 != release.worker_policy_sha256):
            raise ValueError('release_isolation_binding_mismatch')
        for kind, digest in (
            ('custody_release_authorization', release.authorization_sha256),
            ('pre_test_selection_lock', release.selection_lock_sha256),
            ('pre_test_lock_binding', release.selection_lock_reference_sha256),
            ('independent_audit', release.independent_audit_sha256),
        ):
            self._verify(kind, digest)
        return release

    def _match_edition(self, edition: Any, state: _State) -> CustodyRelease:
        release = self._release_current(state)
        if (edition.run_id != release.run_id or edition.plan_sha256 != release.experiment_plan_sha256
                or edition.corpus_manifest_sha256 != release.corpus_manifest_sha256
                or edition.custody_release_sha256 != commitment(release)
                or edition.independent_audit_sha256 != release.independent_audit_sha256
                or edition.selection_lock_sha256 != release.selection_lock_sha256
                or commitment([r.model_dump(mode='json') for r in edition.population]) != release.population_sha256
                or utc(edition.expires_at) > utc(release.expires_at)):
            raise ValueError('locked_edition_custody_mismatch')
        edition.require_current(self.clock())
        if state.opened is not None and state.opened.locked_edition_sha256 != edition.sha256:
            raise ValueError('edition_already_opened_with_other_fingerprint')
        return release

    def require_released(self, edition: Any) -> CustodyRelease:
        """Authenticate delivery channels without consuming the execution open."""
        with self.journal.writer():
            state = _states(self.journal.events()).get(edition.edition_id)
            if state is None:
                raise ValueError('unknown_custody_edition')
            return self._match_edition(edition, state)

    def require_training_export(self, bundle: CorpusBundle) -> None:
        """Sealed corpus labels may leave custody only before test release/open."""
        with self.journal.writer():
            state = _states(self.journal.events()).get(bundle.manifest.edition_id)
            if state is None or state.seal is None:
                raise ValueError('sealed_custody_required_for_training_export')
            state.require_active()
            if state.release is not None or state.opened is not None:
                raise ValueError('training_export_closed_after_pre_test_release')
            if commitment(bundle.manifest) != state.seal.corpus_manifest_sha256:
                raise ValueError('training_export_corpus_mismatch')

    def authorize_open(self, edition: Any, resume: bool) -> OpenReceipt:
        """D7 protocol: open once; only an already-open D7 journal may resume.

        A crash between D4/D7 open markers fails closed, requiring explicit custody
        investigation. A fresh journal cannot masquerade as a first open again.
        D7's cell journal owns physical-call at-most-once accounting within a run.
        """
        with self.journal.writer():
            events = self.journal.events()
            state = _states(events).get(edition.edition_id)
            if state is None:
                raise ValueError('unknown_custody_edition')
            release = self._match_edition(edition, state)
            if state.opened is not None:
                if state.opened.locked_edition_sha256 != edition.sha256:
                    raise ValueError('edition_already_opened_with_other_fingerprint')
                if not resume:
                    raise ValueError('custody_already_opened_investigate_original_journal')
                return state.opened
            if resume:
                raise ValueError('cannot_resume_unopened_custody')
            return self._commit(OpenReceipt(edition_id=edition.edition_id, run_id=edition.run_id,
                locked_edition_sha256=edition.sha256, custody_release_sha256=commitment(release),
                opened_at=self._now()), events)

    def evaluation_gate(self, authority: Callable[[Any, bool], None]) -> Callable[[Any, bool], None]:
        """Compose D7 ReceiptAuthority first, then consume this custody open-once gate."""
        def authorize(edition: Any, resume: bool) -> None:
            authority(edition, resume)
            self.authorize_open(edition, resume)
        return authorize

    def verify_release_receipt(self, kind: str, digest: str) -> bool:
        """D7 verifier adapter. Delegate other receipt types to the trusted host."""
        if kind != 'custody_release':
            return self.verifier(kind, digest) is True
        with self.journal.writer():
            states = _states(self.journal.events())
            matches = [s for s in states.values() if s.release and commitment(s.release) == digest]
            if len(matches) != 1:
                return False
            self._release_current(matches[0])
            return True

    def revoke(self, edition_id: str, *, reason_code: str,
               authorization: CustodyActionAuthorization) -> RevokeReceipt:
        with self.journal.writer():
            events = self.journal.events()
            if edition_id not in _states(events):
                raise ValueError('unknown_custody_edition')
            self._action(authorization, edition_id, 'revoke', {'edition_id': edition_id, 'reason_code': reason_code})
            return self._commit(RevokeReceipt(edition_id=edition_id, reason_code=reason_code,
                authorization_sha256=commitment(authorization), revoked_at=self._now()), events)

    def supersede(self, edition_id: str, replacement_edition_id: str, *,
                  authorization: CustodyActionAuthorization) -> SupersedeReceipt:
        with self.journal.writer():
            events = self.journal.events()
            if edition_id not in _states(events):
                raise ValueError('unknown_custody_edition')
            binding = {'edition_id': edition_id, 'replacement_edition_id': replacement_edition_id}
            self._action(authorization, edition_id, 'supersede', binding)
            return self._commit(SupersedeReceipt(**binding, authorization_sha256=commitment(authorization),
                                               superseded_at=self._now()), events)

    def inspect(self) -> dict:
        """Read-only mechanical snapshot; concurrent partial append fails closed."""
        events = self.journal.events()
        states = _states(events)
        rows = []
        for identity, state in sorted(states.items()):
            phase = ('superseded' if state.superseded else 'revoked' if state.revoked else
                     'opened' if state.opened else 'released' if state.release else
                     'sealed' if state.seal else 'frozen')
            rows.append({'edition_id': identity, 'phase': phase,
                         'freeze_sha256': commitment(state.freeze),
                         'seal_sha256': commitment(state.seal) if state.seal else None,
                         'release_sha256': commitment(state.release) if state.release else None,
                         'intended_test_records': state.seal.intended_test_records if state.seal else None,
                         'timing': self._timing_inventory(events, identity)})
        return {'schema_version': 'CustodyInspection/v1', 'event_count': len(events), 'editions': rows,
                'independent_verdict_issued': False}

    @staticmethod
    def _timing_inventory(events, edition_id: str) -> dict:
        receipts = [e.receipt for e in events if e.receipt.edition_id == edition_id]
        starts = [r for r in receipts if isinstance(r, TimingPhaseConsumed)]
        ends = {r.consumed_sha256: r for r in receipts if isinstance(r, TimingPhaseTerminal)}
        return {'status': 'mechanical_only_not_authorization', 'fixed_passes_per_arm': 3,
                'arms': [{'arm': arm, 'consumed_ordinals': [r.ordinal for r in starts if r.arm == arm],
                    'completed_ordinals': [r.ordinal for r in starts if r.arm == arm
                        and commitment(r) in ends and ends[commitment(r)].outcome == 'completed'],
                    'aborted_ordinals': [r.ordinal for r in starts if r.arm == arm
                        and commitment(r) in ends and ends[commitment(r)].outcome == 'aborted'],
                    'uncertain_ordinals': [r.ordinal for r in starts if r.arm == arm
                        and commitment(r) not in ends]}
                    for arm in ('regex', 'frontier', 'base', 'finetuned')]}
