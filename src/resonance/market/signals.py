"""System-owned auction signal interface.

Bids never carry these signals. A controller-owned provider may contribute an
additional score component at award time while the production default remains
neutral.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Protocol

from .models import MarketBid, MarketTask


@dataclass(frozen=True, slots=True)
class BidSignal:
    """One auditable system-side contribution to an auction score."""

    adjustment: float = 0.0
    provider_label: str = "neutral"
    components: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider_label.strip():
            raise ValueError("provider_label must not be empty")
        object.__setattr__(
            self,
            "components",
            MappingProxyType({key: float(value) for key, value in self.components.items()}),
        )


class BidSignalProvider(Protocol):
    """Controller-owned source of non-bid auction signals."""

    def signal(
        self,
        task: MarketTask,
        bid: MarketBid,
        *,
        at: datetime,
    ) -> BidSignal: ...


class NeutralBidSignalProvider:
    """Explicit neutral provider useful for controls and tests."""

    def signal(
        self,
        task: MarketTask,
        bid: MarketBid,
        *,
        at: datetime,
    ) -> BidSignal:
        del task, bid, at
        return BidSignal()
