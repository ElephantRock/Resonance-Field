"""Task-market domain models and deterministic bid scoring."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from uuid import UUID


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class MarketTask:
    task_id: UUID
    requester_agent_id: UUID
    escrow_account_id: UUID
    description: str
    budget: int
    deadline: datetime
    created_at: datetime
    required_capabilities: tuple[str, ...] = ()
    success_condition: Mapping[str, object] = field(default_factory=dict)
    status: str = "open"
    awarded_agent_id: UUID | None = None
    winning_bid_id: UUID | None = None
    awarded_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise ValueError("description must not be empty")
        if self.budget <= 0:
            raise ValueError("budget must be positive")
        _aware("deadline", self.deadline)
        _aware("created_at", self.created_at)
        if self.deadline <= self.created_at:
            raise ValueError("deadline must be after task creation")
        if self.awarded_at is not None:
            _aware("awarded_at", self.awarded_at)
        if self.completed_at is not None:
            _aware("completed_at", self.completed_at)
        object.__setattr__(self, "success_condition", MappingProxyType(dict(self.success_condition)))


@dataclass(frozen=True, slots=True)
class MarketBid:
    bid_id: UUID
    task_id: UUID
    bidder_agent_id: UUID
    price: int
    confidence: float
    estimated_completion_seconds: int
    strategy_summary: str
    submitted_at: datetime
    status: str = "sealed"

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError("price must be positive")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.estimated_completion_seconds <= 0:
            raise ValueError("estimated_completion_seconds must be positive")
        if not self.strategy_summary.strip():
            raise ValueError("strategy_summary must not be empty")
        _aware("submitted_at", self.submitted_at)


@dataclass(frozen=True, slots=True)
class AuctionResult:
    task: MarketTask
    winning_bid: MarketBid
    score: float


def bid_score(task: MarketTask, bid: MarketBid) -> float:
    """Score an eligible bid without inventing reputation signals not implemented yet."""
    if bid.task_id != task.task_id:
        raise ValueError("bid does not belong to task")
    if bid.price > task.budget:
        raise ValueError("bid price exceeds task budget")

    price_efficiency = 1.0 - (bid.price / task.budget)
    available_seconds = max(1.0, (task.deadline - task.created_at).total_seconds())
    speed = 1.0 - min(1.0, bid.estimated_completion_seconds / available_seconds)
    return 0.45 * bid.confidence + 0.35 * price_efficiency + 0.20 * speed
