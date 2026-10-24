"""Cross-split connected-component audit: shared semantic ancestry merges families, seeds do not."""
from m7.data.development import development_inventory
from m7.data.models import Ancestor, BlockAssignment, CorpusPlan, Family, FamilyInventory, Lexicon, Recipe, Segment
from m7.data.provenance import audit_inventory, family_components

from .custody_fixtures import digest

PLAN = CorpusPlan(edition_id='dev-ed', split_seed=1, sampling_seed=2, guide_sha256=digest('guide'),
                  generator_sha256=digest('generator'), selection_rule_sha256=digest('selection-rule'))


def family(fid, *, lexicon_ancestor=None, scenario_parent=None, name=None, template_source=None):
    """Own grammar/scenario/template/lexicon ancestors unless a shared one is injected."""
    lex = lexicon_ancestor or f'{fid}-lex'
    ancestors = [
        Ancestor(ancestor_id=f'{fid}-grammar', kind='identifier_grammar', source_sha256=digest(f'{fid}-grammar')),
        Ancestor(ancestor_id=f'{fid}-scenario', kind='scenario', source_sha256=digest(f'{fid}-scenario'),
                 parents=(scenario_parent,) if scenario_parent else ()),
        Ancestor(ancestor_id=f'{fid}-template', kind='template',
                 source_sha256=template_source or digest(f'{fid}-template')),
    ]
    if lexicon_ancestor is None:
        ancestors.append(Ancestor(ancestor_id=lex, kind='lexicon', source_sha256=digest(lex)))
    lexicon = Lexicon(lexicon_id=f'{fid}-names', ancestor_id=lex, label='NAME', values=(name or f'Name {fid}',))
    recipe = Recipe(recipe_id=f'{fid}-r', difficulty='normal', taxonomy=('normal_context',),
                    segments=(Segment(text='person: '), Segment(lexicon_id=lexicon.lexicon_id)))
    fam = Family(family_id=fid, ancestors=(f'{fid}-grammar', f'{fid}-scenario', f'{fid}-template'),
                 recipes=(recipe,), author_id='dev-author-1', visibility='development')
    return ancestors, lexicon, fam


def inventory(*parts, extra=()):
    ancestors = list(extra)
    for a, _, _ in parts:
        ancestors += a
    return FamilyInventory(inventory_id='inv', ancestors=tuple(ancestors),
                           lexicons=tuple(x for _, x, _ in parts), families=tuple(f for _, _, f in parts))


SPLIT_AB = (BlockAssignment(block_id='block-a', split='train', family_ids=('fam-a',)),
            BlockAssignment(block_id='block-b', split='development', family_ids=('fam-b',)))


def audit(inv):
    return audit_inventory(inv, SPLIT_AB, PLAN, development_only=True)


def assert_cross_split_flagged(inv):
    assert family_components(inv) == (('fam-a', 'fam-b'),)
    result = audit(inv)
    assert result.status == 'blocked'
    assert result.reasons == ('component_split_across_blocks', 'cross_split_semantic_ancestry')
    assert result.component_by_family['fam-a'] == result.component_by_family['fam-b']


def test_independent_families_pass_mechanical_audit():
    inv = inventory(family('fam-a'), family('fam-b'))
    assert family_components(inv) == (('fam-a',), ('fam-b',))
    result = audit(inv)
    assert result.status == 'mechanical_only' and result.reasons == ()
    assert (result.effective_train_blocks, result.effective_development_blocks, result.effective_test_blocks) == (1, 1, 0)


def test_shared_lexicon_ancestor_is_flagged_across_splits():
    shared = Ancestor(ancestor_id='shared-lex', kind='lexicon', source_sha256=digest('shared-lex'))
    inv = inventory(family('fam-a', lexicon_ancestor='shared-lex'), family('fam-b', lexicon_ancestor='shared-lex'),
                    extra=(shared,))
    assert_cross_split_flagged(inv)


def test_shared_ancestor_through_parent_chain_is_flagged():
    root = Ancestor(ancestor_id='shared-scenario-root', kind='scenario', source_sha256=digest('root'))
    inv = inventory(family('fam-a', scenario_parent='shared-scenario-root'),
                    family('fam-b', scenario_parent='shared-scenario-root'), extra=(root,))
    assert_cross_split_flagged(inv)


def test_relabelled_ancestor_with_same_source_is_flagged():
    # New IDs cannot erase a common template derivation: same kind + source hash.
    inv = inventory(family('fam-a', template_source=digest('common-template')),
                    family('fam-b', template_source=digest('common-template')))
    assert_cross_split_flagged(inv)


def test_shared_entity_value_alone_is_flagged():
    # NFKC + casefold: "MIRA VALE" and "Mira Vale" are the same pooled value.
    inv = inventory(family('fam-a', name='Mira Vale'), family('fam-b', name='MIRA VALE'))
    assert_cross_split_flagged(inv)


def test_shipped_public_development_inventory_is_one_component():
    # Five recipe families deliberately share every ancestor: one component, never five units.
    assert family_components(development_inventory()) == ((
        'public-challenge-benign', 'public-challenge-prompt', 'public-challenge-unicode',
        'public-normal-benign', 'public-normal-contact'),)
