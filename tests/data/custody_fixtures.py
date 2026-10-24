"""Test-only custody scaffolding: original fictional inventories, tmp_path roots, an allowlist host.

The trusted-host verifier is an explicit allowlist of (kind, digest) pairs the test approves;
anything not registered fails. Nothing here touches a real ACL, process, model or network.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import sys
from pathlib import Path

from pydantic import BaseModel

from m7.data.access import IsolationCapability, IsolationGuard, IsolationRequest
from m7.data.filesystem import CustodyFilesystem, CustodyPathPolicy, FilesystemPolicyApproval
from m7.data.lifecycle_models import CustodyActionAuthorization, ReleaseAuthorization, SelectionLockReference
from m7.data.models import (
    Ancestor, BlockAssignment, CorpusPlan, Family, FamilyInventory, Lexicon, Recipe, SealAuthorization, Segment,
)
from m7.data.provenance import commitment

T0 = datetime(2030, 1, 1, tzinfo=timezone.utc)
T0_TEXT = '2030-01-01T00:00:00Z'
ISSUED = '2020-01-01T00:00:00Z'
EXPIRES = '2031-01-01T00:00:00Z'
FAR = '2099-01-01T00:00:00Z'
CUSTODIAN, DEV_AUTHOR, IMPLEMENTER, AUDITOR = 'custodian-1', 'dev-author-1', 'impl-1', 'auditor-1'
RECORDS_PER_BLOCK = 20  # benign = ceil(20 * 0.2) = 4, entity records = 16 per block


def digest(text: str) -> str:
    """Opaque test input digests (not expected values)."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class TrustedHost:
    def __init__(self):
        self.approved: set[tuple[str, str]] = set()

    def approve(self, kind: str, value: str) -> None:
        self.approved.add((kind, value))

    def __call__(self, kind: str, value: str) -> bool:
        return (kind, value) in self.approved


class BindingVerifier:
    """Stands in for the trusted platform check: only an exactly bound request passes."""

    def verify(self, capability, request) -> bool:
        return all(getattr(capability, f) == getattr(request, f)
                   for f in ('edition_id', 'corpus_manifest_sha256', 'filesystem_policy_sha256',
                             'worker_policy_sha256'))


def family(index: int, *, split: str, generation: str = 'g1'):
    """One family = its own semantic component: unique ancestors, sources, values and literals."""
    tag = digest(f'{generation}-{index}')[:16]
    fid = f'fam-{generation}-{index:02d}'
    ancestors = tuple(Ancestor(ancestor_id=f'{fid}-{kind}', kind=kind, source_sha256=digest(f'{fid}-{kind}'))
                      for kind in ('lexicon', 'identifier_grammar', 'scenario', 'template'))
    lex = f'{fid}-lexicon'
    # Entity values are unique by construction across families AND generations (no shared value
    # may merge components or carry an entity into a successor edition).
    gen = generation.lstrip('g')
    lexicons = (
        Lexicon(lexicon_id=f'{fid}-name', ancestor_id=lex, label='NAME', values=(f'Mira Vale G{gen}N{index:02d}',)),
        Lexicon(lexicon_id=f'{fid}-mail', ancestor_id=lex, label='EMAIL',
                values=(f'm.g{gen}n{index:02d}@example.invalid',)),
        Lexicon(lexicon_id=f'{fid}-phone', ancestor_id=lex, label='PHONE', values=(f'+1202{gen}55{index:04d}',)),
        Lexicon(lexicon_id=f'{fid}-acct', ancestor_id=lex, label='ACCOUNT_ID', values=(f'ACCT-G{gen}-{index:02d}',)),
    )

    def contact(prefix: str):
        return (Segment(text=f'{prefix}p{tag} '), Segment(lexicon_id=f'{fid}-name'),
                Segment(text=f' m{tag} '), Segment(lexicon_id=f'{fid}-mail'),
                Segment(text=f' t{tag} '), Segment(lexicon_id=f'{fid}-phone'),
                Segment(text=f' a{tag} '), Segment(lexicon_id=f'{fid}-acct'))
    recipes = (
        Recipe(recipe_id='entity-normal', difficulty='normal', taxonomy=('normal_context',), segments=contact('')),
        Recipe(recipe_id='entity-challenge', difficulty='challenge', taxonomy=('unicode_offsets',),
               segments=contact('\U0001f600 ')),
        Recipe(recipe_id='benign-normal', difficulty='normal', taxonomy=('benign_identifiers',),
               segments=(Segment(text=f'trace {tag} latency=12 ms'),)),
        Recipe(recipe_id='benign-challenge', difficulty='challenge', taxonomy=('phone_vs_port',),
               segments=(Segment(text=f'port=8080 svc {tag} ok'),)),
    )
    private = split == 'test'
    fam = Family(family_id=fid, ancestors=tuple(a.ancestor_id for a in ancestors[1:]), recipes=recipes,
                 author_id=CUSTODIAN if private else DEV_AUTHOR,
                 visibility='custodian_private' if private else 'development')
    return ancestors, lexicons, fam


