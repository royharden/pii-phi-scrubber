"""Public hand-authored pre-R3 receipts: preserve commitments, never invent proof."""

import hashlib
import json

import pytest

from m7.data.custody_journal import CustodyJournal
from m7.data.lifecycle import _states
from m7.data.lifecycle_models import CustodyEvent, FreezeReceipt
from m7.data.provenance import canonical_bytes


def old_freeze():
    # Literal old schema, deliberately omitting the later optional field.
    return dict(schema_version="CustodyFreeze/v1", edition_id="legacy-edition", custodian_id="custodian",
                inventory_sha256="1" * 64, plan_sha256="2" * 64, guide_sha256="3" * 64,
                generator_sha256="4" * 64, assignments_sha256="5" * 64, selection_rule_sha256="6" * 64,
                family_author_ids=["author"], test_semantic_source_pins=["7" * 64], split_seed=1,
                sampling_seed=2, benign_fraction=0.2, challenge_fraction=0.25,
                authorization_sha256="8" * 64, frozen_at="2026-01-01T00:00:00Z", supersedes_edition_id=None)


def canonical(value):
    # Independent JSON oracle, not the application's commitment helper.
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def test_old_absent_field_preserves_exact_canonical_bytes():
    # Bug caught: inserting a default null into an old receipt changes its hash.
    old = old_freeze()
    receipt = FreezeReceipt.model_validate_json(json.dumps(old))
    assert canonical_bytes(receipt) == canonical(old)
    assert receipt.entity_disjoint_from_inventory_sha256 is None


def test_modern_explicit_null_is_not_rewritten_as_legacy_absence():
    explicit = dict(old_freeze(), entity_disjoint_from_inventory_sha256=None)
    receipt = FreezeReceipt.model_validate_json(json.dumps(explicit))
    assert canonical_bytes(receipt) == canonical(explicit)
    assert hashlib.sha256(canonical(explicit)).digest() != hashlib.sha256(canonical(old_freeze())).digest()


def test_old_nested_event_hash_chain_replays_without_file_mutation(tmp_path):
    # Real on-disk journal read, synthetic public receipt fields only. The second
    # event commits to the original old first event, including field absence.
    first = dict(schema_version="CustodyEvent/v1", sequence=1, previous_sha256="0" * 64, receipt=old_freeze())
    # Derive schema_version from the public boundary default, not any private data.
    first["schema_version"] = CustodyEvent.model_fields["schema_version"].default
    second = dict(first, sequence=2, previous_sha256=hashlib.sha256(canonical(first)).hexdigest(),
                  receipt=dict(old_freeze(), edition_id="another-edition"))
    directory = tmp_path / "custody-events"
    directory.mkdir()
    snapshots = {}
    for index, row in enumerate((first, second), 1):
        path = directory / f"{index:08d}.json"
        snapshots[path] = canonical(row)
        path.write_bytes(snapshots[path])
    events = CustodyJournal(tmp_path).events()
    assert len(events) == 2
    assert canonical_bytes(events[0]) == snapshots[directory / "00000001.json"]
    assert all(path.read_bytes() == raw for path, raw in snapshots.items())


def test_legacy_successor_without_entity_proof_remains_refused(tmp_path):
    # Compatibility must not manufacture a successor's entity-disjointness proof.
    from .custody_fixtures import sealed_inventory
    from .test_lifecycle import freeze_successor, released_chain, supersede

    chain = released_chain(tmp_path)
    supersede(chain)
    inventory, assignments = sealed_inventory("g2")
    freeze_successor(chain, inventory, assignments)
    events = chain.lifecycle.journal.events()
    legacy = events[-1].model_dump(mode="json")
    legacy["receipt"].pop("entity_disjoint_from_inventory_sha256")
    parsed = CustodyEvent.model_validate_json(json.dumps(legacy))
    with pytest.raises(ValueError, match="replacement_entity_check_mismatch"):
        _states((*events[:-1], parsed))
