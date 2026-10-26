"""Pure scientific prerequisite assessment, never an execution/acceptance gate.

Only in-memory, value-free projections leave this module. No filesystem, receipt
authentication, custody lifecycle, model, host factory or worker is invoked.
"""
from __future__ import annotations

from typing import Annotated, Literal, TYPE_CHECKING

from pydantic import Field, field_validator, model_validator

from m7.contracts import Arm, Boundary, Digest
from .models import ARMS, LockedEdition, commitment
from .authorization import EvaluationAuthorization, ReceiptAuthority
from .costing import cost_report

if TYPE_CHECKING:
    from m7.training.launch_bundle import WorkerLaunchBundle

Component = Literal['artifacts', 'training', 'providers']
State = Literal['missing', 'held', 'mock', 'shape_valid', 'invalid', 'unknown']
CheckName = Literal['artifacts', 'training', 'providers', 'training_plan', 'preregistration',
                    'campaign_binding', 'intended_population', 'costs',
                    'H1', 'H2', 'H3', 'H4', 'H5', 'H6']
Reason = Literal['input_missing', 'input_invalid', 'shape_only_not_authenticated',
                 'mock_not_execution', 'held_by_roy', 'unknown_or_unreconciled']
CHECKS = ('artifacts', 'training', 'providers', 'training_plan', 'preregistration',
          'campaign_binding', 'intended_population', 'costs', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6')
HOLDS = ('H1', 'H2', 'H3', 'H4', 'H5', 'H6')
REASONS = {'missing': 'input_missing', 'invalid': 'input_invalid',
           'shape_valid': 'shape_only_not_authenticated', 'mock': 'mock_not_execution',
           'held': 'held_by_roy', 'unknown': 'unknown_or_unreconciled'}


class ComponentFact(Boundary):
    """Producer-attributed observation, not a permit or independently proven fact.

    D9 supplies providers; D10 supplies artifacts/training. The digest commits the
    producer's value-free report, never source values or entity-value hashes.
    """
    component: Component
    state: Literal['missing', 'held', 'mock', 'shape_valid', 'invalid', 'unknown']
    evidence_sha256: Digest | None = None

    @model_validator(mode='after')
    def evidence_for_observation(self):
        if self.state in ('mock', 'shape_valid') and self.evidence_sha256 is None:
            raise ValueError('observation_commitment_required')
        return self


class ReadinessCheck(Boundary):
    name: CheckName
    state: State
    reason: Reason
    evidence_sha256: Digest | None = None

    @model_validator(mode='after')
    def consistent_reason(self):
        if self.reason != REASONS[self.state]:
            raise ValueError('readiness_reason_mismatch')
        return self


Count = Annotated[int, Field(ge=0)]


class ArmAccounting(Boundary):
    arm: Arm
    corpus_N: Count
    attempted_N: Count
    answered_N: Count
    error_N: Count
    unattempted_N: Count

    @model_validator(mode='after')
    def fixed_population(self):
        if (self.attempted_N + self.unattempted_N != self.corpus_N
                or self.answered_N + self.error_N != self.attempted_N):
            raise ValueError('readiness_population_mismatch')
        return self


class ReadinessCost(Boundary):
    status: Literal['unknown', 'known', 'partially_known', 'not_measured'] = 'unknown'
    provider_cash_total_micros: Count | None = None
    unresolved_liability_micros: Count | None = None
    economic_total_micros: Count | None = None
    scope_complete: bool = False


class ExperimentReadiness(Boundary):
    """Current offline preparation can never certify actual scientific readiness."""
    schema_version: Literal['ExperimentReadiness/v1'] = 'ExperimentReadiness/v1'
    status: Literal['NOT_READY'] = 'NOT_READY'
    evidence_kind: Literal['readiness', 'mock'] = 'readiness'
    actual_model_execution: Literal[False] = False
    execution_allowed: Literal[False] = False
    product_acceptance: Literal[False] = False
    held_decisions: tuple[Literal['H1', 'H2', 'H3', 'H4', 'H5', 'H6'], ...] = HOLDS
    checks: tuple[ReadinessCheck, ...]
    blockers: tuple[CheckName, ...]
    accounting: tuple[ArmAccounting, ...] = ()
    cost: ReadinessCost = ReadinessCost()

    @field_validator('actual_model_execution', 'execution_allowed', 'product_acceptance', mode='before')
    @classmethod
    def no_execution_claims(cls, value):
        # Field-level validation preserves strict JSON array-to-tuple semantics.
        # A model-before hook would switch the whole JSON object to Python mode.
        if value is not False:
            raise ValueError('readiness_cannot_claim_execution_or_acceptance')
        return value

    @model_validator(mode='after')
    def coherent(self):
        if (self.held_decisions != HOLDS or tuple(row.name for row in self.checks) != CHECKS
                or self.blockers != tuple(row.name for row in self.checks if row.state != 'shape_valid')
                or any(row.state != 'held' for row in self.checks if row.name in HOLDS)):
            raise ValueError('readiness_checks_or_holds_mismatch')
        if self.accounting and (tuple(row.arm for row in self.accounting) != ARMS
                or len({row.corpus_N for row in self.accounting}) != 1):
            raise ValueError('readiness_four_arm_population_required')
        return self


def _check(name, state, digest=None):
    return ReadinessCheck(name=name, state=state, reason=REASONS[state], evidence_sha256=digest)


def assess_readiness(*, component_facts: tuple[ComponentFact, ...] = (),
                     provider_facts=None, training_facts=None,
                     training_plan: dict | None = None, training_permit: dict | None = None,
                     edition: LockedEdition | None = None,
                     authorization: EvaluationAuthorization | None = None,
                     launch_bundle: WorkerLaunchBundle | None = None,
                     result_bundle: dict | None = None, cost_summary: dict | None = None,
                     evidence_kind: Literal['readiness', 'mock'] = 'readiness') -> ExperimentReadiness:
    """Compose existing *pure* validators; exceptions become fixed enums only.

    Inputs must be public fictional development/mock metadata, never sealed files.
    Producer observations are explicitly attributed, not authenticated by this API.
    Even complete structural inputs retain H1-H6 and cannot cause execution.
    """
    # All fields are scalar: revalidate detached fields without serializing rejected values.
    facts = tuple(ComponentFact.model_validate(row.__dict__.copy() if type(row) is ComponentFact else None)
                  for row in component_facts)
    facts += _producer_facts(provider_facts, training_facts)
    if len({row.component for row in facts}) != len(facts):
        raise ValueError('duplicate_readiness_component')
    by_component = {row.component: row for row in facts}
    checks = []
    for name in ('artifacts', 'training', 'providers'):
        fact = by_component.get(name)
        checks.append(_check(name, fact.state if fact else 'missing', fact.evidence_sha256 if fact else None))
    if training_plan is None and training_permit is None:
        checks.append(_check('training_plan', 'missing'))
    else:
        try:
            from m7.training.validation import validate_training_plan
            validate_training_plan(training_plan, training_permit)
            checks.append(_check('training_plan', 'shape_valid'))
        except Exception:
            checks.append(_check('training_plan', 'invalid'))
    lock = None
    if edition is None:
        checks.append(_check('preregistration', 'missing'))
    else:
        try:
            lock = LockedEdition.model_validate_json(edition.model_dump_json(warnings='error'))
            lock.require_current()
            checks.append(_check('preregistration', 'shape_valid', lock.sha256))
        except Exception:
            lock = None
            checks.append(_check('preregistration', 'invalid'))
    if lock is None or authorization is None or launch_bundle is None:
        checks.append(_check('campaign_binding', 'missing'))
    else:
        try:
            from .campaign import validate_campaign_inputs
            packet = EvaluationAuthorization.model_validate_json(authorization.model_dump_json(warnings='error'))
            ReceiptAuthority.validate_binding(packet, lock)
            validate_campaign_inputs(launch_bundle, lock, packet)
            checks.append(_check('campaign_binding', 'shape_valid'))
        except Exception:
            checks.append(_check('campaign_binding', 'invalid'))
    accounting = ()
    if result_bundle is None:
        checks.append(_check('intended_population', 'missing'))
    else:
        try:
            from .result import public_aggregate
            result = public_aggregate(result_bundle)
            if edition is not None and lock is None:
                raise ValueError('readiness_result_lock_invalid')
            if lock is not None and (result['edition_sha256'] != lock.sha256
                    or result['corpus_N'] != len(lock.population)
                    or result['corpus_digest'] != commitment(
                        [row.model_dump(mode='json') for row in lock.population])):
                raise ValueError('readiness_result_lock_mismatch')
            accounting = tuple(ArmAccounting(**{key: row[key] for key in ArmAccounting.model_fields})
                               for row in result['arms'])
            checks.append(_check('intended_population', 'shape_valid'))
        except Exception:
            accounting = ()
            checks.append(_check('intended_population', 'invalid'))
    cost = ReadinessCost()
    try:
        projection = cost_report(cost_summary)
        cost = ReadinessCost(**{key: projection[key] for key in ReadinessCost.model_fields})
        state = ('shape_valid' if cost.status == 'known' and cost.scope_complete
                 and cost.economic_total_micros is not None else 'unknown')
        checks.append(_check('costs', state))
    except Exception:
        checks.append(_check('costs', 'invalid'))
    checks.extend(_check(hold, 'held') for hold in HOLDS)
    return ExperimentReadiness(evidence_kind=evidence_kind, checks=tuple(checks),
        blockers=tuple(row.name for row in checks if row.state != 'shape_valid'), accounting=accounting, cost=cost)


def _producer_facts(provider, training) -> tuple[ComponentFact, ...]:
    """Consume producer-owned schemas; never inspect artifacts or start backends.

    Imports occur only for an explicitly supplied report, so missing producers are
    ordinary missing evidence while their independent implementation is pending.
    """
    facts = []
    if provider is not None:
        try:
            from m7.providers.readiness import ProviderFacts
            if not isinstance(provider, ProviderFacts):
                raise ValueError('canonical_provider_facts_required')
            # Reject forged nested shapes before serializer diagnostics can echo them.
            report = ProviderFacts.model_validate_json(provider.model_dump_json(warnings='error'))
            if report.actual_model_execution is not False or report.execution_allowed is not False:
                raise ValueError('producer_cannot_grant_execution')
            states = tuple(row.status for row in report.arms)
            state = ('invalid' if 'invalid' in states else 'missing' if 'missing' in states
                     else 'shape_valid' if states == ('shape_valid',) * 3 else 'invalid')
            facts.append(ComponentFact(component='providers', state=state,
                evidence_sha256=commitment(report.model_dump(mode='json'))))
        except Exception:
            facts.append(ComponentFact(component='providers', state='invalid'))
    if training is not None:
        try:
            from m7.training.readiness import TrainingArtifactFacts
            if not isinstance(training, TrainingArtifactFacts):
                raise ValueError('canonical_training_facts_required')
            report = TrainingArtifactFacts.model_validate_json(training.model_dump_json(warnings='error'))
            if (report.actual_training_observed is not False or report.execution_allowed_now is not False
                    or report.m7_02_accepted is not False):
                raise ValueError('producer_cannot_grant_training_acceptance')
            digest = commitment(report.model_dump(mode='json'))
            artifacts = {'not_inspected': 'held', 'missing': 'missing',
                         'invalid': 'invalid', 'verified': 'shape_valid'}[report.artifact_status]
            plan = {'missing_plan': 'missing', 'missing_permit': 'missing',
                    'invalid': 'invalid', 'validated': 'shape_valid'}[report.input_status]
            facts.extend((ComponentFact(component='artifacts', state=artifacts, evidence_sha256=digest),
                          ComponentFact(component='training', state=plan, evidence_sha256=digest)))
        except Exception:
            facts.extend(ComponentFact(component=name, state='invalid') for name in ('artifacts', 'training'))
    return tuple(facts)


__all__ = ['ComponentFact', 'ReadinessCheck', 'ArmAccounting', 'ReadinessCost',
           'ExperimentReadiness', 'assess_readiness']
