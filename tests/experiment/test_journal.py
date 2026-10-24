"""Journal: sole primary first-open and no replay of an uncertain begun call.

Plan: the locked test is used once per edition; a crash after begin is an
unknown attempt that needs investigation, never permission to call again.
"""
import pytest

from m7.experiment.executor import AdapterBinding, execute_edition
from m7.experiment.journal import EditionJournal, JournalError

from .scenario import ARMS, EMAIL_SPAN, NAME_SPAN, arm, edition, gold_channel, prediction, records

SPANS = {'rec-001': (NAME_SPAN,), 'rec-002': (EMAIL_SPAN,)}


def regex_registry(calls: list) -> dict:
    """Only the regex arm is bound; its stub returns the hand-written gold spans."""
    def predict(detached):
        calls.append(detached.record_id)
        return prediction('regex', detached.record_id, SPANS[detached.record_id])
    pin = edition().arm_pins[0]
    return {'regex': AdapterBinding(pin=pin, predict=predict, preflight=lambda inputs: None)}


def event_lines(directory) -> list:
    return (directory / 'events.jsonl').read_bytes().splitlines()


def test_second_open_is_refused_in_same_writer(tmp_path):
    journal = EditionJournal(tmp_path / 'journal')
    with journal.writer():
        journal.seal(edition())
        journal.append({'kind': 'opened'})
        with pytest.raises(JournalError, match='journal_transition_invalid'):
            journal.append({'kind': 'opened'})
    # The refused event never reached disk: exactly one persisted event.
    assert len(event_lines(tmp_path / 'journal')) == 1


def test_second_open_is_refused_after_restart(tmp_path):
    with EditionJournal(tmp_path / 'journal').writer() as first:
        first.seal(edition())
        first.append({'kind': 'opened'})
    reopened = EditionJournal(tmp_path / 'journal')
    with reopened.writer():
        reopened.seal(edition())
        assert reopened.opened
        with pytest.raises(JournalError, match='journal_transition_invalid'):
            reopened.append({'kind': 'opened'})


def test_fresh_run_consumes_open_once_and_closed_rerun_calls_nothing(tmp_path):
    calls, flags = [], []
    authorize = lambda locked, already_opened: flags.append(already_opened)
    directory = tmp_path / 'journal'
    execute_edition(edition(), records(), gold_channel(), regex_registry(calls),
                    EditionJournal(directory), authorize=authorize)
    # The first authorization is the only one that sees an unopened journal.
    assert flags[0] is False and flags.count(False) == 1
    assert calls == ['rec-001', 'rec-002']
    first_run_flags = len(flags)
    rerun = execute_edition(edition(), records(), gold_channel(), regex_registry(calls),
                            EditionJournal(directory), authorize=authorize)
    # A closed edition is aggregated from the journal: never a second first-open, no adapter call.
    assert False not in flags[first_run_flags:]
    assert calls == ['rec-001', 'rec-002']
    assert rerun['edition_state'] == 'closed'
    # Exactly one persisted opened event across both runs.
    assert sum(b'"kind":"opened"' in line for line in event_lines(directory)) == 1


def test_crash_after_begin_becomes_interrupted_unknown_without_a_new_call(tmp_path):
    directory = tmp_path / 'journal'
    # Simulated crash: open, begin regex/rec-001, then the process stops before terminal.
    with EditionJournal(directory).writer() as crashed:
        crashed.seal(edition())
        crashed.append({'kind': 'opened'})
        crashed.append({'kind': 'begin', 'arm': 'regex', 'record_id': 'rec-001'})
        assert crashed.abandoned() == (('regex', 'rec-001'),)
    calls, flags = [], []
    journal = EditionJournal(directory)
    result = execute_edition(edition(), records(), gold_channel(), regex_registry(calls), journal,
                             authorize=lambda locked, already_opened: flags.append(already_opened))
    # The uncertain begun call is never re-issued; only rec-002 reaches the adapter.
    assert calls == ['rec-002']
    # Resume never presents itself as a first open.
    assert False not in flags
    cell = journal.terminals()[('regex', 'rec-001')]
    assert (cell.attempted, cell.outcome, cell.prediction, cell.attempt_metadata_missing) == (
        True, 'interrupted_unknown', None, True)
    regex = arm(result, 'regex')
    # 2 attempted (unknown + answered), 1 answered, 1 error, interruption and missing lineage visible.
    assert (regex['attempted_N'], regex['answered_N'], regex['error_N'], regex['unattempted_N']) == (2, 1, 1, 0)
    assert (regex['interrupted_unknown_N'], regex['attempt_metadata_missing_N']) == (1, 1)
    assert regex['measurement_status'] == 'measured_incomplete'
    # Lineage gate cannot pass with an unknown attempt.
    assert result['adoption']['gates']['attempt_lineage_complete'] is False
    for name in ARMS[1:]:
        assert arm(result, name)['adapter_unavailable_N'] == 2


def test_begun_cell_cannot_be_begun_again(tmp_path):
    with EditionJournal(tmp_path / 'journal').writer() as journal:
        journal.seal(edition())
        journal.append({'kind': 'opened'})
        journal.append({'kind': 'begin', 'arm': 'regex', 'record_id': 'rec-001'})
        with pytest.raises(JournalError, match='duplicate_or_unknown_attempt'):
            journal.append({'kind': 'begin', 'arm': 'regex', 'record_id': 'rec-001'})


def test_abandoned_writer_lock_fails_closed_before_any_call(tmp_path):
    directory = tmp_path / 'journal'
    directory.mkdir()
    (directory / 'writer.lock').write_text('4242', encoding='ascii')
    calls, flags = [], []
    with pytest.raises(FileExistsError):
        execute_edition(edition(), records(), gold_channel(), regex_registry(calls),
                        EditionJournal(directory), authorize=lambda locked, opened: flags.append(opened))
    assert (calls, flags) == ([], [])
    # A foreign lock is left for an operator to investigate, never removed.
    assert (directory / 'writer.lock').read_text(encoding='ascii') == '4242'


def test_different_edition_cannot_reuse_a_sealed_journal(tmp_path):
    with EditionJournal(tmp_path / 'journal').writer() as journal:
        journal.seal(edition())
    other = EditionJournal(tmp_path / 'journal')
    with other.writer():
        with pytest.raises(JournalError, match='edition_seal_conflict'):
            other.seal(edition(expires_at='2098-01-01T00:00:00Z'))
