"""Storage boundary for the stigmergic substrate."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from .models import RetrievedTrace, Trace
from .retrieval import RetrievalWeights


class TraceRepository(Protocol):
    """Persistence contract consumed by agent and substrate services."""

    def add(self, trace: Trace) -> None: ...

    def get(self, trace_id: UUID) -> Trace | None: ...

    def add_relation(
        self,
        parent_trace_id: UUID,
        child_trace_id: UUID,
        relation_type: str,
    ) -> None: ...

    def parents(self, child_trace_id: UUID) -> Sequence[Trace]: ...

    def children(self, parent_trace_id: UUID) -> Sequence[Trace]: ...

    def reinforce(
        self,
        trace_id: UUID,
        *,
        at: datetime,
        actor_agent_id: UUID | None = None,
        kind: str = "reinforcement",
        reinforcement: float = 0.0,
        adoption: float = 0.0,
        verified_utility: float = 0.0,
    ) -> Trace: ...

    def search(
        self,
        query_embedding: Sequence[float],
        *,
        at: datetime,
        limit: int = 10,
        weights: RetrievalWeights | None = None,
    ) -> Sequence[RetrievedTrace]: ...
