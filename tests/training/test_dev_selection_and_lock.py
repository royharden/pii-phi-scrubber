"""Dev-only selection input and the pre-test selection lock.

Plan: development chooses thresholds/checkpoint; held-out is read once after the
targets are locked with an explicit Integrator-approved record; a lock cannot be
rewritten after the fact. All lineage hashes below are hand-chosen constants
(`h("a")` = 64 x "a"); `digest` is only used to construct the inputs that bind
them, never to compute an expected assertion value.
"""
from datetime import datetime
import json

import pytest
from pydantic import ValidationError

from m7.contracts import Span, make_record
from m7.training.artifacts import load_training_data
from m7.training.locking import create_pre_test_lock, lock_binding, verify_pre_test_lock
from m7.training.selection import DevRecord, select_checkpoint
from m7.training.selection_models import (
    LABELS, ClassTarget, NumericalTargets, PreTestLockApproval, PreTestSelectionLock,
)
from m7.training.validation import digest


def h(c):
    return c * 64


def utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


# ---------------------------------------------------------------- dev-only selection

@pytest.mark.parametrize("split", ["test", "train", "heldout"])
def test_select_checkpoint_refuses_non_dev_records_before_anything_else(split):
    record = make_record("acct=A123 ok", "r1", split_id=split)
    rows = [DevRecord(record, (Span(start=5, end=9, label="ACCOUNT_ID"),), "blk-1", "normal")]
    # Population check is the first step, so no artifacts/receipts/verifier are consulted.
    with pytest.raises(ValueError, match="invalid_development_population"):
        select_checkpoint(rows, [], policy=None, training_plan=None, training_permit=None,
                          trial_receipts=[], checkpoint_exports=[], training_run=None,
                          training_root=None, verify_receipt=lambda kind, sha: True)


def test_select_checkpoint_refuses_empty_population():
    with pytest.raises(ValueError, match="empty_development_population"):
        select_checkpoint([], [], policy=None, training_plan=None, training_permit=None,
                          trial_receipts=[], checkpoint_exports=[], training_run=None,
                          training_root=None, verify_receipt=lambda kind, sha: True)


def _dataset(tmp_path, split, record_split):
    record = make_record("acct=A123 ok", "r1", split_id=record_split)
    path = tmp_path / f"{split}-{record_split}.json"
    path.write_text(json.dumps({"schema_version": "TrainingDataset/v1", "split": split,
                                "records": [{"record": record.model_dump(mode="json"),
                                             "gold": [{"start": 5, "end": 9, "label": "ACCOUNT_ID"}]}]}),
                    encoding="utf-8")
    return path


def test_training_loader_has_no_test_fallback(tmp_path):
    # A bundle declared "test" cannot be loaded as dev.
    with pytest.raises(ValueError, match="training_split_required"):
        load_training_data(_dataset(tmp_path, "test", "test"), "dev")
    # A test-split record smuggled inside a dev bundle is refused.
    with pytest.raises(ValueError, match="record_split_or_identity_mismatch"):
        load_training_data(_dataset(tmp_path, "dev", "test"), "dev")
    rows = load_training_data(_dataset(tmp_path, "dev", "dev"), "dev")
    assert len(rows) == 1 and rows[0]["spans"][0].end == 9


# ---------------------------------------------------------------- pre-test lock

REG, FIRST, CREATED, JUST, ISSUED = ("2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z",
                                     "2026-01-01T02:00:00Z", "2026-01-01T03:00:00Z",
                                     "2026-01-01T04:00:00Z")
APPROVAL_EXPIRES = "2026-01-02T00:00:00Z"
NOW = utc("2026-01-01T05:00:00Z")


def selection(**overrides):
    s = {"schema_version": "DevSelectionReceipt/v1", "edition_id": "ed-1",
         "heldout_accessed": False, "product_acceptance": False,
         "experiment_plan_sha256": h("1"), "training_plan_sha256": h("2"),
         "selection_rule_sha256": h("3"), "policy_sha256": h("4"),
         "training_run_closeout_sha256": h("5"),
         "registered_at": REG, "first_evaluated_at": FIRST, "created_at": CREATED,
         "selected_finetuned": {"eligible": True, "measurement_status": "measured",
                                "training_receipt_sha256": h("6"), "checkpoint_sha256": h("7"),
                                "checkpoint_export_sha256": h("8"), "configuration_sha256": h("9")},
         "selected_base": {"eligible": True, "measurement_status": "measured",
                           "configuration_sha256": h("a")}}
    s.update(overrides)
    return s


