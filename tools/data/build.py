"""Future development generation CLI. Never generates held-out data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from m7.data import BlockAssignment, CorpusPlan, FamilyInventory, generate_development
from m7.data.development import development_inventory, generator_source_hash
from m7.data.storage import write_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--inventory', type=Path)
    parser.add_argument('--assignments', type=Path, help='Explicit train/development assignments only')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    plan = CorpusPlan.model_validate_json(args.plan.read_bytes())
    guide = hashlib.sha256((ROOT / 'docs' / 'annotation-guide.md').read_bytes()).hexdigest()
    if plan.guide_sha256 != guide or plan.generator_sha256 != generator_source_hash():
        raise ValueError('source_or_guide_commitment_mismatch')
    inventory = (FamilyInventory.model_validate_json(args.inventory.read_bytes())
                 if args.inventory else development_inventory())
    assignments = None
    if args.assignments:
        raw = json.loads(args.assignments.read_bytes())
        if not isinstance(raw, list):
            raise ValueError('assignment_array_required')
        assignments = tuple(BlockAssignment.model_validate_json(json.dumps(row, allow_nan=False)) for row in raw)
    bundle = generate_development(inventory, plan, assignments)
    # The tool has no route to private families or test split construction.
    write_bundle(bundle, args.out)
    print(json.dumps({'status': 'development_only', 'records': bundle.manifest.record_count,
                      'independent_audit': 'pending', 'held_out_generated': False}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        print('{"status":"blocked","reason":"invalid_or_unavailable_input"}')
        raise SystemExit(2) from None
