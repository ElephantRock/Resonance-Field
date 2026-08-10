"""Persistent, evidence-backed reputation domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ReputationState:
    agent_id: UUID
    dimension: str
    context_key: str
    alpha: float
    beta: float
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.dimension.strip() or not self.context_key.strip():
            raise ValueError("dimension and context_key must not be empty")
        if self.alpha <= 0 or self.beta <= 0:
            raise ValueError("alpha and beta must be positive")
        _aware("updated_at", self.updated_at)

    @property
    def score(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def evidence_mass(self) -> float:
        return self.alpha + self.beta - 2.0
