"""Trusted persistence boundary for agent identity and compute credits."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from .models import AgentIdentity, ComputeAccount


class EconomyRepository(Protocol):
    def register_agent(
        self,
        agent_id: UUID,
        *,
        at: datetime,
        generation: int = 0,
        model_profile: str = "STANDARD",
        initial_credits: int = 0,
    ) -> AgentIdentity: ...

    def get_agent(self, agent_id: UUID) -> AgentIdentity | None: ...

    def account_for_agent(self, agent_id: UUID) -> ComputeAccount: ...

    def balance(self, agent_id: UUID) -> int: ...

    def issue(
        self,
        agent_id: UUID,
        amount: int,
        *,
        at: datetime,
        reason: str = "allocation",
        reference_type: str | None = None,
        reference_id: UUID | None = None,
    ) -> UUID: ...

    def create_system_account(
        self,
        account_kind: str,
        *,
        at: datetime,
        reference_id: UUID | None = None,
    ) -> ComputeAccount: ...

    def transfer(
        self,
        source_account_id: UUID,
        target_account_id: UUID,
        amount: int,
        *,
        at: datetime,
        reason: str,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
    ) -> UUID: ...
