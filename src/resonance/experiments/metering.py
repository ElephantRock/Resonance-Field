"""Compute-credit metering for experiment actions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from resonance.agents.actions import ActionRequest
from resonance.economy.repository import EconomyRepository

from .postgres import PostgresExperimentStore


@dataclass(slots=True)
class ExperimentComputeMeter:
    economy: EconomyRepository
    store: PostgresExperimentStore
    run_id: UUID
    sink_account_id: UUID
    costs: Mapping[str, int]

    def cost(self, request: ActionRequest) -> int:
        return int(self.costs.get(request.action.value, 0))

    def charge(self, agent_id: UUID, request: ActionRequest, *, at: datetime) -> int:
        credits = self.cost(request)
        transaction_id: UUID | None = None
        if credits:
            source = self.economy.account_for_agent(agent_id)
            transaction_id = self.economy.transfer(
                source.account_id,
                self.sink_account_id,
                credits,
                at=at,
                reason="experiment action compute",
                reference_type="action_request",
                reference_id=request.request_id,
            )
        self.store.record_action_cost(
            run_id=self.run_id,
            request_id=request.request_id,
            agent_id=agent_id,
            action=request.action.value,
            credits=credits,
            ledger_transaction_id=transaction_id,
            charged_at=at,
        )
        return credits
