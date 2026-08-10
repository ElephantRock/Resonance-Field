"""Typed action boundary shared by all Resonance Field agents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID, uuid4


class ActionType(StrEnum):
    """Primitive actions available to initially general-purpose agents."""

    OBSERVE = "OBSERVE"
    QUERY_SUBSTRATE = "QUERY_SUBSTRATE"
    READ_TRACE = "READ_TRACE"
    WRITE_TRACE = "WRITE_TRACE"
    REINFORCE_TRACE = "REINFORCE_TRACE"
    CHALLENGE_TRACE = "CHALLENGE_TRACE"
    CROSSOVER = "CROSSOVER"
    POST_TASK = "POST_TASK"
    BID_TASK = "BID_TASK"
    DELEGATE = "DELEGATE"
    REQUEST_TOOL = "REQUEST_TOOL"
    REQUEST_FORK = "REQUEST_FORK"
    VOTE = "VOTE"
    ABSTAIN = "ABSTAIN"
    SLEEP = "SLEEP"


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """An agent proposal. Proposals never execute without gateway evaluation."""

    action: ActionType
    payload: Mapping[str, object] = field(default_factory=dict)
    confidence: float = 0.0
    request_id: UUID = field(default_factory=uuid4)
    correlation_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


class OutcomeStatus(StrEnum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    APPROVAL_REQUIRED = "approval_required"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    """Result of policy evaluation plus any permitted execution."""

    status: OutcomeStatus
    output_trace_ids: tuple[UUID, ...] = ()
    data: Mapping[str, object] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))
