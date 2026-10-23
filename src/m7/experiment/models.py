"""Committed evaluation edition; no model values or hidden gold in this wire."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import Field, model_validator

from m7.contracts import Arm, Boundary, Digest, Identifier, LogRecord, Span
from .adoption import AdoptionPolicy

ARMS = ('regex', 'frontier', 'base', 'finetuned')


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('utf-8')


def commitment(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def utc_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('timezone_required')
    return parsed.astimezone(timezone.utc)


class PopulationMember(Boundary):
    record_id: Identifier
    content_sha256: Digest


class ArmPin(Boundary):
    arm: Arm
    model_id: Identifier
    artifact_sha256: Digest
    configuration_sha256: Digest


class LockedEdition(Boundary):
    schema_version: Literal['LockedEdition/v1'] = 'LockedEdition/v1'
    edition_id: Identifier
    run_id: Identifier
    split_id: Literal['inference'] = 'inference'
    plan_sha256: Digest
    corpus_manifest_sha256: Digest
    custody_release_sha256: Digest
    independent_audit_sha256: Digest
    selection_lock_sha256: Digest
    execution_authorization_sha256: Digest
    adoption_policy: AdoptionPolicy
    timing_plan_sha256: Digest
    expires_at: str
    population: Annotated[tuple[PopulationMember, ...], Field(min_length=1)]
    arm_pins: Annotated[tuple[ArmPin, ...], Field(min_length=4, max_length=4)]
    bootstrap_seed: Annotated[int, Field(ge=0)] = 7
    message_max_codepoints: Literal[1024] = 1024

    @model_validator(mode='after')
    def coherent(self) -> LockedEdition:
        ids = [row.record_id for row in self.population]
        if len(ids) != len(set(ids)) or ids != sorted(ids):
            raise ValueError('population_must_be_unique_and_sorted')
        if tuple(pin.arm for pin in self.arm_pins) != ARMS:
            raise ValueError('all_four_ordered_arm_pins_required')
        utc_time(self.expires_at)
        return self

    @property
    def sha256(self) -> str:
        return commitment(self.model_dump(mode='json'))

    def require_current(self, now: datetime | None = None) -> None:
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None or instant >= utc_time(self.expires_at):
            raise ValueError('edition_authorization_expired')


class CustodyGold(Boundary):
    """Private evaluator channel. Never serialize into journal or adapter requests."""
    record_id: Identifier
    content_sha256: Digest
    spans: tuple[Span, ...]
    block_id: Identifier
    slice_name: Literal['normal', 'challenge']


def check_channels(edition: LockedEdition, inference: tuple[LogRecord, ...],
                   gold: tuple[CustodyGold, ...]) -> None:
    expected = {row.record_id: row.content_sha256 for row in edition.population}
    records = {row.record_id: row for row in inference}
    labels = {row.record_id: row for row in gold}
    if len(records) != len(inference) or len(labels) != len(gold):
        raise ValueError('duplicate_channel_record')
    if records.keys() != expected.keys() or labels.keys() != expected.keys():
        raise ValueError('population_channel_mismatch')
    for key, digest in expected.items():
        record, truth = records[key], labels[key]
        if record.content_sha256 != digest or truth.content_sha256 != digest:
            raise ValueError('channel_hash_mismatch')
        if record.split_id != edition.split_id:
            raise ValueError('edition_split_mismatch')
        if any(s.end > len(record.log.message) for s in truth.spans):
            raise ValueError('gold_bounds_invalid')
        if len({(s.start, s.end, s.label) for s in truth.spans}) != len(truth.spans):
            raise ValueError('duplicate_gold_span')


__all__ = ['ARMS', 'ArmPin', 'CustodyGold', 'LockedEdition', 'PopulationMember',
           'canonical', 'commitment', 'check_channels']
