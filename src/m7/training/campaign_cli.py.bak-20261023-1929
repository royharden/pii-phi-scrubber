"""Campaign CLI composition. Validation never creates a host or starts execution."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from m7.providers.contracts import AdapterFault
from .artifacts import load_object
from .campaign import CampaignHost, export_prepared_campaign, prepare_campaign, validate_campaign
from .campaign_models import CampaignSpec


def campaign_main(argv=None, *, host: CampaignHost | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--spec", type=Path, help="campaign-only control-plane validation/handoff")
    source.add_argument("--launch-bundle", type=Path, help="joined D6/D7 worker bundle or immutable handoff")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--activate", action="store_true",
                      help="future explicit authenticated handoff only; never runs an experiment")
    parser.add_argument("--check-files", action="store_true", help="read-only hash inspection, no model load")
    parser.add_argument("--out", type=Path, help="existing handoff directory; activation only")
    args = parser.parse_args(argv)
    # Strict duplicate-key/size/nonfinite guard before canonical schema parsing.
    try:
        if args.launch_bundle is not None:
            from .launch_bundle import export_launch_bundle, load_launch_bundle, prepare_launch_bundle, validate_launch_bundle
            bundle = load_launch_bundle(args.launch_bundle)
            if args.activate:
                if host is None:
                    return {"status": "unavailable", "reason": "authenticated_campaign_host_required",
                            "activation_allowed": False, "worker_started": False, "heldout_opened": False}
                prepared = prepare_launch_bundle(bundle, host=host)
                if args.out is not None:
                    return export_launch_bundle(prepared, args.out, host=host)
                return {"status": prepared.receipt.status, "bundle_sha256": bundle.sha256,
                        "preparation": prepared.receipt.model_dump(mode="json"),
                        "worker_started": False, "heldout_opened": False}
            if args.out is not None:
                raise ValueError("validation_cannot_write_handoff")
            return validate_launch_bundle(bundle, check_files=args.check_files)
        body = load_object(args.spec, max_bytes=8_000_000)
        spec = CampaignSpec.model_validate_json(json.dumps(body, allow_nan=False))
        if args.activate:
            if host is None:
                return {"status": "unavailable", "reason": "authenticated_campaign_host_required",
                        "activation_allowed": False, "runtime_executed": False}
            prepared = prepare_campaign(spec, host=host)
            if args.out is not None:
                return export_prepared_campaign(prepared, args.out, host=host)
            return {"status": prepared.receipt.status, "campaign_sha256": spec.sha256,
                    "activation": prepared.receipt.model_dump(mode="json"), "runtime_executed": False}
        if args.out is not None:
            raise ValueError("validation_cannot_write_handoff")
        return validate_campaign(spec, check_files=args.check_files)
    except AdapterFault:
        raise ValueError("campaign_adapter_prerequisite_unavailable") from None
