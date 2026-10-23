"""Append-only local custody journal. No reads/writes until explicitly called."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from typing import Iterator

from .lifecycle_models import CustodyEvent, Receipt
from .provenance import canonical_bytes, commitment

ZERO = '0' * 64


class CustodyJournal:
    """One trusted custody root, all editions, serialized by exclusive creation.

    A crash leaves a lock or partial event: fail closed, require operator recovery.
    Hash chains detect corruption, not hostile rewrite by an authorized OS user.
    Back up the store externally; never reset/delete a store to reopen an edition.
    """
    def __init__(self, root: Path):
        self.root = root

    @contextmanager
    def writer(self) -> Iterator[None]:
        # Root is pre-provisioned with custody ACLs; do not create it implicitly.
        root = self.root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError('custody_store_not_directory')
        lock = root / '.custody-writer.lock'
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise ValueError('custody_writer_busy_or_recovery_required') from None
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(b'custody-writer-v1\n')
                stream.flush()
                os.fsync(stream.fileno())
            yield
        finally:
            # This invocation created the lock; never remove another owner's lock.
            lock.unlink()

    def events(self) -> tuple[CustodyEvent, ...]:
        directory = self.root.resolve(strict=True) / 'custody-events'
        if not directory.exists():
            return ()
        paths = sorted(directory.iterdir())
        if len(paths) > 100000:
            raise ValueError('custody_journal_too_large')
        events = []
        previous = ZERO
        for sequence, path in enumerate(paths, start=1):
            if path.name != f'{sequence:08d}.json' or path.is_symlink():
                raise ValueError('custody_journal_sequence_invalid')
            with path.open('rb') as stream:
                raw = stream.read(1000001)
            if len(raw) > 1000000:
                raise ValueError('custody_event_too_large')
            event = CustodyEvent.model_validate_json(raw)
            if event.sequence != sequence or event.previous_sha256 != previous:
                raise ValueError('custody_journal_chain_invalid')
            events.append(event)
            previous = commitment(event)
        return tuple(events)

    def append(self, receipt: Receipt, events: tuple[CustodyEvent, ...]) -> None:
        """Caller holds writer lock and has validated current state."""
        directory = self.root.resolve(strict=True) / 'custody-events'
        directory.mkdir(exist_ok=True)
        event = CustodyEvent(sequence=len(events) + 1,
                            previous_sha256=commitment(events[-1]) if events else ZERO,
                            receipt=receipt)
        with (directory / f'{event.sequence:08d}.json').open('xb') as stream:
            stream.write(canonical_bytes(event))
            stream.flush()
            os.fsync(stream.fileno())
