"""Generator-defined gold for public fictional records, and gold-free inference exports."""
import hashlib
import json

import pytest

from m7.data.corpus import generate_development, inference_records
from m7.data.models import Ancestor, CorpusPlan, Family, FamilyInventory, Lexicon, Recipe, Segment
from m7.data.provenance import canonical_bytes

from .custody_fixtures import TrustedHost, custody_filesystem, digest

# Public fictional values (same as the shipped development fixture), one value per pool so each
# recipe expands to exactly one message.
NAME, EMAIL, PHONE, ACCOUNT = 'Mira Vale', 'mira.vale@example.invalid', '+12025550123', 'ACCT-731'
CONTACT_MESSAGE = f'person: {NAME}; email: {EMAIL}; phone: {PHONE}; account_id={ACCOUNT}'
# "person: " 8 -> NAME [8, 17) (9); "; email: " 9 -> 26, EMAIL 25 -> [26, 51); "; phone: " 9 -> 60,
# PHONE 12 -> [60, 72); "; account_id=" 13 -> 85, ACCOUNT 8 -> [85, 93).
CONTACT_SPANS = [(8, 17, 'NAME'), (26, 51, 'EMAIL'), (60, 72, 'PHONE'), (85, 93, 'ACCOUNT_ID')]
# Prefix U+1F600, " ", "e", U+0301, CR, LF = 6 code points (no NFC, no newline rewriting): +6 each;
# then "; again: " 9 -> 99 + 9 = 108, EMAIL 25 -> [108, 133).
UNICODE_PREFIX = '\U0001f600 é\r\n'
UNICODE_SPANS = [(14, 23, 'NAME'), (32, 57, 'EMAIL'), (66, 78, 'PHONE'), (91, 99, 'ACCOUNT_ID'),
                 (108, 133, 'EMAIL')]
GOLD_FREE_KEYS = {'spans', 'gold', 'label', 'start', 'end', 'provenance', 'family_id', 'recipe_id',
                  'block_id', 'taxonomy', 'difficulty', 'split', 'sample_index'}


def public_inventory() -> FamilyInventory:
    ancestors = tuple(Ancestor(ancestor_id=f'pub-{kind}', kind=kind, source_sha256=digest(f'pub-{kind}'))
                      for kind in ('lexicon', 'identifier_grammar', 'scenario', 'template'))
    lexicons = tuple(Lexicon(lexicon_id=name, ancestor_id='pub-lexicon', label=label, values=(value,))
                     for name, label, value in (('people', 'NAME', NAME), ('mail', 'EMAIL', EMAIL),
                                                ('phones', 'PHONE', PHONE), ('accounts', 'ACCOUNT_ID', ACCOUNT)))
    contact = (Segment(text='person: '), Segment(lexicon_id='people'), Segment(text='; email: '),
               Segment(lexicon_id='mail'), Segment(text='; phone: '), Segment(lexicon_id='phones'),
               Segment(text='; account_id='), Segment(lexicon_id='accounts'))
    recipes = (
        Recipe(recipe_id='contact', difficulty='normal', taxonomy=('normal_context',), segments=contact),
        Recipe(recipe_id='unicode', difficulty='challenge', taxonomy=('unicode_offsets', 'multiline'),
               segments=(Segment(text=UNICODE_PREFIX), *contact, Segment(text='; again: '),
                         Segment(lexicon_id='mail'))),
        Recipe(recipe_id='benign', difficulty='normal', taxonomy=('benign_identifiers',),
               segments=(Segment(text='trace_id=REQ-401 latency=731'),)),
        Recipe(recipe_id='benign-port', difficulty='challenge', taxonomy=('phone_vs_port',),
               segments=(Segment(text='port=55501 latency=12025550123'),)),
    )
    family = Family(family_id='pub-family', ancestors=('pub-identifier_grammar', 'pub-scenario', 'pub-template'),
                    recipes=recipes, author_id='dev-author-1', visibility='development')
    return FamilyInventory(inventory_id='pub-inv', ancestors=ancestors, lexicons=lexicons, families=(family,))


def bundle():
    corpus_plan = CorpusPlan(edition_id='dev-ed', split_seed=1, sampling_seed=2, records_per_block=10,
                             guide_sha256=digest('guide'), generator_sha256=digest('generator'),
                             selection_rule_sha256=digest('selection-rule'))
    return generate_development(public_inventory(), corpus_plan)