def sealed_inventory(generation: str = 'g1'):
    """1 train + 1 development + 20 test single-family components (plan minimum is 20 test blocks)."""
    splits = ['train', 'development'] + ['test'] * 20
    ancestors, lexicons, families, assignments = [], [], [], []
    for index, split in enumerate(splits):
        a, x, f = family(index, split=split, generation=generation)
        ancestors += a
        lexicons += x
        families.append(f)
        assignments.append(BlockAssignment(block_id=f'block-{generation}-{index:02d}', split=split,
                                           family_ids=(f.family_id,)))
    inventory = FamilyInventory(inventory_id=f'inv-{generation}', ancestors=tuple(ancestors),
                                lexicons=tuple(lexicons), families=tuple(families))
    return inventory, tuple(assignments)


def plan(edition_id: str = 'ed-1') -> CorpusPlan:
    return CorpusPlan(edition_id=edition_id, split_seed=1, sampling_seed=2, train_blocks=1,
                      development_blocks=1, test_blocks=20, records_per_block=RECORDS_PER_BLOCK,
                      guide_sha256=digest('guide'), generator_sha256=digest('generator'),
                      selection_rule_sha256=digest('selection-rule'))


def custody_filesystem(tmp_path: Path, host: TrustedHost) -> CustodyFilesystem:
    base = tmp_path.resolve()
    roots = {role: base / role for role in ('private', 'inference', 'evaluator', 'training')}
    for root in roots.values():
        root.mkdir()
    policy = CustodyPathPolicy(policy_id='policy-1', custodian_id=CUSTODIAN,
                               **{role + '_root': str(path) for role, path in roots.items()})
    approval = FilesystemPolicyApproval(authorization_id='fs-approval-1', policy_sha256=commitment(policy),
                                        custodian_id=CUSTODIAN, issued_at=ISSUED, expires_at=FAR)
    host.approve('custody_filesystem_policy', commitment(approval))
    filesystem = CustodyFilesystem(policy, approval, verify_receipt=host)
    filesystem.claim_roots()
    return filesystem


def isolation_guard(filesystem, host, *, edition_id, manifest_sha256) -> IsolationGuard:
    request = IsolationRequest(edition_id=edition_id, corpus_manifest_sha256=manifest_sha256,
                               filesystem_policy_sha256=filesystem.sha256, worker_policy_sha256=digest('worker'))
    platform = {'win32': 'windows', 'linux': 'linux', 'darwin': 'macos'}[sys.platform]
    capability = IsolationCapability(capability_id='iso-1', edition_id=edition_id,
                                     corpus_manifest_sha256=manifest_sha256,
                                     filesystem_policy_sha256=filesystem.sha256,
                                     worker_policy_sha256=digest('worker'),
                                     enforcement_evidence_sha256=digest('evidence'), issuer_id='host-1',
                                     platform=platform, mechanism_id='test-mechanism', issued_at=ISSUED,
                                     expires_at=FAR)
    host.approve('isolation_capability', commitment(capability))
    host.approve('platform_isolation_enforcement', digest('evidence'))
    return IsolationGuard(capability, request, verify_receipt=host, platform_verifier=BindingVerifier())


