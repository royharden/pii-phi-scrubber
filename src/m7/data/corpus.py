"""Original recipe expansion with append-time gold spans and private provenance."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import ceil
import re
import unicodedata

from m7.contracts import LogRecord, Span, make_record

from .models import (
    BlockAssignment, CorpusBundle, CorpusManifest, CorpusPlan, FamilyInventory,
    GoldRow, RecordProvenance, SealAuthorization, Split,
)
from .provenance import audit_inventory, commitment, family_components

LABELS = ('NAME', 'EMAIL', 'PHONE', 'ACCOUNT_ID')


def normalize_entity_value(value: str) -> str:
    """The ONE successor-reuse comparison form: NFC, casefold, NFC, whitespace collapsed/stripped.

    Comparison only; never used for offsets, model inputs or any persisted record.
    """
    folded = unicodedata.normalize('NFC', unicodedata.normalize('NFC', value).casefold())
    return re.sub(r'\s+', ' ', folded).strip()


def held_out_entity_values(inventory: FamilyInventory) -> frozenset[str]:
    """Normalized labelled pool values of custodian-private (test) families, in memory only.

    The split audit forces test blocks to hold exactly the custodian_private families.
    """
    lexicons = {lexicon.lexicon_id: lexicon for lexicon in inventory.lexicons}
    return frozenset(normalize_entity_value(value)
                     for family in inventory.families if family.visibility == 'custodian_private'
                     for recipe in family.recipes for segment in recipe.segments
                     if segment.lexicon_id is not None and lexicons[segment.lexicon_id].label is not None
                     for value in lexicons[segment.lexicon_id].values)


def _choice(seed: int, *parts: object, size: int) -> int:
    return int(commitment([seed, *parts]), 16) % size


def near_duplicate_audit(records: tuple[LogRecord, ...], gold: tuple[GoldRow, ...],
                         provenance: tuple[RecordProvenance, ...],
                         *, threshold: float = 0.9) -> tuple[tuple[str, str], ...]:
    """Private supplemental normalized-skeleton audit; output IDs only.

    Gold values are replaced before normalizing. Normalization is NEVER used for
    prediction offsets or model inputs. Character trigrams catch punctuation and
    superficial paraphrase duplicates; absence of matches is not independence.
    """
    if not 0 < threshold <= 1 or len(records) > 10000:
        raise ValueError('unsupported_near_duplicate_audit_size')
    gold_by_id = {row.record_id: row for row in gold}
    splits = {row.record_id: row.split for row in provenance}
    postings: dict[str, set[int]] = defaultdict(set)
    prior: list[tuple[str, str, frozenset[str]]] = []
    pairs: list[tuple[str, str]] = []
    for record in records:
        text = record.log.message
        spans = gold_by_id[record.record_id].spans
        for span in sorted(spans, key=lambda s: s.start, reverse=True):
            text = text[:span.start] + '<' + span.label + '>' + text[span.end:]
        normalized = re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text).casefold()).strip()
        grams = frozenset(normalized[i:i + 3] for i in range(max(1, len(normalized) - 2)))
        candidates: set[int] = set()
        for gram in grams:
            candidates.update(postings[gram])
        for index in sorted(candidates):
            previous_id, split, other = prior[index]
            if split == splits[record.record_id]:
                continue
            denominator = len(grams | other)
            similarity = len(grams & other) / denominator if denominator else 1.0
            if similarity >= threshold:
                pairs.append((previous_id, record.record_id))
        for gram in grams:
            postings[gram].add(len(prior))
        prior.append((record.record_id, splits[record.record_id], grams))
    return tuple(pairs)


def _build(inventory: FamilyInventory, plan: CorpusPlan,
           assignments: tuple[BlockAssignment, ...], *, development_only: bool) -> CorpusBundle:
    audit = audit_inventory(inventory, assignments, plan, development_only=development_only)
    if audit.status == 'blocked':
        raise ValueError('split_audit_blocked')
    if len(assignments) * plan.records_per_block > 10000:
        raise ValueError('unsupported_corpus_size')
    families = {family.family_id: family for family in inventory.families}
    lexicons = {lexicon.lexicon_id: lexicon for lexicon in inventory.lexicons}
    records: list[LogRecord] = []
    gold: list[GoldRow] = []
    provenance: list[RecordProvenance] = []
    for block in sorted(assignments, key=lambda b: b.block_id):
        # Freeze both proportions at the block level; no gold-dependent resampling.
        n = plan.records_per_block
        benign_indices = set(sorted(range(n), key=lambda i: commitment([plan.sampling_seed, block.block_id, 'benign', i]))[:ceil(n * plan.benign_fraction)])
        challenge_indices = set(sorted(range(n), key=lambda i: commitment([plan.sampling_seed, block.block_id, 'challenge', i]))[:ceil(n * plan.challenge_fraction)])
        recipes = [(families[f], recipe) for f in block.family_ids for recipe in families[f].recipes]
        buckets: dict[tuple[bool, str], list] = defaultdict(list)
        for family, recipe in recipes:
            has_entities = any(s.lexicon_id is not None and lexicons[s.lexicon_id].label is not None for s in recipe.segments)
            buckets[(not has_entities, recipe.difficulty)].append((family, recipe))
        for index in range(n):
            difficulty = 'challenge' if index in challenge_indices else 'normal'
            options = buckets[(index in benign_indices, difficulty)]
            if not options:
                raise ValueError('missing_sampling_stratum')
            family, recipe = options[_choice(plan.sampling_seed, block.block_id, index, 'recipe', size=len(options))]
            pieces: list[str] = []
            spans: list[Span] = []
            cursor = 0
            for segment in recipe.segments:
                if segment.text is not None:
                    value, label = segment.text, None
                else:
                    lexicon = lexicons[segment.lexicon_id]
                    value = lexicon.values[_choice(plan.sampling_seed, block.block_id, index, lexicon.lexicon_id, size=len(lexicon.values))]
                    label = lexicon.label
                pieces.append(value)
                if label is not None:
                    spans.append(Span(start=cursor, end=cursor + len(value), label=label))
                cursor += len(value)
            message = ''.join(pieces)
            # Opaque IDs reveal neither family, recipe, split nor entity values.
            record_id = 'r-' + commitment([plan.edition_id, block.block_id, index])[:32]
            record = make_record(message, record_id, 'inference')
            records.append(record)
            gold.append(GoldRow(record_id=record_id, content_sha256=record.content_sha256, spans=tuple(spans)))
            provenance.append(RecordProvenance(record_id=record_id, block_id=block.block_id,
                family_id=family.family_id, recipe_id=recipe.recipe_id, split=block.split,
                difficulty=difficulty, taxonomy=recipe.taxonomy, sample_index=index))
    frozen_records, frozen_gold, frozen_provenance = tuple(records), tuple(gold), tuple(provenance)
    pairs = near_duplicate_audit(frozen_records, frozen_gold, frozen_provenance)
    if pairs:
        # Resolve ancestry/duplicates in a new inventory BEFORE seal, not by dropping rows.
        raise ValueError('cross_split_near_duplicates_require_adjudication')
    counts = {split: {label: 0 for label in LABELS} for split in ('train', 'development', 'test')}
    split_counts: Counter[str] = Counter()
    benign_counts: Counter[str] = Counter()
    block_labels: dict[str, set[str]] = defaultdict(set)
    for row, annotation in zip(provenance, gold, strict=True):
        split_counts[row.split] += 1
        benign_counts[row.split] += not annotation.spans
        for span in annotation.spans:
            counts[row.split][span.label] += 1
            block_labels[row.block_id].add(span.label)
    for split, total in split_counts.items():
        if benign_counts[split] < ceil(total * plan.benign_fraction):
            raise ValueError('insufficient_benign_coverage')
    for block in assignments:
        if block_labels[block.block_id] != set(LABELS):
            raise ValueError('insufficient_per_block_class_coverage')
    if not development_only and any(counts['test'][label] < plan.minimum_test_entities_per_class for label in LABELS):
        raise ValueError('insufficient_test_class_support')
    manifest = CorpusManifest(edition_id=plan.edition_id,
        scope='development_only' if development_only else 'custodian_sealed',
        inventory_sha256=commitment(inventory), plan_sha256=commitment(plan),
        guide_sha256=plan.guide_sha256, generator_sha256=plan.generator_sha256,
        assignments_sha256=commitment(assignments), records_sha256=commitment(frozen_records),
        gold_sha256=commitment(frozen_gold), provenance_sha256=commitment(frozen_provenance),
        audit_sha256=commitment(audit), record_count=len(records), split_counts=dict(split_counts),
        effective_blocks={'train': audit.effective_train_blocks, 'development': audit.effective_development_blocks,
                          'test': audit.effective_test_blocks}, gold_counts=counts,
        near_duplicate_cross_split_pairs=0)
    return CorpusBundle(manifest=manifest, records=frozen_records, gold=frozen_gold,
                        provenance=frozen_provenance, assignments=assignments, audit=audit)


def generate_development(inventory: FamilyInventory, plan: CorpusPlan,
                         assignments: tuple[BlockAssignment, ...] | None = None) -> CorpusBundle:
    """Generate train/dev only. The shipped shared-family scaffold is one dev block."""
    if any(f.visibility != 'development' for f in inventory.families):
        raise ValueError('private_inventory_not_allowed_in_development')
    if assignments is None:
        assignments = tuple(BlockAssignment(block_id='dev-' + commitment(list(group))[:24],
                            split='development', family_ids=group) for group in family_components(inventory))
    if any(block.split == 'test' for block in assignments):
        raise ValueError('test_generation_requires_custodian')
    return _build(inventory, plan, assignments, development_only=True)


def seal_corpus(inventory: FamilyInventory, plan: CorpusPlan,
                assignments: tuple[BlockAssignment, ...], authorization: SealAuthorization,
                *, now: datetime | None = None) -> CorpusBundle:
    """Future custodian-only entrypoint. This does not issue an independent verdict.

    The operator must authenticate approval/audit receipts and enforce OS/process
    separation. Lifecycle release/revocation is a separate gate, not this function.
    """
    now = now or datetime.now(timezone.utc)
    try:
        expiry = datetime.fromisoformat(authorization.expires_at.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('invalid_custody_expiry') from None
    if now.tzinfo is None or expiry.tzinfo is None or expiry <= now:
        raise ValueError('expired_custody_authorization')
    if (authorization.edition_id != plan.edition_id or authorization.inventory_sha256 != commitment(inventory)
            or authorization.plan_sha256 != commitment(plan)):
        raise ValueError('custody_commitment_mismatch')
    implementers = set(authorization.implementation_author_ids)
    authors = {family.author_id for family in inventory.families}
    if authorization.custodian_id in implementers or authorization.independent_auditor_id in authors | implementers | {authorization.custodian_id}:
        raise ValueError('custody_role_conflict')
    families = {family.family_id: family for family in inventory.families}
    for block in assignments:
        if block.split == 'test' and any(families[f].author_id != authorization.custodian_id for f in block.family_ids):
            raise ValueError('test_family_not_authored_by_custodian')
    return _build(inventory, plan, assignments, development_only=False)


def inference_records(bundle: CorpusBundle, *, split: Split | None = None) -> tuple[LogRecord, ...]:
    """Evaluator selects a split before creating the provenance-free worker channel."""
    verify_bundle(bundle)
    return tuple(record.model_copy(update={'split_id': 'inference'})
                 for record, row in zip(bundle.records, bundle.provenance, strict=True)
                 if split is None or row.split == split)


def verify_bundle(bundle: CorpusBundle) -> None:
    """Integrity checks for a consumer before reading separate evaluator channels."""
    m = bundle.manifest
    for expected, actual in (
        (m.records_sha256, commitment(bundle.records)), (m.gold_sha256, commitment(bundle.gold)),
        (m.provenance_sha256, commitment(bundle.provenance)), (m.assignments_sha256, commitment(bundle.assignments)),
        (m.audit_sha256, commitment(bundle.audit)),
    ):
        if expected != actual:
            raise ValueError('corpus_commitment_mismatch')
    ids = [record.record_id for record in bundle.records]
    if len(set(ids)) != len(ids) or len(ids) != m.record_count:
        raise ValueError('invalid_corpus_record_identity')
    if ids != [row.record_id for row in bundle.gold] or ids != [row.record_id for row in bundle.provenance]:
        raise ValueError('corpus_channel_identity_mismatch')
    assignments = {block.block_id: block for block in bundle.assignments}
    for record, gold, provenance in zip(bundle.records, bundle.gold, bundle.provenance, strict=True):
        block = assignments.get(provenance.block_id)
        if block is None or provenance.split != block.split or provenance.family_id not in block.family_ids:
            raise ValueError('corpus_provenance_assignment_mismatch')
        if gold.content_sha256 != record.content_sha256 or any(span.end > len(record.log.message) for span in gold.spans):
            raise ValueError('corpus_gold_identity_mismatch')
        intervals = sorted((span.start, span.end) for span in gold.spans)
        if any(a[1] > b[0] for a, b in zip(intervals, intervals[1:])):
            raise ValueError('overlapping_generator_gold')
    if m.inventory_sha256 != bundle.audit.inventory_sha256 or m.assignments_sha256 != bundle.audit.assignments_sha256 or bundle.audit.status != 'mechanical_only':
        raise ValueError('corpus_audit_mismatch')
    effective = {'train': bundle.audit.effective_train_blocks,
                 'development': bundle.audit.effective_development_blocks,
                 'test': bundle.audit.effective_test_blocks}
    split_counts = dict(Counter(row.split for row in bundle.provenance))
    counts = {split: {label: 0 for label in LABELS} for split in ('train', 'development', 'test')}
    for row, gold in zip(bundle.provenance, bundle.gold, strict=True):
        for span in gold.spans:
            counts[row.split][span.label] += 1
    if (m.effective_blocks != effective or m.split_counts != split_counts or m.gold_counts != counts
            or m.near_duplicate_cross_split_pairs != 0):
        raise ValueError('corpus_summary_mismatch')
    if m.scope == 'development_only' and split_counts.get('test', 0):
        raise ValueError('test_in_development_bundle')
    if m.scope == 'custodian_sealed' and not bundle.audit.minimum_count_met:
        raise ValueError('insufficient_sealed_test_blocks')