def keys(value):
    if isinstance(value, dict):
        return set(value) | set().union(*(keys(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(keys(v) for v in value)) if value else set()
    return set()


def test_generator_gold_matches_hand_computed_spans():
    expected = {'contact': (CONTACT_MESSAGE, CONTACT_SPANS),
                'unicode': (UNICODE_PREFIX + CONTACT_MESSAGE + '; again: ' + EMAIL, UNICODE_SPANS),
                'benign': ('trace_id=REQ-401 latency=731', []),
                'benign-port': ('port=55501 latency=12025550123', [])}
    corpus = bundle()
    assert len(corpus.records) == 10
    seen = set()
    for record, gold, provenance in zip(corpus.records, corpus.gold, corpus.provenance, strict=True):
        message, spans = expected[provenance.recipe_id]
        seen.add(provenance.recipe_id)
        assert record.log.message == message
        assert record.content_sha256 == gold.content_sha256 == hashlib.sha256(message.encode('utf-8')).hexdigest()
        assert [(s.start, s.end, s.label) for s in gold.spans] == spans
    # Benign stratum = ceil(10 * 0.2) = 2 records drawn from the two entity-free recipes; the other 8
    # come from the entity recipes, which always carry spans.
    assert seen & {'benign', 'benign-port'}
    assert sum(1 for g in corpus.gold if not g.spans) == 2


def test_inference_records_carry_no_gold_or_provenance():
    corpus = bundle()
    records = inference_records(corpus)
    assert [r.record_id for r in records] == [r.record_id for r in corpus.records]
    for record in records:
        dumped = record.model_dump(mode='json')
        assert set(dumped) == {'schema_version', 'record_id', 'split_id', 'synthetic', 'content_sha256', 'log'}
        assert set(dumped['log']) == {'timestamp', 'level', 'event', 'message'}
        assert dumped['split_id'] == 'inference'
        # Opaque IDs: "r-" + 32 hex, revealing neither family nor recipe.
        assert len(record.record_id) == 34 and record.record_id.startswith('r-')
        assert 'pub-family' not in record.record_id and 'contact' not in record.record_id


def inference_manifest(records):
    return {'schema_version': 'ReleasedChannel/v1', 'edition_id': 'dev-ed', 'run_id': 'run-1',
            'custody_release_sha256': digest('release'), 'record_count': len(records), 'channel': 'inference',
            'records_sha256': hashlib.sha256(canonical_bytes(records)).hexdigest()}


def test_inference_export_on_disk_lacks_every_gold_field(tmp_path):
    filesystem = custody_filesystem(tmp_path, TrustedHost())
    records = inference_records(bundle())
    target = filesystem.roots()['inference'] / 'export-1'
    filesystem.write_export('inference', target, (('records.json', records),
                                                  ('manifest.json', inference_manifest(records))),
                            export_id='export-1')
    assert {p.name for p in target.iterdir()} == {'records.json', 'manifest.json', 'commitment.json'}
    for path in target.iterdir():
        assert not keys(json.loads(path.read_bytes())) & GOLD_FREE_KEYS


def test_inference_export_refuses_a_gold_channel(tmp_path):
    filesystem = custody_filesystem(tmp_path, TrustedHost())
    corpus = bundle()
    records = inference_records(corpus)
    with pytest.raises(ValueError, match='invalid_export_channel_files'):
        filesystem.write_export('inference', filesystem.roots()['inference'] / 'export-1',
                                (('records.json', records), ('gold.json', corpus.gold),
                                 ('manifest.json', inference_manifest(records))), export_id='export-1')


def test_inference_export_refuses_training_split_records(tmp_path):
    filesystem = custody_filesystem(tmp_path, TrustedHost())
    records = tuple(r.model_copy(update={'split_id': 'train'}) for r in inference_records(bundle()))
    with pytest.raises(ValueError, match='wrong_record_export_role'):
        filesystem.write_export('inference', filesystem.roots()['inference'] / 'export-1',
                                (('records.json', records), ('manifest.json', inference_manifest(records))),
                                export_id='export-1')


def test_test_split_cannot_be_generated_outside_custody():
    from m7.data.models import BlockAssignment
    corpus_plan = CorpusPlan(edition_id='dev-ed', split_seed=1, sampling_seed=2, records_per_block=10,
                             guide_sha256=digest('guide'), generator_sha256=digest('generator'),
                             selection_rule_sha256=digest('selection-rule'))
    test_block = (BlockAssignment(block_id='b-1', split='test', family_ids=('pub-family',)),)
    with pytest.raises(ValueError, match='test_generation_requires_custodian'):
        generate_development(public_inventory(), corpus_plan, test_block)
