"""Lazy public exports; pure timing contracts never load worker/native consumers."""
from importlib import import_module

_EXPORTS = {'ARMS': 'models',
 'ExperimentReadiness': 'readiness',
 'ComponentFact': 'readiness',
 'assess_readiness': 'readiness',
 'AdapterBinding': 'executor',
 'AdoptionPolicy': 'adoption',
 'ArmPin': 'models',
 'CellResult': 'journal',
 'ClassFloor': 'adoption',
 'CustodyGold': 'models',
 'EconomicAllocation': 'costing',
 'EditionJournal': 'journal',
 'EvaluationAuthorization': 'authorization',
 'HardwareContext': 'timing',
 'IsolatedCampaignHost': 'isolated',
 'IsolatedRegistry': 'isolated',
 'IsolatedTimingPlan': 'timing_contracts',
 'JournalError': 'journal',
 'LengthSlice': 'timing',
 'LockedEdition': 'models',
 'OperatorHost': 'activation',
 'PopulationMember': 'models',
 'PrimaryAccountingReceipt': 'timing_contracts',
 'ReceiptAuthority': 'authorization',
 'TimingContinuationAuthority': 'timing_contracts',
 'TimingLengthSlice': 'timing_contracts',
 'TimingPhasePermit': 'timing_contracts',
 'TimingPhaseRequest': 'timing_contracts',
 'TimingPlan': 'timing',
 'TimingWorker': 'timing',
 'WarmBackendIdentity': 'timing_contracts',
 'WarmTimingSession': 'timing_contracts',
 'WorkerDefinition': 'isolated',
 'adoption_report': 'adoption',
 'aggregate_edition': 'executor',
 'channels_from_bundle': 'custody',
 'combined_cost_summary': 'costing',
 'cost_report': 'costing',
 'execute_edition': 'executor',
 'execute_isolated_campaign': 'campaign',
 'policy_from_selection_lock': 'activation',
 'primary_accounting': 'isolated_timing',
 'public_aggregate': 'result',
 'read_released_channels': 'released',
 'retained_timing_identities': 'isolated_timing',
 'run_isolated_timing': 'isolated_timing',
 'run_timing': 'timing',
 'timing_worker_factory': 'activation',
 'validate_campaign_inputs': 'campaign',
 'validate_timing_plan': 'isolated_timing',
 'write_aggregate_result': 'result'}
__all__ = list(_EXPORTS)

def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module("." + module, __name__), name)
    globals()[name] = value
    return value
