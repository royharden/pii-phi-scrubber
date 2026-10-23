"""Semantic ancestry closure and whole-component allocation, never seed independence."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import defaultdict
from typing import Any

from pydantic import BaseModel

from .models import BlockAssignment, CorpusPlan, FamilyInventory, SplitAudit


def canonical_bytes(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode='json')
    elif isinstance(value, (tuple, list)):
        value = [v.model_dump(mode='json') if isinstance(v, BaseModel) else v for v in value]
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def commitment(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def family_components(inventory: FamilyInventory) -> tuple[tuple[str, ...], ...]:
    """Merge through aliases, parents, lexicons AND actual shared entity values.

    Generic programming libraries are not semantic ancestors. Scenario grammars,
    identifier generators, paraphrases and value pools are. A new ID/source hash
    never erases a declared common ancestor. Hidden ancestry still needs an auditor.
    """
    nodes = {a.ancestor_id: a for a in inventory.ancestors}
    lexicons = {x.lexicon_id: x for x in inventory.lexicons}
    families = {f.family_id: f for f in inventory.families}
    if len(nodes) != len(inventory.ancestors) or len(lexicons) != len(inventory.lexicons) or len(families) != len(inventory.families):
        raise ValueError('duplicate_inventory_identifier')
    memo: dict[str, frozenset[str]] = {}
    visiting: set[str] = set()

    def closure(identity: str) -> frozenset[str]:
        if identity not in nodes:
            raise ValueError('unknown_semantic_ancestor')
        if identity in visiting:
            raise ValueError('cyclic_semantic_ancestry')
        if identity not in memo:
            visiting.add(identity)
            result = {identity}
            for parent in nodes[identity].parents:
                result.update(closure(parent))
            visiting.remove(identity)
            memo[identity] = frozenset(result)
        return memo[identity]

    for identity in nodes:
        closure(identity)
    for lexicon in lexicons.values():
        if lexicon.ancestor_id not in nodes or nodes[lexicon.ancestor_id].kind != 'lexicon':
            raise ValueError('invalid_lexicon_ancestry')
    parents = {identity: identity for identity in families}

    def root(identity: str) -> str:
        while parents[identity] != identity:
            parents[identity] = parents[parents[identity]]
            identity = parents[identity]
        return identity

    seen: dict[tuple[str, str], str] = {}
    for family in inventory.families:
        semantic: set[str] = set()
        for ancestor in family.ancestors:
            semantic.update(closure(ancestor))
        recipe_ids: set[str] = set()
        values: set[str] = set()
        for recipe in family.recipes:
            if recipe.recipe_id in recipe_ids:
                raise ValueError('duplicate_recipe_identifier')
            recipe_ids.add(recipe.recipe_id)
            for segment in recipe.segments:
                if segment.lexicon_id is not None:
                    lexicon = lexicons.get(segment.lexicon_id)
                    if lexicon is None:
                        raise ValueError('unknown_recipe_lexicon')
                    semantic.update(closure(lexicon.ancestor_id))
                    # Private-only supplement. No normalized values/hashes in reports.
                    if lexicon.label is not None:
                        values.update(unicodedata.normalize('NFKC', v).casefold() for v in lexicon.values)
        kinds = {nodes[a].kind for a in semantic}
        if not {'lexicon', 'identifier_grammar', 'scenario', 'template'}.issubset(kinds):
            raise ValueError('incomplete_semantic_ancestry')
        keys = ([('ancestor', a) for a in semantic]
                + [('semantic_source', nodes[a].kind + ':' + nodes[a].source_sha256) for a in semantic]
                + [('entity', v) for v in values])
        for key in keys:
            if key in seen:
                a, b = root(family.family_id), root(seen[key])
                parents[max(a, b)] = min(a, b)
            else:
                seen[key] = family.family_id
    groups: dict[str, list[str]] = defaultdict(list)
    for identity in families:
        groups[root(identity)].append(identity)
    return tuple(sorted(tuple(sorted(group)) for group in groups.values()))


def allocate_blocks(inventory: FamilyInventory, plan: CorpusPlan) -> tuple[BlockAssignment, ...]:
    """Require the full inventory target; never split a connected component."""
    groups = family_components(inventory)
    expected = plan.train_blocks + plan.development_blocks + plan.test_blocks
    if len(groups) != expected:
        raise ValueError('inventory_component_target_mismatch')
    families = {family.family_id: family for family in inventory.families}
    public_groups = []
    private_groups = []
    for group in groups:
        visibility = {families[f].visibility for f in group}
        if len(visibility) != 1:
            raise ValueError('development_private_semantic_overlap')
        (public_groups if visibility == {'development'} else private_groups).append(group)
    if len(public_groups) != plan.train_blocks + plan.development_blocks or len(private_groups) != plan.test_blocks:
        raise ValueError('inventory_custody_pool_target_mismatch')
    public_groups.sort(key=lambda group: commitment([plan.split_seed, list(group)]))
    private_groups.sort(key=lambda group: commitment([plan.split_seed, list(group)]))
    ordered = public_groups + private_groups
    assignments = []
    for index, group in enumerate(ordered):
        split = ('train' if index < plan.train_blocks else 'development'
                 if index < plan.train_blocks + plan.development_blocks else 'test')
        assignments.append(BlockAssignment(block_id='block-' + commitment(list(group))[:24],
                                           split=split, family_ids=group))
    return tuple(assignments)


def audit_inventory(inventory: FamilyInventory, assignments: tuple[BlockAssignment, ...],
                    plan: CorpusPlan, *, development_only: bool = False) -> SplitAudit:
    groups = family_components(inventory)
    component = {f: 'component-' + commitment(list(group))[:24] for group in groups for f in group}
    reasons: set[str] = set()
    owners: dict[str, tuple[str, str]] = {}
    seen_families: set[str] = set()
    seen_blocks: set[str] = set()
    effective: dict[str, set[str]] = {s: set() for s in ('train', 'development', 'test')}
    family_by_id = {f.family_id: f for f in inventory.families}
    for block in assignments:
        if block.block_id in seen_blocks:
            reasons.add('duplicate_block_id')
        seen_blocks.add(block.block_id)
        block_components = set()
        for identity in block.family_ids:
            if identity not in component:
                raise ValueError('unknown_assigned_family')
            if identity in seen_families:
                reasons.add('duplicate_assigned_family')
            seen_families.add(identity)
            cid = component[identity]
            block_components.add(cid)
            previous = owners.get(cid)
            if previous is not None and previous != (block.block_id, block.split):
                reasons.add('component_split_across_blocks')
                if previous[1] != block.split:
                    reasons.add('cross_split_semantic_ancestry')
            owners[cid] = (block.block_id, block.split)
            effective[block.split].add(cid)
            family = family_by_id[identity]
            if block.split == 'test' and family.visibility != 'custodian_private':
                reasons.add('development_family_in_test')
            if block.split != 'test' and family.visibility != 'development':
                reasons.add('private_family_in_development')
            if any(r.adjudication == 'pending' for r in family.recipes):
                reasons.add('unresolved_annotation_ambiguity')
        if len(block_components) != 1:
            reasons.add('unrelated_components_in_one_block')
    if seen_families != set(component):
        reasons.add('unassigned_family')
    enough = len(effective['test']) >= plan.minimum_test_blocks
    if development_only:
        if effective['test']:
            reasons.add('test_forbidden_in_development_generation')
    else:
        for split, target in (('train', plan.train_blocks), ('development', plan.development_blocks), ('test', plan.test_blocks)):
            if len(effective[split]) != target:
                reasons.add('insufficient_or_excess_' + split + '_blocks')
        if not enough:
            reasons.add('insufficient_independent_test_blocks')
    return SplitAudit(status='blocked' if reasons else 'mechanical_only', reasons=tuple(sorted(reasons)),
                      inventory_sha256=commitment(inventory), assignments_sha256=commitment(assignments),
                      effective_train_blocks=len(effective['train']), effective_development_blocks=len(effective['development']),
                      effective_test_blocks=len(effective['test']), component_by_family=component, minimum_count_met=enough)
