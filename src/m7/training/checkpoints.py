"""Local selected-checkpoint export and D6 parity. No model imports or downloads."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Callable

from m7.providers.contracts import LocalModelConfig, config_digest, verify_artifacts
from m7.providers.parity import validate_architecture, validate_pair
from .artifacts import file_sha256, inspect_artifacts, local_path, load_object, no_links, tree_sha256
from .executor import _write_json
from .selection import authenticate, Verifier
from .validation import digest, now_utc, validate_training_receipt


def _files(root: Path) -> dict[str, str]:
    manifest = {}
    for path in sorted(root.rglob("*")):
        no_links(path)
        if path.is_file():
            if path.suffix.lower() in {".py", ".pyc", ".pkl", ".pickle", ".bin", ".pt", ".pth"}:
                raise ValueError("unsafe_checkpoint_file")
            manifest[path.relative_to(root).as_posix()] = file_sha256(path)
    return manifest


def export_checkpoint(receipt: dict, plan: dict, permit: dict, *, staging_root: Path,
                      destination: Path, base_config: LocalModelConfig,
                      verify_receipt: Verifier, clock: Callable[[], datetime] = now_utc) -> dict:
    """Create a fresh D6-compatible artifact bundle, never overwrite originals.

    Rehome the local backbone path BEFORE calculating new export pins. Original
    checkpoint digest/receipt remain unchanged and separately referenced.
    """
    validate_training_receipt(receipt, plan, permit)
    authenticate(verify_receipt, "training_receipt", digest(receipt))
    authenticate(verify_receipt, "base_adapter_configuration", config_digest(base_config))
    staging_root = staging_root.resolve(strict=True)
    paths, metadata = inspect_artifacts(plan, staging_root)
    if (base_config.arm != "base" or base_config.training_receipt_sha256 is not None or
            file_sha256(paths["model"] / "model.safetensors") != base_config.weights_sha256 or
            base_config.gliner_version != metadata["environment"]["packages"]["gliner"] or
            base_config.transformers_version != metadata["environment"]["packages"]["transformers"]):
        raise ValueError("base_training_lineage_mismatch")
    verify_artifacts(base_config)
    if (metadata["config"]["decoder_sha256"] != digest(base_config.decoder.model_dump(mode="json", exclude={"threshold"})) or
            metadata["config"]["label_descriptions_sha256"] != digest(list(base_config.decoder.labels))):
        raise ValueError("training_inference_configuration_mismatch")
    checkpoint = local_path(staging_root, receipt["checkpoint_relative_path"])
    if tree_sha256(checkpoint) != receipt["checkpoint_sha256"]:
        raise ValueError("checkpoint_hash_mismatch")
    # Refuse executable/pickle payloads before copying any artifact.
    _files(checkpoint)
    _files(paths["tokenizer"])
    if not destination.is_absolute():
        raise ValueError("absolute_export_destination_required")
    for part in (destination, *destination.parents):
        no_links(part)
    destination.parent.resolve(strict=True)
    target = destination.resolve()
    if target.is_relative_to(staging_root) or staging_root.is_relative_to(target):
        raise ValueError("checkpoint_export_must_be_separate_from_training")
    target.mkdir(exist_ok=False)
    shutil.copytree(checkpoint, target / "model")
    shutil.copytree(paths["tokenizer"], target / "backbone")
    model_config_path = target / "model/gliner_config.json"
    architecture = load_object(model_config_path)
    architecture["model_name"] = str(target / "backbone")
    # This is a newly created export file; the trained source is never edited.
    model_config_path.write_text(json.dumps(architecture, sort_keys=True, allow_nan=False), encoding="utf-8")
    validate_architecture(architecture, base_config)
    manifest = _files(target)
    weights = manifest.get("model/model.safetensors")
    if weights is None:
        raise ValueError("safetensors_checkpoint_required")
    tokenizer_files = {k[len("backbone/"):]: v for k, v in manifest.items() if k.startswith("backbone/")}
    tokenizer_hash = digest(tokenizer_files)
    if tokenizer_hash != base_config.tokenizer_sha256:
        raise ValueError("export_tokenizer_parity_mismatch")
    exported = {"schema_version": "CheckpointExport/v1", "edition_id": plan["edition_id"],
        "trial_id": receipt["trial_id"], "training_receipt_sha256": digest(receipt),
        "plan_sha256": digest(plan), "original_checkpoint_sha256": receipt["checkpoint_sha256"],
        "export_root": str(target), "files": manifest, "artifact_tree_sha256": tree_sha256(target),
        "weights_sha256": weights, "tokenizer_sha256": tokenizer_hash,
        "architecture_sha256": base_config.architecture_sha256,
        "training_decoder_sha256": metadata["config"]["decoder_sha256"],
        "label_descriptions_sha256": metadata["config"]["label_descriptions_sha256"],
        "base_configuration_sha256": config_digest(base_config),
        "created_at": clock().isoformat(), "approved_for_publication": False}
    # Sidecar is outside the strict model artifact root, so the file manifest
    # remains closed and reloadable under D6 verify_artifacts.
    _write_json(target.parent / (target.name + ".export.json"), exported)
    return exported


def verify_checkpoint_export(export: dict, receipt: dict, plan: dict, permit: dict) -> None:
    validate_training_receipt(receipt, plan, permit)
    if (export["schema_version"] != "CheckpointExport/v1" or export["plan_sha256"] != digest(plan) or
            export["edition_id"] != plan["edition_id"] or export["trial_id"] != receipt["trial_id"] or
            export["training_receipt_sha256"] != digest(receipt) or
            export["original_checkpoint_sha256"] != receipt["checkpoint_sha256"]):
        raise ValueError("checkpoint_export_lineage_mismatch")
    root = Path(export["export_root"])
    for part in (root, *root.parents):
        no_links(part)
    if not root.is_absolute() or _files(root) != export["files"] or tree_sha256(root) != export["artifact_tree_sha256"]:
        raise ValueError("checkpoint_export_bytes_mismatch")


def configuration_from_export(export: dict, base: LocalModelConfig, *, model_id: str,
                               threshold: float) -> LocalModelConfig:
    """Construct a D6 fine config without loading a backend or changing policy."""
    if (export.get("schema_version") != "CheckpointExport/v1" or base.arm != "base" or
            export["tokenizer_sha256"] != base.tokenizer_sha256 or
            export["architecture_sha256"] != base.architecture_sha256):
        raise ValueError("checkpoint_configuration_parity_mismatch")
    payload = base.model_dump(mode="json")
    payload.update(arm="finetuned", model_id=model_id, artifact_root=export["export_root"],
                   model_subdir="model", backbone_subdir="backbone",
                   training_receipt_sha256=export["training_receipt_sha256"],
                   weights_sha256=export["weights_sha256"],
                   files=[{"relative_path": key, "sha256": value} for key, value in sorted(export["files"].items())])
    payload["decoder"]["threshold"] = threshold
    # JSON validation retains the canonical strict tuple schemas in D6.
    fine = LocalModelConfig.model_validate_json(json.dumps(payload, allow_nan=False))
    validate_pair(base, fine)
    return fine


def verify_parity(base: LocalModelConfig, fine: LocalModelConfig, *, receipt: dict,
                  plan: dict, permit: dict, export: dict, verify_receipt: Verifier) -> dict:
    """Reuse D6's canonical parity/artifact validators; add training lineage."""
    validate_pair(base, fine)
    verify_artifacts(base)
    verify_artifacts(fine)
    verify_checkpoint_export(export, receipt, plan, permit)
    authenticate(verify_receipt, "training_receipt", digest(receipt))
    authenticate(verify_receipt, "checkpoint_export", digest(export))
    authenticate(verify_receipt, "base_adapter_configuration", config_digest(base))
    authenticate(verify_receipt, "finetuned_adapter_configuration", config_digest(fine))
    if (fine.training_receipt_sha256 != digest(receipt) or fine.weights_sha256 != export["weights_sha256"] or
            fine.artifact_root != export["export_root"] or fine.tokenizer_sha256 != export["tokenizer_sha256"] or
            fine.architecture_sha256 != export["architecture_sha256"]):
        raise ValueError("fine_export_parity_mismatch")
    if (export["training_decoder_sha256"] != digest(base.decoder.model_dump(mode="json", exclude={"threshold"})) or
            export["label_descriptions_sha256"] != digest(list(base.decoder.labels))):
        raise ValueError("training_decoder_parity_mismatch")
    for cfg in (base, fine):
        validate_architecture(load_object(Path(cfg.artifact_root) / cfg.model_subdir / "gliner_config.json"), cfg)
    return {"schema_version": "TrainingParity/v1", "edition_id": plan["edition_id"],
        "base_configuration_sha256": config_digest(base), "finetuned_configuration_sha256": config_digest(fine),
        "selected_training_receipt_sha256": digest(receipt), "selected_checkpoint_sha256": receipt["checkpoint_sha256"],
        "checkpoint_export_sha256": digest(export), "tokenizer_sha256": base.tokenizer_sha256,
        "architecture_sha256": base.architecture_sha256, "base_weights_sha256": base.weights_sha256,
        "selection_rule_sha256": base.decoder.threshold_selection_sha256,
        "status": "source_artifact_parity_verified_runtime_unverified"}
