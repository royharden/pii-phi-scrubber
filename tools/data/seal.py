"""Future custodian sealing tool; requires private inventory and explicit receipts.

Not invoked during Dirty Mode. Typed receipts do not authenticate their issuer;
the operating custodian must verify the approval/audit originals out of band.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from m7.data import CorpusPlan, FamilyInventory, SealAuthorization, allocate_blocks, commitment, seal_corpus
from m7.data.development import generator_source_hash
from m7.data.storage import write_bundle
from m7.data.lifecycle import CustodyLifecycle


def main(*, verify_receipt=None, filesystem=None, isolation_guard=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('inventory', 'plan', 'authorization', 'approval-receipt', 'audit-receipt', 'private-root', 'out', 'custody-store'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--custodian-id', required=True)
    parser.add_argument('--resume-persisted', action='store_true', help='Seal an already written complete bundle without regeneration')
    args = parser.parse_args()
    if verify_receipt is None or filesystem is None:
        raise ValueError('trusted_receipt_authority_and_filesystem_required')
    from m7.data.filesystem import checked_path
    private_root, destination = checked_path(args.private_root), filesystem.require_path('private', args.out, must_exist=False)
    if not private_root.is_dir() or destination == private_root or not destination.is_relative_to(private_root):
        raise ValueError('destination_outside_private_custody')
    inventory = FamilyInventory.model_validate_json(filesystem.read_private(args.inventory))
    plan = CorpusPlan.model_validate_json(filesystem.read_private(args.plan))
    authorization = SealAuthorization.model_validate_json(filesystem.read_private(args.authorization))
    if authorization.custodian_id != args.custodian_id:
        raise ValueError('wrong_custodian_identity')
    for path, digest in ((args.approval_receipt, authorization.approval_receipt_sha256),
                         (args.audit_receipt, authorization.independent_audit_receipt_sha256),
                         (ROOT / 'docs' / 'annotation-guide.md', plan.guide_sha256)):
        raw = checked_path(path).read_bytes() if path == ROOT / 'docs' / 'annotation-guide.md' else filesystem.read_private(path)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('custody_receipt_or_guide_mismatch')
    if plan.generator_sha256 != generator_source_hash():
        raise ValueError('generator_commitment_mismatch')
    assignments = allocate_blocks(inventory, plan)
    lifecycle = CustodyLifecycle(args.custody_store, verify_receipt=verify_receipt,
                                filesystem=filesystem, isolation_guard=isolation_guard)
    if args.resume_persisted:
        from m7.data.storage import read_bundle
        bundle = read_bundle(args.out, filesystem=filesystem)
    else:
        lifecycle.validate_seal_inputs(inventory, plan, assignments, authorization)
        bundle = seal_corpus(inventory, plan, assignments, authorization)
        write_bundle(bundle, args.out, private_root=args.private_root, filesystem=filesystem)
    receipt = lifecycle.seal(bundle, authorization=authorization)
    print(json.dumps({'status': 'sealed_not_released', 'records': bundle.manifest.record_count,
                      'seal_receipt_sha256': commitment(receipt),
                      'independent_verdict_issued': False}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        print('{"status":"blocked","reason":"invalid_or_unavailable_custody_input"}')
        raise SystemExit(2) from None
