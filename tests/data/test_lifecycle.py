"""Custody lifecycle on tmp_path: freeze -> seal -> release -> open once; revoke; successor editions."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from m7.data.corpus import seal_corpus
from m7.data.lifecycle import CustodyLifecycle, freeze_binding
from m7.data.lifecycle_models import CustodyActionAuthorization, OpenReceipt
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
                             supersedes_edition_id=supersedes)
    return chain.lifecycle.freeze(inventory, successor_plan, assignments, custodian_id=CUSTODIAN,
                                  authorization=action(chain.host, 'ed-2', 'freeze', binding),
                                  supersedes_edition_id=supersedes)


def test_successor_supersedes_without_reopening_predecessor(tmp_path):
    chain = released_chain(tmp_path)
    chain.lifecycle.authorize_open(chain.edition, False)
    supersede(chain)
    inventory, assignments = sealed_inventory('g2')  # fresh test families, disjoint source pins
    receipt = freeze_successor(chain, inventory, assignments)
    assert receipt.supersedes_edition_id == 'ed-1'
    assert phases(chain.lifecycle) == {'ed-1': 'superseded', 'ed-2': 'frozen'}
    # The superseded predecessor cannot be reopened or resumed; the successor is not released.
    refused('custody_revoked_or_superseded', chain.lifecycle.authorize_open, chain.edition, True)
    refused('sealed_edition_required', chain.lifecycle.release, 'ed-2',
            selection_lock=None, authorization=None)
    assert chain.lifecycle.inspect()['event_count'] == 6  # freeze, seal, release, open, supersede, freeze


def test_successor_reusing_predecessor_inventory_refused(tmp_path):
    chain = released_chain(tmp_path)
    supersede(chain)
    inventory, assignments = sealed_inventory('g1')  # same families/test sources as ed-1
    refused('invalid_replacement_inventory', freeze_successor, chain, inventory, assignments)
    assert phases(chain.lifecycle) == {'ed-1': 'superseded'}


def test_successor_without_supersede_reservation_refused(tmp_path):
    chain = released_chain(tmp_path)
    inventory, assignments = sealed_inventory('g2')
    refused('replacement_edition_reservation_mismatch', freeze_successor, chain, inventory, assignments)
