"""Mechanical declared-ancestry audit only; never independent custody acceptance."""

import argparse
from pathlib import Path

from _common import emit, guarded, load_json

from m7.data import CorpusManifest, CorpusPlan, FamilyInventory, audit_inventory, commitment
from m7.data.storage import read_bundle


def inspect_manifest(manifest: dict) -> dict:
    if set(manifest) != {"schema_version", "blocks"} or manifest["schema_version"] != "SplitManifest/v1":
        raise ValueError("invalid_manifest")
    blocks = manifest["blocks"]
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("empty_manifest")
    ancestry = {}
    ids = set()
    test_blocks = 0
    for block in blocks:
        if not isinstance(block, dict) or set(block) != {"block_id", "split", "ancestors"}:
            raise ValueError("invalid_block")
        identity, split, ancestors = block["block_id"], block["split"], block["ancestors"]
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError("duplicate_or_invalid_block")
        if split not in ("train", "development", "test") or not isinstance(ancestors, list) or not ancestors:
            raise ValueError("missing_ancestry")
        ids.add(identity)
        test_blocks += split == "test"
        for ancestor in ancestors:
            if not isinstance(ancestor, str) or not ancestor:
                raise ValueError("invalid_ancestor")
            if ancestor in ancestry and ancestry[ancestor] != split:
                return {"status": "blocked", "reason": "cross_split_ancestry", "independent_audit": "pending"}
            ancestry[ancestor] = split
    # Test blocks sharing any ancestor must be merged; union transitive components.
    parents = list(range(len(blocks)))
    def root(i):
        while parents[i] != i:
            i = parents[i]
        return i
    seen = {}
    for index, block in enumerate(blocks):
        for ancestor in block["ancestors"]:
            if ancestor in seen:
                parents[root(index)] = root(seen[ancestor])
            seen[ancestor] = index
    effective = len({root(i) for i, block in enumerate(blocks) if block["split"] == "test"})
    return {"status": "mechanical_only", "declared_test_blocks": test_blocks,
            "effective_declared_test_components": effective, "minimum_count_met": effective >= 20,
            "independent_audit": "pending", "label_audit": "pending", "custody_accepted": False}


def main(*, filesystem=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args()
    manifest_path = filesystem.require_path('private', args.manifest) if filesystem else args.manifest
    manifest = load_json(manifest_path)
    if manifest.get('schema_version') == 'CorpusManifest/v1':
        if args.bundle_dir is None or args.inventory is None or args.plan is None:
            raise ValueError('full_custody_audit_inputs_required')
        declared = CorpusManifest.model_validate_json(filesystem.read_private(manifest_path) if filesystem else manifest_path.read_bytes())
        bundle = read_bundle(args.bundle_dir, filesystem=filesystem)
        inventory = FamilyInventory.model_validate_json(filesystem.read_private(args.inventory))
        plan = CorpusPlan.model_validate_json(filesystem.read_private(args.plan))
        if (bundle.manifest != declared or commitment(inventory) != declared.inventory_sha256
                or commitment(plan) != declared.plan_sha256):
            raise ValueError('audit_input_commitment_mismatch')
        audit = audit_inventory(inventory, bundle.assignments, plan,
                                development_only=declared.scope == 'development_only')
        if commitment(audit) != declared.audit_sha256:
            raise ValueError('recomputed_audit_mismatch')
        result = audit.model_dump(mode='json')
        result.pop('component_by_family')
    else:
        # Legacy declarations do not prove guide/label/content integrity.
        result = inspect_manifest(manifest)
    emit(result)
    return 2 if result["status"] == "blocked" or not result.get("minimum_count_met", False) else 0


if __name__ == "__main__":
    guarded(main)