def action(host, edition_id: str, kind: str, binding: dict) -> CustodyActionAuthorization:
    authorization = CustodyActionAuthorization(authorization_id=f'{kind}-{edition_id}', edition_id=edition_id,
                                               action=kind, binding_sha256=commitment(binding),
                                               issued_at=ISSUED, expires_at=EXPIRES)
    host.approve(f'custody_{kind}_authorization', commitment(authorization))
    return authorization


def seal_authorization(host, inventory, corpus_plan) -> SealAuthorization:
    authorization = SealAuthorization(authorization_id='seal-1', edition_id=corpus_plan.edition_id,
                                      inventory_sha256=commitment(inventory), plan_sha256=commitment(corpus_plan),
                                      custodian_id=CUSTODIAN, implementation_author_ids=(IMPLEMENTER,),
                                      independent_auditor_id=AUDITOR, approval_receipt_sha256=digest('approval'),
                                      independent_audit_receipt_sha256=digest('audit'), expires_at=EXPIRES)
    host.approve('custody_seal_authorization', commitment(authorization))
    host.approve('custody_approval', digest('approval'))
    host.approve('independent_audit', digest('audit'))
    return authorization


def release_inputs(host, seal_receipt, *, edition_id, manifest_sha256, guard):
    lock = SelectionLockReference(edition_id=edition_id, receipt_sha256=digest('d5-lock'),
                                  corpus_manifest_sha256=manifest_sha256,
                                  selection_rule_sha256=digest('selection-rule'), locked_at=T0_TEXT)
    authorization = ReleaseAuthorization(authorization_id='release-1', edition_id=edition_id, run_id='run-1',
                                         experiment_plan_sha256=digest('experiment-plan'),
                                         corpus_manifest_sha256=manifest_sha256,
                                         population_sha256=seal_receipt.population_sha256,
                                         selection_lock_sha256=digest('d5-lock'),
                                         independent_audit_sha256=seal_receipt.independent_audit_sha256,
                                         isolation_capability_sha256=guard.sha256, custodian_id=CUSTODIAN,
                                         issued_at=T0_TEXT, expires_at=EXPIRES)
    host.approve('custody_release_authorization', commitment(authorization))
    host.approve('pre_test_selection_lock', digest('d5-lock'))
    host.approve('pre_test_lock_binding', commitment(lock))
    return lock, authorization


class PopulationRow(BaseModel):
    record_id: str
    content_sha256: str


@dataclass
class EditionStub:
    """Duck-typed stand-in for D7's LockedEdition fields read by the custody gate."""
    edition_id: str
    run_id: str
    plan_sha256: str
    corpus_manifest_sha256: str
    custody_release_sha256: str
    independent_audit_sha256: str
    selection_lock_sha256: str
    population: tuple
    expires_at: str
    sha256: str

    def require_current(self, now) -> None:
        return None


def edition_for(release, bundle) -> EditionStub:
    rows = sorted(((r.record_id, r.content_sha256) for r, p in zip(bundle.records, bundle.provenance)
                   if p.split == 'test'))
    return EditionStub(edition_id=release.edition_id, run_id=release.run_id,
                       plan_sha256=release.experiment_plan_sha256,
                       corpus_manifest_sha256=release.corpus_manifest_sha256,
                       custody_release_sha256=commitment(release),
                       independent_audit_sha256=release.independent_audit_sha256,
                       selection_lock_sha256=release.selection_lock_sha256,
                       population=tuple(PopulationRow(record_id=i, content_sha256=h) for i, h in rows),
                       expires_at=EXPIRES, sha256=digest('locked-edition'))