def parity(sel):
    return {"schema_version": "TrainingParity/v1", "edition_id": sel["edition_id"],
            "selected_training_receipt_sha256": h("6"), "selected_checkpoint_sha256": h("7"),
            "checkpoint_export_sha256": h("8"), "selection_rule_sha256": h("3"),
            "base_configuration_sha256": h("a"), "finetuned_configuration_sha256": h("9")}


def targets(name_recall=0.95):
    per = {label: ClassTarget() for label in LABELS}
    per["NAME"] = ClassTarget(recall=name_recall, recall_lower_95=min(0.90, name_recall))
    return NumericalTargets(per_class=per).model_dump(mode="json")


def justification(sel, *, created_at=JUST, tgt=None):
    tgt = targets() if tgt is None else tgt
    return {"schema_version": "TargetJustification/v1", "edition_id": sel["edition_id"],
            "heldout_accessed": False, "dev_selection_receipt_sha256": digest(sel),
            "targets": tgt, "targets_sha256": digest(tgt),
            "exact_invariants": {"structure_failures": 0, "intended_record_accounting": 1.0},
            "created_at": created_at, "rationale_receipt_sha256": h("b")}


def approval_for(sel, par, just, *, issued_at=ISSUED, expires_at=APPROVAL_EXPIRES):
    binding = lock_binding(sel, par, just, corpus_manifest_sha256=h("c"))
    return PreTestLockApproval(approval_id="appr-1", approved_by="int2", approved=True,
                               allowed_action="lock_targets_before_heldout",
                               binding_sha256=digest(binding), issued_at=issued_at, expires_at=expires_at)


class Verifier:
    def __init__(self, refuse=()):
        self.refuse, self.calls = set(refuse), []

    def __call__(self, kind, sha):
        self.calls.append(kind)
        return kind not in self.refuse


def materials():
    sel = selection()
    par = parity(sel)
    just = justification(sel)
    return sel, par, just, approval_for(sel, par, just)


def make_lock(verifier=None, clock=NOW):
    sel, par, just, appr = materials()
    lock = create_pre_test_lock(sel, par, just, corpus_manifest_sha256=h("c"), approval=appr,
                                verify_receipt=verifier or Verifier(), clock=lambda: clock)
    return lock, (sel, par, just, appr)


def test_lock_freezes_hand_supplied_lineage_and_window():
    verifier = Verifier()
    lock, _ = make_lock(verifier)
    assert lock.edition_id == "ed-1" and lock.corpus_manifest_sha256 == h("c")
    assert lock.selected_training_receipt_sha256 == h("6") and lock.selected_checkpoint_sha256 == h("7")
    assert lock.base_configuration_sha256 == h("a") and lock.finetuned_configuration_sha256 == h("9")
    assert lock.selection_rule_sha256 == h("3")
    assert lock.experiment_plan_sha256 == h("1") and lock.training_plan_sha256 == h("2")
    assert utc(lock.locked_at) == NOW and lock.expires_at == APPROVAL_EXPIRES
    # Custody must be asked that held-out is still unopened; no permissive default.
    assert "heldout_unopened" in verifier.calls and "pre_test_lock_approval" in verifier.calls


def test_lock_is_immutable():
    lock, _ = make_lock()
    with pytest.raises(ValidationError):
        lock.targets_sha256 = h("d")
    with pytest.raises(ValidationError):
        lock.selected_checkpoint_sha256 = h("e")


def test_lock_window_must_be_positive():
    lock, _ = make_lock()
    data = lock.model_dump(mode="json")
    data["expires_at"] = data["locked_at"]
    with pytest.raises(ValidationError):
        PreTestSelectionLock(**data)


def test_verify_accepts_unchanged_materials_and_rejects_rewritten_targets():
    lock, (sel, par, just, appr) = make_lock()
    later = utc("2026-01-01T06:00:00Z")
    verify_pre_test_lock(lock, selection=sel, parity=par, justification=just, approval=appr,
                         verify_receipt=Verifier(), clock=lambda: later)
    # Post-hoc target rewrite (NAME recall 0.95 -> 0.80), internally consistent hash, same approval.
    rewritten = justification(sel, tgt=targets(name_recall=0.80))
    with pytest.raises(ValueError, match="pre_test_lock_binding_or_expiry_mismatch"):
        verify_pre_test_lock(lock, selection=sel, parity=par, justification=rewritten, approval=appr,
                             verify_receipt=Verifier(), clock=lambda: later)


