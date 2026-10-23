"""Trusted future operator integration; no provided host or automatic credentials."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Mapping

from .adoption import AdoptionPolicy, ClassFloor
from .executor import AdapterBinding
from .models import LockedEdition, commitment, utc_time
from .timing import TimingWorker
from .costing import EconomicAllocation

if TYPE_CHECKING:
    from m7.data.access import IsolationGuard
    from m7.data.filesystem import CustodyFilesystem


@dataclass(frozen=True)
class OperatorHost:
    """Externally reviewed/provisioned code, not an arbitrary untrusted plugin.

    Construction must be inert. Registry factory runs only after current D4/D5
    authority checks; it supplies D6 bindings and actual external receipt verifier.
    It never receives corpus paths, held-out gold or provenance from this API.
    """
    verify_receipt: Callable[[str, str], bool]
    registry_factory: Callable[[], Mapping[str, AdapterBinding]]
    cost_summary: Callable[[], dict]
    custody_filesystem: CustodyFilesystem
    isolation_guard: IsolationGuard
    timing_factories: Callable[[], Mapping[str, Callable[[], TimingWorker]]] | None = None
    cancelled: Callable[[], bool] = lambda: False
    economic_allocation: EconomicAllocation | None = None


def policy_from_selection_lock(edition: LockedEdition, lock, targets, *,
                                verify_receipt: Callable[[str, str], bool]) -> AdoptionPolicy:
    """Consume D5's exact final schema, never duplicate its selection algorithm."""
    from m7.training.selection_models import NumericalTargets, PreTestSelectionLock
    if not isinstance(lock, PreTestSelectionLock) or not isinstance(targets, NumericalTargets):
        raise ValueError('d5_lock_and_targets_required')
    now = datetime.now(timezone.utc)
    if (lock.sha256 != edition.selection_lock_sha256 or lock.edition_id != edition.edition_id
            or lock.experiment_plan_sha256 != edition.plan_sha256
            or lock.corpus_manifest_sha256 != edition.corpus_manifest_sha256
            or commitment(targets.model_dump(mode='json')) != lock.targets_sha256
            or not utc_time(lock.locked_at) <= now < utc_time(lock.expires_at)
            or utc_time(edition.expires_at) > utc_time(lock.expires_at)):
        raise ValueError('d5_pre_test_lock_binding_mismatch')
    pins = {pin.arm: pin for pin in edition.arm_pins}
    if (pins['base'].configuration_sha256 != lock.base_configuration_sha256
            or pins['finetuned'].configuration_sha256 != lock.finetuned_configuration_sha256):
        raise ValueError('selected_base_fine_configuration_mismatch')
    for kind, digest in (
        ('pre_test_selection_lock', lock.sha256), ('numerical_targets', lock.targets_sha256),
        ('target_justification', lock.target_justification_sha256),
        ('training_receipt', lock.selected_training_receipt_sha256),
        ('parity_receipt', lock.parity_receipt_sha256),
        ('pre_test_lock_approval', lock.approval_sha256),
    ):
        if verify_receipt(kind, digest) is not True:
            raise ValueError('d5_selection_receipt_not_authenticated')
    policy = AdoptionPolicy(per_class=tuple(ClassFloor(label=label,
        recall_minimum=targets.per_class[label].recall,
        precision_minimum=targets.per_class[label].precision,
        recall_lower95_minimum=targets.per_class[label].recall_lower_95)
        for label in ('NAME', 'EMAIL', 'PHONE', 'ACCOUNT_ID')),
        development_justification_sha256=lock.target_justification_sha256)
    if policy != edition.adoption_policy:
        raise ValueError('edition_policy_differs_from_approved_pre_test_targets')
    return policy


def timing_worker_factory(source, pin, *, run_id: str) -> Callable[[], TimingWorker]:
    """Bind a FRESH D6 adapter to a cold load and fresh per-pass controllers.

    Caller must create a new registry for timing, not reuse the evaluated model's
    loaded backend. Does not start or load anything until the returned factory runs.
    """
    def factory() -> TimingWorker:
        from m7.detectors.attempts import AttemptController
        from m7.detectors.registry import DetectorAdapter, RegexAdapter, bind_registry
        from m7.providers.frontier import PermittedFrontier
        if not isinstance(source, (DetectorAdapter, RegexAdapter)):
            raise ValueError('d6_timing_adapter_required')
        initial = bind_registry({pin.arm: source}, (pin,), run_id=run_id)[pin.arm]
        if isinstance(source, RegexAdapter):
            return TimingWorker(initial, lambda: None, lambda _: initial)
        original = source.controller
        if original is None:
            raise ValueError('timing_attempt_controller_required')
        def startup():
            if isinstance(source.backend, PermittedFrontier):
                source.backend.check()  # Client init, never provider-model startup.
            else:
                source.backend.preflight(())  # Local import/load; no inference.
        def for_pass(index: int) -> AdapterBinding:
            if type(index) is not int or not 0 <= index < 3:
                raise ValueError('exactly_three_timing_passes')
            controller = AttemptController(run_id=run_id, arm=source.arm, model_id=source.model_id,
                policy=original.policy, ledger=original.ledger, cancelled=original.cancelled,
                receipt_resolver=original.receipt_resolver, diagnostic_sink=original.diagnostic_sink)
            adapter = DetectorAdapter(run_id, source.arm, source.model_id, source.backend, controller)
            return bind_registry({pin.arm: adapter}, (pin,), run_id=run_id)[pin.arm]
        return TimingWorker(initial, startup, for_pass)
    return factory


__all__ = ['OperatorHost', 'policy_from_selection_lock', 'timing_worker_factory']
