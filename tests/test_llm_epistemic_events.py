from __future__ import annotations

import pytest

from resonance.experiments.llm_epistemic_events import (
    EpistemicEvent,
    EpistemicEventLog,
)

SOURCE_HASH = "a" * 64


def _event(event_id: str, *, producer_id: str = "producer-1") -> EpistemicEvent:
    return EpistemicEvent(
        event_id=event_id,
        case_id="case-001",
        producer_id=producer_id,
        source_id="source-001",
        source_sha256=SOURCE_HASH,
        subject="component-x",
        predicate="depends_on",
        object="component-y",
        confidence=0.8,
        observed_at="2026-08-12T12:00:00Z",
    )


def test_event_log_is_canonical_and_hashable() -> None:
    log = EpistemicEventLog(
        schema_version="1.0",
        case_id="case-001",
        events=(_event("event-1"), _event("event-2", producer_id="producer-2")),
    )

    assert len(log.sha256()) == 64
    assert log.producer_ids() == ("producer-1", "producer-2")
    assert log.canonical_bytes() == log.canonical_bytes()


def test_event_log_rejects_missing_references() -> None:
    event = EpistemicEvent(
        **{
            **_event("event-1").canonical_mapping(),
            "support_event_ids": ("missing",),
        }
    )
    log = EpistemicEventLog(schema_version="1.0", case_id="case-001", events=(event,))

    with pytest.raises(ValueError, match="missing event ids"):
        log.validate()


def test_event_rejects_unhashed_source() -> None:
    event = EpistemicEvent(
        event_id="event-1",
        case_id="case-001",
        producer_id="producer-1",
        source_id="source-001",
        source_sha256="not-a-hash",
        subject="x",
        predicate="relates_to",
        object="y",
        confidence=0.5,
        observed_at="2026-08-12T12:00:00Z",
    )

    with pytest.raises(ValueError, match="SHA-256"):
        event.validate()


def test_event_rejects_naive_timestamp() -> None:
    event = EpistemicEvent(
        event_id="event-1",
        case_id="case-001",
        producer_id="producer-1",
        source_id="source-001",
        source_sha256=SOURCE_HASH,
        subject="x",
        predicate="relates_to",
        object="y",
        confidence=0.5,
        observed_at="2026-08-12T12:00:00",
    )

    with pytest.raises(ValueError, match="timezone"):
        event.validate()
