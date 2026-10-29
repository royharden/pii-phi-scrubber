"""Mechanical declared-ancestry audit only; never independent custody acceptance."""

import argparse
from pathlib import Path

from _common import emit, guarded, load_json


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = inspect_manifest(load_json(args.manifest))
    emit(result)
    return 2 if result["status"] == "blocked" or not result.get("minimum_count_met", False) else 0


if __name__ == "__main__":
    guarded(main)
