"""Substrate-neutral epistemic event schema for Experiments 142–145."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .llm_epistemic_ontology import validate_relation


def _require_sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
        raise ValueError(f"{label} must be a 64-character SHA-256 hex digest")


def _require_nonempty(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must be non-empty")


@dataclass(frozen=True, slots=True)
class EpistemicEvent:
    event_id: str
    case_id: str
    producer_id: str
    source_id: str
    source_sha256: str
    subject: str
    predicate: str
    object: str
    confidence: float
    observed_at: str
    source_locator: str | None = None
    support_event_ids: tuple[str, ...] = ()
    contradict_event_ids: tuple[str, ...] = ()
    uncertainty: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for label, value in (
            ("event_id", self.event_id),
            ("case_id", self.case_id),
            ("producer_id", self.producer_id),
            ("source_id", self.source_id),
            ("subject", self.subject),
            ("predicate", self.predicate),
            ("object", self.object),
            ("observed_at", self.observed_at),
        ):
            _require_nonempty(value, label)
        validate_relation(self.predicate)
        _require_sha256(self.source_sha256, "source_sha256")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        try:
            parsed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("observed_at must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        if parsed.utcoffset() is None:
            raise ValueError("observed_at must include a valid timezone offset")
        if self.event_id in self.support_event_ids or self.event_id in self.contradict_event_ids:
            raise ValueError("an event cannot support or contradict itself")
        if set(self.support_event_ids) & set(self.contradict_event_ids):
            raise ValueError("the same event cannot be both support and contradiction")

    def canonical_mapping(self) -> dict[str, Any]:
        self.validate()
        return {
            "event_id": self.event_id,
            "case_id": self.case_id,
            "producer_id": self.producer_id,
            "source_id": self.source_id,
            "source_sha256": self.source_sha256.lower(),
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "confidence": self.confidence,
            "observed_at": self.observed_at,
            "source_locator": self.source_locator,
            "support_event_ids": list(self.support_event_ids),
            "contradict_event_ids": list(self.contradict_event_ids),
            "uncertainty": self.uncertainty,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class EpistemicEventLog:
    schema_version: str
    case_id: str
    events: tuple[EpistemicEvent, ...]

    def validate(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("unsupported epistemic event schema version")
        _require_nonempty(self.case_id, "case_id")
        if not self.events:
            raise ValueError("event log must contain at least one event")
        ids: set[str] = set()
        for event in self.events:
            event.validate()
            if event.case_id != self.case_id:
                raise ValueError("every event must belong to the event-log case")
            if event.event_id in ids:
                raise ValueError("event_id values must be unique within a case")
            ids.add(event.event_id)
        for event in self.events:
            references = set(event.support_event_ids) | set(event.contradict_event_ids)
            missing = references - ids
            if missing:
                raise ValueError(f"event references missing event ids: {sorted(missing)}")

    def canonical_bytes(self) -> bytes:
        self.validate()
        payload = {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "events": [event.canonical_mapping() for event in self.events],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def producer_ids(self) -> tuple[str, ...]:
        self.validate()
        return tuple(sorted({event.producer_id for event in self.events}))


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["EpistemicEvent", "EpistemicEventLog", "utc_now_iso"]
