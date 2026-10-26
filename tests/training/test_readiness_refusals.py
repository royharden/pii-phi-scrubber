"""W2 evidence_kind=mock: coherent fake packets do not grant training authority.

Uses only public temporary fixture bytes and an injected engine. No actual
training, optional package import, model acquisition or sealed data access.
"""
import hashlib
import json

import pytest

from m7.training.executor import execute_training
from m7.training.validation import digest

from .test_executor_failures import AT, Engine, accept_env, oom, stage


def amend_mock_packet(root, plan, permit, key, change):
    # Keep structural hashes coherent so refusal tests the semantic gate, not an
    # accidentally stale pin. These are dummy fixture approvals, not real rights.
    path = root / plan["artifacts"][key]["path"]
    packet = json.loads(path.read_text(encoding="utf-8"))
    packet.update(change)
    path.write_text(json.dumps(packet), encoding="utf-8")
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    plan["artifacts"][key]["sha256"] = pin
    if key in ("license_packet", "custody_audit"):
        permit[key + "_sha256"] = pin
    permit["plan_sha256"] = digest(plan)


@pytest.mark.parametrize("key,change,reason", [
    ("license_packet", {"approved": False}, "license_scope_mismatch"),
    ("license_packet", {"training_allowed": False}, "license_scope_mismatch"),
    ("license_packet", {"derivatives_allowed": False}, "license_scope_mismatch"),
    ("custody_audit", {"auditor_id": "custodian-a"}, "custody_scope_mismatch"),
    ("custody_audit", {"allowed_splits": ["train", "dev", "test"]}, "custody_scope_mismatch"),
    ("custody_audit", {"test_access_allowed": True}, "custody_scope_mismatch"),
    ("config", {"labels": ["EMAIL", "NAME", "PHONE", "ACCOUNT_ID"]}, "unsupported_training_config"),
    ("config", {"label_descriptions_sha256": "0" * 64}, "training_label_description_pin_mismatch"),
])
def test_semantically_unapproved_mock_packet_has_no_execution_effects(tmp_path, key, change, reason):
    # Bug caught: matching byte hashes alone must never turn denied rights,
    # same-author custody, forbidden split access or label drift into training.
    plan, permit = stage(tmp_path, 1)
    amend_mock_packet(tmp_path, plan, permit, key, change)
    engine = Engine(oom)
    environment_calls = []

    def environment(metadata):
        environment_calls.append(metadata)
        accept_env(metadata)

    with pytest.raises(ValueError, match=reason):
        execute_training(plan, permit, root=tmp_path, engine=engine,
                         clock=lambda: AT, environment_check=environment)
    assert engine.calls == 0
    assert not (tmp_path / "runs").exists() and not (tmp_path / "accounting").exists()
    if key != "config":
        assert environment_calls == []


def test_absent_local_artifact_allocates_no_run_or_accounting(tmp_path):
    plan, permit = stage(tmp_path, 1)
    plan["artifacts"]["model"]["path"] = "staged/not-acquired-model"
    permit["plan_sha256"] = digest(plan)
    engine = Engine(oom)
    before = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")}
    with pytest.raises(OSError):
        execute_training(plan, permit, root=tmp_path, engine=engine,
                         clock=lambda: AT, environment_check=accept_env)
    assert engine.calls == 0
    assert {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")} == before
