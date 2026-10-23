"""Safe inventory/bundle/lifecycle inspection. Never prints examples or gold rows."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from m7.data import BlockAssignment, CorpusPlan, CustodyLifecycle, FamilyInventory, audit_inventory, commitment, family_components
from m7.data.development import development_inventory, generator_source_hash
from m7.data.storage import read_bundle
from m7.data.filesystem import checked_path
from m7.data import IsolationCapability, IsolationRequest, build_audit_handoff


def main(*, filesystem=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('pins', help='Current source/guide pins; no corpus generation')
    inventory_parser = commands.add_parser('inventory')
    inventory_parser.add_argument('--inventory', type=Path)
    inventory_parser.add_argument('--plan', type=Path)
    inventory_parser.add_argument('--assignments', type=Path)
    bundle_parser = commands.add_parser('bundle')
    bundle_parser.add_argument('--directory', type=Path, required=True)
    store_parser = commands.add_parser('store')
    store_parser.add_argument('--root', type=Path, required=True)
    handoff_parser = commands.add_parser('audit-handoff')
    for name in ('inventory', 'plan', 'assignments'):
        handoff_parser.add_argument('--' + name, type=Path, required=True)
    handoff_parser.add_argument('--custodian-id', required=True)
    handoff_parser.add_argument('--implementation-author', action='append', required=True)
    handoff_parser.add_argument('--bundle-directory', type=Path)
    capability_parser = commands.add_parser('capability', help='Shape inspection only, never enforcement approval')
    capability_parser.add_argument('--capability', type=Path, required=True)
    capability_parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'pins':
        result = {'guide_sha256': hashlib.sha256((ROOT / 'docs/annotation-guide.md').read_bytes()).hexdigest(),
                  'generator_sha256': generator_source_hash()}
    elif args.command == 'inventory':
        inventory = (FamilyInventory.model_validate_json(checked_path(args.inventory).read_bytes())
                     if args.inventory else development_inventory())
        if args.inventory and any(f.visibility == 'custodian_private' for f in inventory.families):
            if filesystem is None:
                raise ValueError('private_inventory_requires_custody_filesystem')
            filesystem.require_path('private', args.inventory)
        groups = family_components(inventory)
        result = {'schema_version': 'InventoryInspection/v1', 'inventory_sha256': commitment(inventory),
                  'declared_families': len(inventory.families), 'effective_components': len(groups),
                  'independent_verdict_issued': False}
        if (args.plan is None) != (args.assignments is None):
            raise ValueError('plan_and_assignments_required_together')
        if args.plan is not None:
            plan = CorpusPlan.model_validate_json(args.plan.read_bytes())
            raw = json.loads(args.assignments.read_bytes())
            if not isinstance(raw, list):
                raise ValueError('assignment_array_required')
            assignments = tuple(BlockAssignment.model_validate_json(json.dumps(row, allow_nan=False)) for row in raw)
            audit = audit_inventory(inventory, assignments, plan)
            summary = audit.model_dump(mode='json')
            summary.pop('component_by_family')
            result['audit'] = summary
    elif args.command == 'bundle':
        bundle = read_bundle(args.directory, filesystem=filesystem)
        result = {'schema_version': 'BundleInspection/v1', 'manifest_sha256': commitment(bundle.manifest),
                  'scope': bundle.manifest.scope, 'record_count': bundle.manifest.record_count,
                  'split_counts': bundle.manifest.split_counts, 'gold_counts': bundle.manifest.gold_counts,
                  'effective_blocks': bundle.manifest.effective_blocks, 'independent_verdict_issued': False}
    elif args.command == 'store':
        # A deny-all verifier is sufficient for inspection; no authorization issued.
        result = CustodyLifecycle(args.root, verify_receipt=lambda kind, digest: False).inspect()
    elif args.command == 'capability':
        capability = IsolationCapability.model_validate_json(checked_path(args.capability).read_bytes())
        request = IsolationRequest.model_validate_json(checked_path(args.request).read_bytes())
        result = {'schema_version': 'IsolationInspection/v1', 'capability_sha256': commitment(capability),
                  'request_sha256': commitment(request), 'platform_enforcement_verified': False,
                  'status': 'shape_only_not_authorized'}
    else:
        if filesystem is None:
            raise ValueError('audit_handoff_host_requires_custody_filesystem')
        inventory = FamilyInventory.model_validate_json(filesystem.read_private(args.inventory))
        plan = CorpusPlan.model_validate_json(filesystem.read_private(args.plan))
        raw = json.loads(filesystem.read_private(args.assignments))
        if not isinstance(raw, list):
            raise ValueError('assignment_array_required')
        assignments = tuple(BlockAssignment.model_validate_json(json.dumps(row, allow_nan=False)) for row in raw)
        bundle = read_bundle(args.bundle_directory, filesystem=filesystem) if args.bundle_directory else None
        result = build_audit_handoff(inventory, plan, assignments, custodian_id=args.custodian_id,
                    implementation_author_ids=tuple(args.implementation_author), bundle=bundle).model_dump(mode='json')
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    audit = result.get('audit')
    return 2 if audit and audit['status'] == 'blocked' else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        print('{"status":"blocked","reason":"invalid_or_unavailable_custody_input"}')
        raise SystemExit(2) from None
