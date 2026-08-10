"""Task-market service boundary used by the agent runtime and auction controller."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from .models import AuctionResult, MarketBid, MarketTask


class MarketService(Protocol):
    def post_task(
        self,
        requester_agent_id: UUID,
        *,
        description: str,
        budget: int,
        deadline: datetime,
        at: datetime,
        required_capabilities: Sequence[str] = (),
        success_condition: Mapping[str, object] | None = None,
    ) -> MarketTask: ...

    def submit_bid(
        self,
        bidder_agent_id: UUID,
        *,
        task_id: UUID,
        price: int,
        confidence: float,
        estimated_completion_seconds: int,
        strategy_summary: str,
        at: datetime,
    ) -> MarketBid: ...

    def get_task(self, task_id: UUID) -> MarketTask | None: ...

    def award(self, task_id: UUID, *, at: datetime) -> AuctionResult | None: ...

    def settle(self, task_id: UUID, *, at: datetime) -> MarketTask: ...
