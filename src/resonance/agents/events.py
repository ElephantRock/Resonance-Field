"""Decision provenance emitted by the agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence
from uuid import UUID, uuid4

from .actions import ActionType, OutcomeStatus
from .gateway import PolicyResult


@dataclass(frozen=True, slots=True)
class DecisionEvent:
    """Auditable provenance for one agent proposal and its outcome."""

    agent_id: UUID
    occurred_at: datetime
    trigger: str
    proposed_action: ActionType
    policy_result: PolicyResult
    policy_reason: str
    outcome_status: OutcomeStatus
    confidence: float
    request_id: UUID
    correlation_id: UUID
    retrieved_trace_ids: tuple[UUID, ...] = ()
    output_trace_ids: tuple[UUID, ...] = ()
    action_payload: Mapping[str, object] = field(default_factory=dict)
    outcome_data: Mapping[str, object] = field(default_factory=dict)
    error: str | None = None
    event_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if not self.trigger.strip():
            raise ValueError("trigger must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "action_payload", MappingProxyType(dict(self.action_payload)))
        object.__setattr__(self, "outcome_data", MappingProxyType(dict(self.outcome_data)))


class DecisionEventStore(Protocol):
    """Append-only persistence boundary for agent decision provenance."""

    def append(self, event: DecisionEvent) -> None: ...

    def get(self, event_id: UUID) -> DecisionEvent | None: ...

    def list_for_agent(self, agent_id: UUID, *, limit: int = 100) -> Sequence[DecisionEvent]: ...


class InMemoryDecisionEventStore:
    """Deterministic event store for unit tests and local experiments."""

    def __init__(self) -> None:
        self._events: list[DecisionEvent] = []

    def append(self, event: DecisionEvent) -> None:
        self._events.append(event)

    def get(self, event_id: UUID) -> DecisionEvent | None:
        return next((event for event in self._events if event.event_id == event_id), None)

    def list_for_agent(self, agent_id: UUID, *, limit: int = 100) -> Sequence[DecisionEvent]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        events = [event for event in self._events if event.agent_id == agent_id]
        return tuple(reversed(events[-limit:]))
