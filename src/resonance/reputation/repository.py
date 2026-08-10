"""Repository boundary for non-spendable reputation evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from .models import ReputationState


class ReputationRepository(Protocol):
    def get(
        self,
        agent_id: UUID,
        *,
        dimension: str,
        context_key: str,
        at: datetime,
    ) -> ReputationState: ...

    def record_evidence(
        self,
        agent_id: UUID,
        *,
        dimension: str,
        context_key: str,
        positive: bool,
        source_type: str,
        source_id: UUID,
        at: datetime,
        weight: float = 1.0,
    ) -> ReputationState: ...
