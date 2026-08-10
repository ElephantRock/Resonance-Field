"""Agent identity and compute-credit domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    agent_id: UUID
    generation: int
    status: str
    model_profile: str
    created_at: datetime
    last_active_at: datetime

    def __post_init__(self) -> None:
        if self.generation < 0:
            raise ValueError("generation must be non-negative")
        if not self.status.strip():
            raise ValueError("status must not be empty")
        if not self.model_profile.strip():
            raise ValueError("model_profile must not be empty")
        _aware("created_at", self.created_at)
        _aware("last_active_at", self.last_active_at)


@dataclass(frozen=True, slots=True)
class ComputeAccount:
    account_id: UUID
    account_kind: str
    balance: int
    created_at: datetime
    owner_agent_id: UUID | None = None
    reference_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.account_kind.strip():
            raise ValueError("account_kind must not be empty")
        if self.balance < 0:
            raise ValueError("balance must be non-negative")
        _aware("created_at", self.created_at)
