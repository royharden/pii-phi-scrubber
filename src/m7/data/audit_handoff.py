"""Value-free request packet for a genuinely nonauthoring provenance/label audit."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Callable, Literal
from typing import Annotated

from pydantic import Field

from m7.contracts import Boundary, Digest, Identifier

from .access import _time
from .corpus import LABELS, verify_bundle
from .models import BlockAssignment, CorpusBundle, CorpusPlan, FamilyInventory
from .provenance import audit_inventory, commitment


class AuditHandoff(Boundary):
    schema_version: Literal['AuditHandoff/v1'] = 'AuditHandoff/v1'
    edition_id: Identifier
    custodian_id: Identifier
    implementation_author_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    family_author_ids: tuple[Identifier, ...]
    guide_sha256: Digest
    generator_sha256: Digest
    inventory_sha256: Digest
    ancestry_sha256: Digest
    assignments_sha256: Digest
    plan_sha256: Digest
    selection_rule_sha256: Digest
    corpus_manifest_sha256: Digest | None
    mechanical_audit_sha256: Digest
    effective_blocks: dict[str, int]
    population_status: Literal['not_supplied', 'supplied_mechanical']
    slice_record_counts: dict[str, dict[str, int]] | None
    slice_class_counts: dict[str, dict[str, dict[str, int]]] | None
    benign_record_counts: dict[str, int] | None
    taxonomy_recipe_counts: dict[str, int]
    adjudication_counts: dict[str, int]
    issue_counts: dict[str, int]
    requested_scope: Literal['independent_provenance_and_stratified_label_audit'] = 'independent_provenance_and_stratified_label_audit'
    provenance_verdict: Literal['pending'] = 'pending'
    annotation_verdict: Literal['pending'] = 'pending'
    independent_verdict_issued: Literal[False] = False


class IndependentAuditVerdict(Boundary):
    """Only an external authenticated reviewer may supply this completed verdict."""
    schema_version: Literal['IndependentAuditVerdict/v1'] = 'IndependentAuditVerdict/v1'
    edition_id: Identifier
    packet_sha256: Digest
    reviewer_id: Identifier
    review_scope: Literal['independent_provenance_and_stratified_label_audit']
    provenance_verdict: Literal['accepted', 'rejected']
    annotation_verdict: Literal['accepted', 'rejected']
    evidence_sha256: Digest
    completed_at: str
    expires_at: str


def build_audit_handoff(inventory: FamilyInventory, plan: CorpusPlan,
                        assignments: tuple[BlockAssignment, ...], *, custodian_id: str,
                        implementation_author_ids: tuple[str, ...],
                        bundle: CorpusBundle | None = None) -> AuditHandoff:
    development_only = not any(block.split == 'test' for block in assignments)
    audit = audit_inventory(inventory, assignments, plan, development_only=development_only)
    recipes = [recipe for family in inventory.families for recipe in family.recipes]
    adjudications = dict(Counter(recipe.adjudication for recipe in recipes))
    issues = dict(Counter(audit.reasons))
    if not audit.minimum_count_met:
        issues['insufficient_independent_test_blocks'] = 1
    if adjudications.get('pending'):
        issues['unresolved_annotation_adjudications'] = adjudications['pending']
    slice_records = {split: {'normal': 0, 'challenge': 0} for split in ('train', 'development', 'test')}
    classes = {split: {difficulty: {label: 0 for label in LABELS} for difficulty in ('normal', 'challenge')}
               for split in ('train', 'development', 'test')}
    benign = {split: 0 for split in ('train', 'development', 'test')}
    manifest_digest = None
    if bundle is not None:
        verify_bundle(bundle)
        if (bundle.manifest.plan_sha256 != commitment(plan)
                or bundle.manifest.inventory_sha256 != commitment(inventory)
                or bundle.manifest.assignments_sha256 != commitment(assignments)):
            raise ValueError('audit_handoff_corpus_binding_mismatch')
        manifest_digest = commitment(bundle.manifest)
        for provenance, gold in zip(bundle.provenance, bundle.gold, strict=True):
            slice_records[provenance.split][provenance.difficulty] += 1
            benign[provenance.split] += not gold.spans
            for span in gold.spans:
                classes[provenance.split][provenance.difficulty][span.label] += 1
    else:
        issues['corpus_not_generated_or_supplied'] = 1
    return AuditHandoff(edition_id=plan.edition_id, custodian_id=custodian_id,
        implementation_author_ids=implementation_author_ids,
        family_author_ids=tuple(sorted({family.author_id for family in inventory.families})),
        guide_sha256=plan.guide_sha256, generator_sha256=plan.generator_sha256,
        inventory_sha256=commitment(inventory), ancestry_sha256=commitment(inventory.ancestors),
        assignments_sha256=commitment(assignments), plan_sha256=commitment(plan),
        selection_rule_sha256=plan.selection_rule_sha256, corpus_manifest_sha256=manifest_digest,
        mechanical_audit_sha256=commitment(audit),
        effective_blocks={'train': audit.effective_train_blocks, 'development': audit.effective_development_blocks,
                          'test': audit.effective_test_blocks},
        population_status='supplied_mechanical' if bundle else 'not_supplied',
        slice_record_counts=slice_records if bundle else None,
        slice_class_counts=classes if bundle else None, benign_record_counts=benign if bundle else None,
        taxonomy_recipe_counts=dict(Counter(tag for recipe in recipes for tag in recipe.taxonomy)),
        adjudication_counts=adjudications, issue_counts=issues)


def verify_independent_audit(packet: AuditHandoff, verdict: IndependentAuditVerdict, *,
                              verify_receipt: Callable[[str, str], bool]) -> str:
    """Return original verdict digest only after issuer/scope/role authentication.

    Packet remains immutable/pending. This function never authors a verdict or
    calls the author's own source inspection an independent audit.
    """
    if (packet.population_status != 'supplied_mechanical' or any(packet.issue_counts.values())
            or verdict.edition_id != packet.edition_id or verdict.packet_sha256 != commitment(packet)
            or verdict.review_scope != packet.requested_scope
            or verdict.reviewer_id in set(packet.implementation_author_ids) | set(packet.family_author_ids) | {packet.custodian_id}
            or not _time(verdict.completed_at) <= datetime.now(timezone.utc) < _time(verdict.expires_at)):
        raise ValueError('independent_audit_binding_or_role_mismatch')
    if verify_receipt('independent_audit_verdict', commitment(verdict)) is not True:
        raise ValueError('independent_audit_not_authenticated_or_revoked')
    if verdict.provenance_verdict != 'accepted' or verdict.annotation_verdict != 'accepted':
        raise ValueError('independent_audit_rejected')
    return commitment(verdict)
