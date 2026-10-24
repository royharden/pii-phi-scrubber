"""Hand-built fictional two-record, four-arm edition for this test package.

Kept local to the package (tests/report has its own copy) so each test package
stays self-contained. Every expected number in the tests is derived by hand from
these literals, never by calling the scorer.

Offsets are Python code points, start inclusive, end exclusive (DEC-021):
  rec-001 "user Mirela Quandt signed in"
          'user ' is 5 code points, 'Mirela Quandt' is 6+1+6 = 13 -> NAME [5, 18)
  rec-002 "contact mirela.q@example.test now"
          'contact ' is 8, 'mirela.q@example.test' is 6+1+1+1+7+1+4 = 21 -> EMAIL [8, 29)
Gold code points in the population: 13 + 21 = 34. No PHONE or ACCOUNT_ID gold.
Blocks: rec-001 in block-a (normal), rec-002 in block-b (challenge): 2 blocks < 20.
"""
from m7.contracts import Prediction, Span, make_record
from m7.experiment.adoption import AdoptionPolicy, ClassFloor
from m7.experiment.executor import aggregate_edition
from m7.experiment.journal import CellResult
from m7.experiment.models import ArmPin, CustodyGold, LockedEdition, PopulationMember

ARMS = ('regex', 'frontier', 'base', 'finetuned')
LABELS = ('NAME', 'EMAIL', 'PHONE', 'ACCOUNT_ID')
RUN_ID = 'run-1'
NAME_VALUE = 'Mirela Quandt'
EMAIL_VALUE = 'mirela.q@example.test'
MESSAGES = {'rec-001': 'user Mirela Quandt signed in',
            'rec-002': 'contact mirela.q@example.test now'}
NAME_SPAN = Span(start=5, end=18, label='NAME')
EMAIL_SPAN = Span(start=8, end=29, label='EMAIL')
GOLD = {'rec-001': (NAME_SPAN,), 'rec-002': (EMAIL_SPAN,)}
PROVENANCE = {'rec-001': ('block-a', 'normal'), 'rec-002': ('block-b', 'challenge')}


def digest(character: str) -> str:
    return character * 64


def records():
    return tuple(make_record(MESSAGES[key], key, split_id='inference') for key in sorted(MESSAGES))


def record(record_id: str):
    return next(row for row in records() if row.record_id == record_id)


def policy() -> AdoptionPolicy:
    return AdoptionPolicy(per_class=tuple(ClassFloor(label=label, recall_minimum=0.5, precision_minimum=0.5,
                                                     recall_lower95_minimum=0.4) for label in LABELS),
                          development_justification_sha256=digest('a'))


def edition(expires_at: str = '2099-01-01T00:00:00Z') -> LockedEdition:
    return LockedEdition(
        edition_id='edition-1', run_id=RUN_ID, plan_sha256=digest('1'),
        corpus_manifest_sha256=digest('2'), custody_release_sha256=digest('3'),
        independent_audit_sha256=digest('4'), selection_lock_sha256=digest('5'),
        execution_authorization_sha256=digest('6'), adoption_policy=policy(),
        timing_plan_sha256=digest('7'), expires_at=expires_at,
        population=tuple(PopulationMember(record_id=r.record_id, content_sha256=r.content_sha256)
                         for r in records()),
        arm_pins=tuple(ArmPin(arm=arm, model_id=f'model-{arm}', artifact_sha256=digest('8'),
                              configuration_sha256=digest('9')) for arm in ARMS))


def gold_channel():
    return tuple(CustodyGold(record_id=key, content_sha256=record(key).content_sha256, spans=GOLD[key],
                             block_id=PROVENANCE[key][0], slice_name=PROVENANCE[key][1])
                 for key in sorted(MESSAGES))


def prediction(arm: str, record_id: str, spans=()) -> Prediction:
    return Prediction(run_id=RUN_ID, record_id=record_id, content_sha256=record(record_id).content_sha256,
                      arm=arm, model_id=f'model-{arm}', attempt_id=f'{arm}-{record_id}', status='ok',
                      spans=tuple(spans))


def answered(arm: str, record_id: str, spans=()) -> CellResult:
    return CellResult(arm=arm, record_id=record_id, content_sha256=record(record_id).content_sha256,
                      attempted=True, outcome='answered', prediction=prediction(arm, record_id, spans))


def failed(arm: str, record_id: str) -> CellResult:
    return CellResult(arm=arm, record_id=record_id, content_sha256=record(record_id).content_sha256,
                      attempted=True, outcome='backend_failure')


def unavailable(arm: str, record_id: str) -> CellResult:
    return CellResult(arm=arm, record_id=record_id, content_sha256=record(record_id).content_sha256,
                      attempted=False, outcome='adapter_unavailable')


def mixed_cells() -> dict:
    """regex perfect; frontier answers rec-001 and fails rec-002 (partial arm);
    base answers both with no spans (misses everything); finetuned misses the NAME
    on rec-001 (a leaked rendering) and finds the EMAIL: it loses to regex on NAME."""
    cells = [answered('regex', 'rec-001', (NAME_SPAN,)), answered('regex', 'rec-002', (EMAIL_SPAN,)),
             answered('frontier', 'rec-001', (NAME_SPAN,)), failed('frontier', 'rec-002'),
             answered('base', 'rec-001'), answered('base', 'rec-002'),
             answered('finetuned', 'rec-001'), answered('finetuned', 'rec-002', (EMAIL_SPAN,))]
    return {(cell.arm, cell.record_id): cell for cell in cells}


def regex_only_cells() -> dict:
    """regex perfect; the three model arms were never available (not measured)."""
    cells = [answered('regex', 'rec-001', (NAME_SPAN,)), answered('regex', 'rec-002', (EMAIL_SPAN,))]
    cells += [unavailable(arm, key) for arm in ARMS[1:] for key in sorted(MESSAGES)]
    return {(cell.arm, cell.record_id): cell for cell in cells}


def bundle(cells: dict, *, closed: bool = True) -> dict:
    return aggregate_edition(edition(), records(), gold_channel(), cells, closed=closed)


def arm(bundle_or_projection: dict, name: str) -> dict:
    return next(row for row in bundle_or_projection['arms'] if row['arm'] == name)
