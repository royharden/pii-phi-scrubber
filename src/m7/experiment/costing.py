"""Provider cash, conservative liabilities and economic allocation stay distinct."""
from __future__ import annotations

from typing import Annotated, Literal
import math
import re

from pydantic import Field

from m7.contracts import Boundary, Digest

CATEGORIES = ('training', 'inference', 'retry', 'failed_trial')
STATES = ('reserved', 'succeeded', 'failed', 'cancelled', 'unknown')
COUNT_KEYS = ('attempts_N', 'known_provider_cash_micros', 'unresolved_liability_micros',
              'unknown_attempts', 'known_usage_units', 'unknown_usage_attempts')
AMOUNT_SOURCES = ('estimated', 'actual')


class EconomicAllocation(Boundary):
    """All amounts share the authorization currency; receipt is host-authenticated."""
    schema_version: Literal['EconomicAllocation/v1'] = 'EconomicAllocation/v1'
    receipt_sha256: Digest
    currency: Annotated[str, Field(pattern=r'^[A-Z]{3}$')]
    electricity_micros: Annotated[int, Field(ge=0)] | None = None
    hardware_amortization_micros: Annotated[int, Field(ge=0)] | None = None
    compute_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError('invalid_cost_counter')
    return value


def _seconds(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('invalid_compute_seconds')
    return float(value)


def _has_compute(categories: dict) -> bool:
    keys = ('known_compute_seconds', 'unknown_compute_attempts')
    supplied = [key in categories.get(category, {}) for category in CATEGORIES for key in keys]
    if any(supplied) and not all(supplied):
        raise ValueError('complete_compute_summary_required')
    return all(supplied)


def cost_report(summary: dict | None, allocation: EconomicAllocation | None = None) -> dict:
    empty = {'status': 'unknown', 'attempts_N': None, 'known_provider_cash_micros': None,
             'provider_cash_total_micros': None, 'unresolved_liability_micros': None,
             'unknown_attempts': None, 'cap_micros': None, 'remaining_micros': None,
             'over_cap': None, 'by_category': None, 'states': None,
             'electricity_micros': None, 'hardware_amortization_micros': None,
             'compute_seconds': None, 'economic_total_micros': None,
             'scope_complete': False,
             'currency': None,
             'amount_sources': None, 'known_compute_seconds': None, 'unknown_compute_attempts': None,
             'economic_null_reason': 'unmeasured_or_unreconciled'}
    if summary is None:
        return empty
    keys = ('cap_micros', 'known_provider_cash_micros', 'unresolved_liability_micros',
            'unknown_attempts', 'remaining_micros', 'attempts_N')
    output = {**empty, **{key: _count(summary.get(key)) for key in keys}}
    categories = summary.get('by_category')
    states = summary.get('states')
    if not isinstance(categories, dict) or not isinstance(states, dict):
        raise ValueError('complete_cost_summary_required')
    output['by_category'] = {category: {key: _count(categories.get(category, {}).get(key))
                                       for key in COUNT_KEYS} for category in CATEGORIES}
    output['states'] = {state: _count(states.get(state)) for state in STATES}
    if sum(output['states'].values()) != output['attempts_N']:
        raise ValueError('cost_state_denominator_mismatch')
    for key in ('attempts_N', 'known_provider_cash_micros', 'unresolved_liability_micros', 'unknown_attempts'):
        if sum(row[key] for row in output['by_category'].values()) != output[key]:
            raise ValueError('cost_category_reconciliation_mismatch')
    sources = summary.get('amount_sources')
    if sources is not None:
        # Counts of attempts whose amount is a receipt ('actual') or the reservation ('estimated').
        if not isinstance(sources, dict):
            raise ValueError('invalid_amount_sources')
        output['amount_sources'] = {source: _count(sources.get(source)) for source in AMOUNT_SOURCES}
        if sum(output['amount_sources'].values()) != output['attempts_N']:
            raise ValueError('amount_source_denominator_mismatch')
    if _has_compute(categories):
        # Compute time is a resource proxy only; no cost figure is ever derived from it.
        for category in CATEGORIES:
            row = output['by_category'][category]
            row['known_compute_seconds'] = _seconds(categories[category].get('known_compute_seconds'))
            row['unknown_compute_attempts'] = _count(categories[category].get('unknown_compute_attempts'))
            if row['unknown_compute_attempts'] > row['attempts_N']:
                raise ValueError('compute_attempt_count_mismatch')
        output['known_compute_seconds'] = sum(r['known_compute_seconds'] for r in output['by_category'].values())
        output['unknown_compute_attempts'] = sum(r['unknown_compute_attempts'] for r in output['by_category'].values())
    cash, liability = output['known_provider_cash_micros'], output['unresolved_liability_micros']
    if output['remaining_micros'] != max(0, output['cap_micros'] - cash - liability):
        raise ValueError('cost_remaining_mismatch')
    output['over_cap'] = cash + liability > output['cap_micros'] or summary.get('any_authorization_over_cap') is True
    output['scope_complete'] = summary.get('scope_complete') is True
    currency = summary.get('currency')
    output['currency'] = currency if isinstance(currency, str) and re.fullmatch('[A-Z]{3}', currency) else None
    output['status'] = ('not_measured' if output['attempts_N'] == 0 else
                        'partially_known' if output['unknown_attempts'] else 'known')
    if output['status'] == 'known':
        output['provider_cash_total_micros'] = cash
    if allocation is not None:
        if allocation.currency != output['currency']:
            raise ValueError('economic_allocation_currency_mismatch')
        output.update(electricity_micros=allocation.electricity_micros,
                      hardware_amortization_micros=allocation.hardware_amortization_micros,
                      compute_seconds=allocation.compute_seconds)
        if (output['status'] == 'known' and allocation.electricity_micros is not None
                and allocation.hardware_amortization_micros is not None):
            output['economic_total_micros'] = cash + allocation.electricity_micros + allocation.hardware_amortization_micros
            output['economic_null_reason'] = None
    return output


def combined_cost_summary(summaries: dict[str, dict], *, currency: str,
                          required_scopes: tuple[str, ...] = ('training', 'inference')) -> dict:
    """Combine distinct ledgers; trusted host verifies common invoice currency.

    Training, failed trials and inference must all be represented. Timing uses the
    inference ledger or a separately required timing ledger, never a duplicate alias.
    Aggregate remaining cap is informational; no cross-ledger spending is allowed.
    """
    if (not isinstance(currency, str) or re.fullmatch('[A-Z]{3}', currency) is None
            or not {'training', 'inference'} <= set(required_scopes)
            or len(set(required_scopes)) != len(required_scopes)
            or set(required_scopes) - {'training', 'inference', 'timing'}
            or set(summaries) != set(required_scopes)):
        raise ValueError('complete_cost_scopes_required')
    combined = merge_cost_authorizations(tuple(summaries.values()), currency=currency)
    combined['scope_complete'] = True
    return combined


def merge_cost_authorizations(summaries: tuple[dict, ...], *, currency: str) -> dict:
    """Shared arithmetic for distinct authorization ledgers, not a spend permit."""
    if not summaries or not isinstance(currency, str) or re.fullmatch('[A-Z]{3}', currency) is None:
        raise ValueError('cost_authorizations_and_currency_required')
    ids = [s.get('authorization_id') for s in summaries]
    if any(not isinstance(identity, str) or not identity for identity in ids) or len(set(ids)) != len(ids):
        raise ValueError('duplicate_or_missing_cost_authorization')
    reports = [cost_report(summary) for summary in summaries]
    keys = ('cap_micros', 'known_provider_cash_micros', 'unresolved_liability_micros', 'unknown_attempts', 'attempts_N')
    combined = {key: sum(row[key] for row in reports) for key in keys}
    combined['remaining_micros'] = max(0, combined['cap_micros'] - combined['known_provider_cash_micros']
                                        - combined['unresolved_liability_micros'])
    combined['by_category'] = {category: {key: sum(row['by_category'][category][key] for row in reports)
                                        for key in COUNT_KEYS} for category in CATEGORIES}
    combined['states'] = {state: sum(row['states'][state] for row in reports) for state in STATES}
    # Carry optional source/compute counts only when every authorization reports them.
    if all(row['amount_sources'] is not None for row in reports):
        combined['amount_sources'] = {source: sum(row['amount_sources'][source] for row in reports)
                                      for source in AMOUNT_SOURCES}
    if all(row['known_compute_seconds'] is not None for row in reports):
        for category in CATEGORIES:
            combined['by_category'][category]['known_compute_seconds'] = sum(
                row['by_category'][category]['known_compute_seconds'] for row in reports)
            combined['by_category'][category]['unknown_compute_attempts'] = sum(
                row['by_category'][category]['unknown_compute_attempts'] for row in reports)
    combined['scope_complete'] = False
    combined['currency'] = currency
    combined['any_authorization_over_cap'] = any(row['over_cap'] for row in reports)
    return combined


__all__ = ['EconomicAllocation', 'cost_report', 'combined_cost_summary', 'merge_cost_authorizations']
