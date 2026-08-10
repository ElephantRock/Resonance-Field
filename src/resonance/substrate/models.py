"""Canonical substrate domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from .decay import decayed_energy


def _bounded(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Trace:
    """A persistent stigmergic trace and its current decay anchor."""

    kind: str
    content: str
    created_at: datetime
    updated_at: datetime
    initial_energy: float
    half_life_seconds: float
    trace_id: UUID = field(default_factory=uuid4)
    author_agent_id: UUID | None = None
    embedding: tuple[float, ...] | None = None
    energy_anchor: float | None = None
    energy_updated_at: datetime | None = None
    confidence: float = 0.0
    quality_score: float = 0.0
    adoption_score: float = 0.0
    context_score: float = 0.0
    exploration_bonus: float = 0.0
    repetition_penalty: float = 0.0
    status: str = "active"
    safety_class: str = "standard"
    visibility: str = "shared"

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("kind must not be empty")
        if not self.content.strip():
            raise ValueError("content must not be empty")

        _aware("created_at", self.created_at)
        _aware("updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")

        if self.initial_energy < 0:
            raise ValueError("initial_energy must be non-negative")
        if self.half_life_seconds <= 0:
            raise ValueError("half_life_seconds must be positive")

        for name in (
            "confidence",
            "quality_score",
            "adoption_score",
            "context_score",
            "exploration_bonus",
            "repetition_penalty",
        ):
            _bounded(name, getattr(self, name))

        if self.embedding is not None and len(self.embedding) != 1536:
            raise ValueError("embedding must contain exactly 1536 dimensions")

        if self.energy_anchor is None:
            object.__setattr__(self, "energy_anchor", self.initial_energy)
        elif self.energy_anchor < 0:
            raise ValueError("energy_anchor must be non-negative")

        if self.energy_updated_at is None:
            object.__setattr__(self, "energy_updated_at", self.created_at)
        else:
            _aware("energy_updated_at", self.energy_updated_at)
            if self.energy_updated_at < self.created_at:
                raise ValueError("energy_updated_at must not precede created_at")

    def energy_at(self, at: datetime) -> float:
        """Return trace energy at a point in time from the current decay anchor."""
        _aware("at", at)
        assert self.energy_anchor is not None
        assert self.energy_updated_at is not None
        elapsed = max(0.0, (at - self.energy_updated_at).total_seconds())
        return decayed_energy(self.energy_anchor, elapsed, self.half_life_seconds)


@dataclass(frozen=True, slots=True)
class RetrievedTrace:
    """A trace plus the components used to rank it."""

    trace: Trace
    semantic_similarity: float
    energy: float
    retrieval_score: float
