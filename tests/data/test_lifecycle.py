"""Custody lifecycle on tmp_path: freeze -> seal -> release -> open once; revoke; successor editions."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from m7.data.corpus import seal_corpus
from m7.data.corpus import normalize_entity_value
from m7.data.lifecycle import CustodyLifecycle, _states, freeze_binding
from m7.data.lifecycle_models import CustodyActionAuthorization, CustodyEvent, OpenReceipt
from m7.data.provenance import commitment

from .custody_fixtures import (
    CUSTODIAN, EXPIRES, ISSUED, T0, TrustedHost, action, custody_filesystem, digest, edition_for,
    isolation_guard, plan, release_inputs, seal_authorization, sealed_inventory,
)


def released_chain(tmp_path):
    host = TrustedHost()
    filesystem = custody_filesystem(tmp_path, host)
    journal = tmp_path.resolve() / 'private' / 'journal'
    journal.mkdir()
    inventory, assignments = sealed_inventory()
    corpus_plan = plan('ed-1')
    lifecycle = CustodyLifecycle(journal, verify_receipt=host, clock=lambda: T0, filesystem=filesystem)
    binding = freeze_binding(inventory, corpus_plan, assignments, custodian_id=CUSTODIAN)
    lifecycle.freeze(inventory, corpus_plan, assignments, custodian_id=CUSTODIAN,
                     authorization=action(host, 'ed-1', 'freeze', binding))
    authorization = seal_authorization(host, inventory, corpus_plan)
    lifecycle.validate_seal_inputs(inventory, corpus_plan, assignments, authorization)
    bundle = seal_corpus(inventory, corpus_plan, assignments, authorization, now=T0)
    seal = lifecycle.seal(bundle, authorization=authorization)
    manifest_sha256 = commitment(bundle.manifest)
    guard = isolation_guard(filesystem, host, edition_id='ed-1', manifest_sha256=manifest_sha256)
    # Same on-disk journal; a lifecycle that also holds the activation guard for release/open.
    lifecycle = CustodyLifecycle(journal, verify_receipt=host, clock=lambda: T0, filesystem=filesystem,
                                 isolation_guard=guard)
    lock, release_authorization = release_inputs(host, seal, edition_id='ed-1',
                                                 manifest_sha256=manifest_sha256, guard=guard)
    release = lifecycle.release('ed-1', selection_lock=lock, authorization=release_authorization)
    return SimpleNamespace(host=host, lifecycle=lifecycle, bundle=bundle, seal=seal, release=release,
                           inventory=inventory,
                           edition=edition_for(release, bundle))


def phases(lifecycle):
    return {row['edition_id']: row['phase'] for row in lifecycle.inspect()['editions']}


def refused(message, call, *args, **kwargs):
    with pytest.raises(ValueError, match=message):
        call(*args, **kwargs)


def test_sealed_corpus_counts_are_the_planned_strata(tmp_path):
    chain = released_chain(tmp_path)
    manifest = chain.bundle.manifest
    # 1 train + 1 dev + 20 test blocks x 20 records; 4 benign + 16 entity records per block,
    # each entity record carries exactly one span per class.
    assert manifest.split_counts == {'train': 20, 'development': 20, 'test': 400}
    assert manifest.gold_counts['test'] == {'NAME': 320, 'EMAIL': 320, 'PHONE': 320, 'ACCOUNT_ID': 320}
    assert manifest.gold_counts['train'] == {'NAME': 16, 'EMAIL': 16, 'PHONE': 16, 'ACCOUNT_ID': 16}
    assert manifest.effective_blocks == {'train': 1, 'development': 1, 'test': 20}
    assert chain.seal.intended_test_records == 400
    assert phases(chain.lifecycle) == {'ed-1': 'released'}


def test_open_once_then_second_open_refused(tmp_path):
    chain = released_chain(tmp_path)
    opened = chain.lifecycle.authorize_open(chain.edition, False)
    assert isinstance(opened, OpenReceipt) and opened.run_id == 'run-1'
    assert chain.lifecycle.inspect()['event_count'] == 4  # freeze, seal, release, open
    refused('custody_already_opened_investigate_original_journal',
            chain.lifecycle.authorize_open, chain.edition, False)
    # Only the already-open journal may resume, and it gets the SAME receipt, not a new open.
    assert chain.lifecycle.authorize_open(chain.edition, True) == opened
    refused('edition_already_opened_with_other_fingerprint', chain.lifecycle.authorize_open,
            replace(chain.edition, sha256=digest('other-locked-edition')), True)
    assert chain.lifecycle.inspect()['event_count'] == 4
    assert phases(chain.lifecycle) == {'ed-1': 'opened'}


def test_resume_of_unopened_custody_refused(tmp_path):
    chain = released_chain(tmp_path)
    refused('cannot_resume_unopened_custody', chain.lifecycle.authorize_open, chain.edition, True)


def test_revoke_then_open_refused(tmp_path):
    chain = released_chain(tmp_path)
    binding = {'edition_id': 'ed-1', 'reason_code': 'custody_compromised'}
    chain.lifecycle.revoke('ed-1', reason_code='custody_compromised',
                           authorization=action(chain.host, 'ed-1', 'revoke', binding))
    refused('custody_revoked_or_superseded', chain.lifecycle.authorize_open, chain.edition, False)
    refused('custody_revoked_or_superseded', chain.lifecycle.require_released, chain.edition)
    assert chain.lifecycle.inspect()['event_count'] == 4  # freeze, seal, release, revoke; no open
    assert phases(chain.lifecycle) == {'ed-1': 'revoked'}


def test_unauthenticated_revoke_is_refused(tmp_path):
    chain = released_chain(tmp_path)
    binding = {'edition_id': 'ed-1', 'reason_code': 'custody_compromised'}
    unapproved = CustodyActionAuthorization(authorization_id='rogue', edition_id='ed-1', action='revoke',
                                            binding_sha256=commitment(binding), issued_at=ISSUED,
                                            expires_at=EXPIRES)
    refused('custody_receipt_not_authenticated_or_revoked', chain.lifecycle.revoke, 'ed-1',
            reason_code='custody_compromised', authorization=unapproved)
    assert phases(chain.lifecycle) == {'ed-1': 'released'}


def supersede(chain, replacement='ed-2'):
    binding = {'edition_id': 'ed-1', 'replacement_edition_id': replacement}
    chain.lifecycle.supersede('ed-1', replacement, authorization=action(chain.host, 'ed-1', 'supersede', binding))


def freeze_successor(chain, inventory, assignments, supersedes='ed-1'):
    successor_plan = plan('ed-2')
    binding = freeze_binding(inventory, successor_plan, assignments, custodian_id=CUSTODIAN,
                             supersedes_edition_id=supersedes, predecessor_inventory=chain.inventory)
    return chain.lifecycle.freeze(inventory, successor_plan, assignments, custodian_id=CUSTODIAN,
                                  authorization=action(chain.host, 'ed-2', 'freeze', binding),
                                  supersedes_edition_id=supersedes, predecessor_inventory=chain.inventory)


def test_successor_supersedes_without_reopening_predecessor(tmp_path):
    chain = released_chain(tmp_path)
    chain.lifecycle.authorize_open(chain.edition, False)
    supersede(chain)
    inventory, assignments = sealed_inventory('g2')  # fresh test families, disjoint source pins
    receipt = freeze_successor(chain, inventory, assignments)
    assert receipt.supersedes_edition_id == 'ed-1'
    # Only the predecessor inventory commitment is recorded; no entity value appears in the receipt.
    assert receipt.entity_disjoint_from_inventory_sha256 == commitment(chain.inventory)
    assert 'mira vale' not in receipt.model_dump_json().casefold()
    assert phases(chain.lifecycle) == {'ed-1': 'superseded', 'ed-2': 'frozen'}
    # The superseded predecessor cannot be reopened or resumed; the successor is not released.
    refused('custody_revoked_or_superseded', chain.lifecycle.authorize_open, chain.edition, True)
    refused('sealed_edition_required', chain.lifecycle.release, 'ed-2',
            selection_lock=None, authorization=None)
    assert chain.lifecycle.inspect()['event_count'] == 6  # freeze, seal, release, open, supersede, freeze


def test_successor_reusing_predecessor_inventory_refused(tmp_path):
    chain = released_chain(tmp_path)
    supersede(chain)
    inventory, assignments = sealed_inventory('g1')  # same families, values and sources as ed-1
    refused('replacement_entity_value_reuse', freeze_successor, chain, inventory, assignments)
    assert phases(chain.lifecycle) == {'ed-1': 'superseded'}


def with_lexicon_value(inventory, lexicon_id, value):
    lexicons = tuple(x.model_copy(update={'values': (value,)}) if x.lexicon_id == lexicon_id else x
                     for x in inventory.lexicons)
    return inventory.model_copy(update={'lexicons': lexicons})


@pytest.mark.parametrize('reused', [
    'Mira Vale G1N02',          # exact predecessor test NAME (index 2 is the first test family)
    '  MIRA   vale\tG1n02 ',    # same after casefold + whitespace collapse/strip
])
def test_successor_reusing_one_test_entity_value_refused(tmp_path, reused):
    chain = released_chain(tmp_path)
    supersede(chain)
    inventory, assignments = sealed_inventory('g2')
    inventory = with_lexicon_value(inventory, 'fam-g2-05-name', reused)
    refused('replacement_entity_value_reuse', freeze_successor, chain, inventory, assignments)
    assert chain.lifecycle.inspect()['event_count'] == 4  # freeze, seal, release, supersede


def test_predecessor_train_value_is_not_a_test_reuse(tmp_path):
    # Index 0 is the predecessor's TRAIN family; only held-out (test) values are compared.
    chain = released_chain(tmp_path)
    supersede(chain)
    inventory, assignments = sealed_inventory('g2')
    inventory = with_lexicon_value(inventory, 'fam-g2-05-name', 'Mira Vale G1N00')
    assert freeze_successor(chain, inventory, assignments).edition_id == 'ed-2'


def test_successor_sharing_a_test_source_pin_refused(tmp_path):
    # Values fresh, but one test template keeps the predecessor's semantic source hash.
    chain = released_chain(tmp_path)
    supersede(chain)
    inventory, assignments = sealed_inventory('g2')
    ancestors = tuple(a.model_copy(update={'source_sha256': digest('fam-g1-02-template')})
                      if a.ancestor_id == 'fam-g2-02-template' else a for a in inventory.ancestors)
    inventory = inventory.model_copy(update={'ancestors': ancestors})
    refused('invalid_replacement_inventory', freeze_successor, chain, inventory, assignments)


def test_successor_without_supersede_reservation_refused(tmp_path):
    chain = released_chain(tmp_path)
    inventory, assignments = sealed_inventory('g2')
    refused('replacement_edition_reservation_mismatch', freeze_successor, chain, inventory, assignments)


def test_successor_without_predecessor_inventory_refused(tmp_path):
    chain = released_chain(tmp_path)
    supersede(chain)
    inventory, assignments = sealed_inventory('g2')
    refused('predecessor_inventory_required_for_successor_only', freeze_binding, inventory, plan('ed-2'),
            assignments, custodian_id=CUSTODIAN, supersedes_edition_id='ed-1')


def test_replay_rejects_successor_freeze_without_entity_check(tmp_path):
    chain = released_chain(tmp_path)
    supersede(chain)
    inventory, assignments = sealed_inventory('g2')
    freeze_successor(chain, inventory, assignments)
    events = chain.lifecycle.journal.events()
    for forged in (None, commitment(inventory)):  # missing, or checked against the wrong inventory
        receipt = events[-1].receipt.model_copy(update={'entity_disjoint_from_inventory_sha256': forged})
        tampered = CustodyEvent(sequence=events[-1].sequence, previous_sha256=events[-1].previous_sha256,
                                receipt=receipt)
        refused('replacement_entity_check_mismatch', _states, (*events[:-1], tampered))


def test_entity_value_normalization_form():
    # NFC: "e" + U+0301 composes to U+00E9; casefold; whitespace runs -> one space; ends stripped.
    raw = '  Jose' + chr(0x301) + chr(9) + chr(10) + ' VALE '
    assert normalize_entity_value(raw) == 'jos' + chr(0xE9) + ' vale'
    assert normalize_entity_value('STRASSE') == 'strasse'