def test_verify_rejects_after_expiry():
    lock, (sel, par, just, appr) = make_lock()
    with pytest.raises(ValueError, match="pre_test_lock_binding_or_expiry_mismatch"):
        verify_pre_test_lock(lock, selection=sel, parity=par, justification=just, approval=appr,
                             verify_receipt=Verifier(), clock=lambda: utc(APPROVAL_EXPIRES))


@pytest.mark.parametrize("kind", ["heldout_unopened", "pre_test_lock_approval", "numerical_targets"])
def test_unauthenticated_material_or_opened_heldout_fails_closed(kind):
    with pytest.raises(ValueError, match="receipt_not_authenticated_or_revoked"):
        make_lock(Verifier(refuse={kind}))


def test_truthy_non_true_verifier_is_not_authentication():
    sel, par, just, appr = materials()
    with pytest.raises(ValueError, match="receipt_not_authenticated_or_revoked"):
        create_pre_test_lock(sel, par, just, corpus_manifest_sha256=h("c"), approval=appr,
                             verify_receipt=lambda kind, sha: 1, clock=lambda: NOW)


def test_heldout_already_accessed_cannot_be_locked():
    sel = selection(heldout_accessed=True)
    par = parity(sel)
    just = justification(sel)
    with pytest.raises(ValueError, match="pre_test_lock_material_binding_mismatch"):
        lock_binding(sel, par, just, corpus_manifest_sha256=h("c"))


def test_parity_must_bind_selected_checkpoint():
    sel = selection()
    par = parity(sel)
    par["selected_checkpoint_sha256"] = h("f")  # some other checkpoint
    with pytest.raises(ValueError, match="pre_test_lock_material_binding_mismatch"):
        lock_binding(sel, par, justification(sel), corpus_manifest_sha256=h("c"))


def test_approval_before_justification_is_chronology_failure():
    sel = selection()
    par = parity(sel)
    just = justification(sel)
    early = approval_for(sel, par, just, issued_at="2026-01-01T02:30:00Z")  # before JUST 03:00
    with pytest.raises(ValueError, match="pre_test_lock_approval_or_chronology_mismatch"):
        create_pre_test_lock(sel, par, just, corpus_manifest_sha256=h("c"), approval=early,
                             verify_receipt=Verifier(), clock=lambda: NOW)


def test_lock_after_approval_expiry_refused():
    with pytest.raises(ValueError, match="pre_test_lock_approval_or_chronology_mismatch"):
        make_lock(clock=utc(APPROVAL_EXPIRES))


def test_class_target_lower_bound_cannot_exceed_point_target():
    with pytest.raises(ValidationError):
        ClassTarget(recall=0.90, recall_lower_95=0.95)
    with pytest.raises(ValidationError):
        NumericalTargets(per_class={"NAME": ClassTarget()})  # missing three classes


def test_verify_rechecks_selection_chronology():
    # A lock assembled outside create_pre_test_lock over a selection whose first evaluation
    # (02:30) is AFTER its created_at (02:00). Binding/approval hashes are self-consistent,
    # so only the registered <= first_evaluated <= created re-check can refuse it.
    sel = selection(first_evaluated_at="2026-01-01T02:30:00Z")
    par = parity(sel)
    just = justification(sel)
    appr = approval_for(sel, par, just)
    binding = lock_binding(sel, par, just, corpus_manifest_sha256=h("c"))
    lock = PreTestSelectionLock(**binding, approval_sha256=digest(appr.model_dump(mode="json")),
                                locked_at="2026-01-01T05:00:00+00:00", expires_at=APPROVAL_EXPIRES)
    with pytest.raises(ValueError, match="pre_test_lock_binding_or_expiry_mismatch"):
        verify_pre_test_lock(lock, selection=sel, parity=par, justification=just, approval=appr,
                             verify_receipt=Verifier(), clock=lambda: utc("2026-01-01T06:00:00Z"))
