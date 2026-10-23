"""Private corpus construction contracts, separate from detector input contracts."""
from __future__ import annotations

from math import ceil
from typing import Annotated, Literal

from pydantic import Field, model_validator

from m7.contracts import Boundary, Digest, Identifier, Label, LogRecord, Span

Split = Literal['train', 'development', 'test']
Difficulty = Literal['normal', 'challenge']
AncestryKind = Literal['lexicon', 'identifier_grammar', 'scenario', 'template', 'derivation']
Count = Annotated[int, Field(ge=1, le=10000)]
Taxon = Literal[
    'normal_context', 'benign_identifiers', 'name_in_email', 'derived_username',
    'phone_vs_port', 'repeat_entity', 'unicode_offsets', 'multiline',
    'escaped_punctuation', 'prompt_as_data', 'implicit_person', 'ambiguous_context',
]


class CorpusPlan(Boundary):
    schema_version: Literal['CorpusPlan/v1'] = 'CorpusPlan/v1'
    edition_id: Identifier
    split_seed: Annotated[int, Field(ge=0, le=2**63 - 1)]
    sampling_seed: Annotated[int, Field(ge=0, le=2**63 - 1)]
    train_blocks: Count = 40
    development_blocks: Count = 20
    test_blocks: Annotated[int, Field(ge=20, le=10000)] = 30
    records_per_block: Annotated[int, Field(ge=5, le=10000)] = 40
    minimum_test_blocks: Annotated[int, Field(ge=20, le=10000)] = 20
    minimum_test_entities_per_class: Annotated[int, Field(ge=200, le=1000000)] = 200
    benign_fraction: Annotated[float, Field(ge=0.2, lt=1, allow_inf_nan=False)] = 0.2
    challenge_fraction: Annotated[float, Field(gt=0, lt=1, allow_inf_nan=False)] = 0.5
    guide_sha256: Digest
    generator_sha256: Digest
    selection_rule_sha256: Digest

    @model_validator(mode='after')
    def enough_requested_blocks(self) -> CorpusPlan:
        if self.test_blocks < self.minimum_test_blocks:
            raise ValueError('insufficient_requested_test_blocks')
        if (ceil(self.records_per_block * self.benign_fraction) >= self.records_per_block
                or ceil(self.records_per_block * self.challenge_fraction) >= self.records_per_block):
            raise ValueError('sampling_fraction_removes_required_stratum')
        return self


class Ancestor(Boundary):
    ancestor_id: Identifier
    kind: AncestryKind
    parents: tuple[Identifier, ...] = ()
    source_sha256: Digest


class Lexicon(Boundary):
    lexicon_id: Identifier
    ancestor_id: Identifier
    label: Label | None = None
    values: Annotated[tuple[str, ...], Field(min_length=1, max_length=10000)]

    @model_validator(mode='after')
    def safe_original_values(self) -> Lexicon:
        if any(not value or len(value) > 512 or any(0xD800 <= ord(c) <= 0xDFFF for c in value)
               for value in self.values):
            raise ValueError('invalid_lexicon_value')
        if len(set(self.values)) != len(self.values):
            raise ValueError('duplicate_lexicon_value')
        if self.label == 'EMAIL' and any(not v.endswith('@example.invalid') for v in self.values):
            raise ValueError('development_email_domain_required')
        return self


class Segment(Boundary):
    """Exactly one literal or lexicon reference; labels come from the lexicon."""
    text: Annotated[str, Field(max_length=1024)] | None = None
    lexicon_id: Identifier | None = None

    @model_validator(mode='after')
    def one_source(self) -> Segment:
        if (self.text is None) == (self.lexicon_id is None):
            raise ValueError('one_segment_source_required')
        return self


class Recipe(Boundary):
    recipe_id: Identifier
    difficulty: Difficulty
    taxonomy: Annotated[tuple[Taxon, ...], Field(min_length=1)]
    adjudication: Literal['clear', 'resolved', 'pending'] = 'clear'
    adjudication_ref: Identifier | None = None
    segments: Annotated[tuple[Segment, ...], Field(min_length=1, max_length=128)]

    @model_validator(mode='after')
    def resolved_reference(self) -> Recipe:
        if self.adjudication == 'resolved' and self.adjudication_ref is None:
            raise ValueError('adjudication_reference_required')
        return self


class Family(Boundary):
    family_id: Identifier
    ancestors: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    recipes: Annotated[tuple[Recipe, ...], Field(min_length=1)]
    author_id: Identifier
    visibility: Literal['development', 'custodian_private']
    original_synthetic: Literal[True] = True


class FamilyInventory(Boundary):
    schema_version: Literal['FamilyInventory/v1'] = 'FamilyInventory/v1'
    inventory_id: Identifier
    ancestors: Annotated[tuple[Ancestor, ...], Field(min_length=1)]
    lexicons: tuple[Lexicon, ...]
    families: Annotated[tuple[Family, ...], Field(min_length=1)]


class BlockAssignment(Boundary):
    block_id: Identifier
    split: Split
    family_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]


class SplitAudit(Boundary):
    schema_version: Literal['SplitAudit/v1'] = 'SplitAudit/v1'
    status: Literal['mechanical_only', 'blocked']
    reasons: tuple[Identifier, ...]
    inventory_sha256: Digest
    assignments_sha256: Digest
    effective_train_blocks: int
    effective_development_blocks: int
    effective_test_blocks: int
    component_by_family: dict[str, str]
    minimum_count_met: bool
    independent_audit: Literal['pending'] = 'pending'
    label_audit: Literal['pending'] = 'pending'
    custody_accepted: Literal[False] = False


class GoldRow(Boundary):
    record_id: Identifier
    content_sha256: Digest
    spans: tuple[Span, ...]


class RecordProvenance(Boundary):
    record_id: Identifier
    block_id: Identifier
    family_id: Identifier
    recipe_id: Identifier
    split: Split
    difficulty: Difficulty
    taxonomy: tuple[Taxon, ...]
    sample_index: int


class CorpusManifest(Boundary):
    schema_version: Literal['CorpusManifest/v1'] = 'CorpusManifest/v1'
    edition_id: Identifier
    scope: Literal['development_only', 'custodian_sealed']
    inventory_sha256: Digest
    plan_sha256: Digest
    guide_sha256: Digest
    generator_sha256: Digest
    assignments_sha256: Digest
    records_sha256: Digest
    gold_sha256: Digest
    provenance_sha256: Digest
    audit_sha256: Digest
    record_count: int
    split_counts: dict[str, int]
    effective_blocks: dict[str, int]
    gold_counts: dict[str, dict[str, int]]
    near_duplicate_cross_split_pairs: int
    independent_audit: Literal['pending'] = 'pending'
    custody_accepted: Literal[False] = False


class CorpusBundle(Boundary):
    """Evaluator/custodian-only container. Never pass this object to a detector."""
    manifest: CorpusManifest
    records: tuple[LogRecord, ...]
    gold: tuple[GoldRow, ...]
    provenance: tuple[RecordProvenance, ...]
    assignments: tuple[BlockAssignment, ...]
    audit: SplitAudit


class SealAuthorization(Boundary):
    """Explicit future custody grant; a typed record is not an independent verdict."""
    authorization_id: Identifier
    edition_id: Identifier
    inventory_sha256: Digest
    plan_sha256: Digest
    custodian_id: Identifier
    implementation_author_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    independent_auditor_id: Identifier
    approval_receipt_sha256: Digest
    independent_audit_receipt_sha256: Digest
    expires_at: str
    permitted_action: Literal['seal_corpus'] = 'seal_corpus'
