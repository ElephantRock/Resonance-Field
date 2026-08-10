"""Common deterministic policy for Experiment 002."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from resonance.agents.actions import ActionRequest, ActionType
from resonance.agents.runtime import AgentPolicy, DecisionContext


class DecayStressPolicy(AgentPolicy):
    """Reinforce cooling evidence opportunistically; otherwise query the substrate."""

    def __init__(self, *, seed: int, action_costs: Mapping[str, int]) -> None:
        self._seed = seed
        self._costs = dict(action_costs)

    def _draw(self, cycle: int, slot: int, neighborhood: str) -> float:
        digest = hashlib.sha256(
            f"decay:{self._seed}:{cycle}:{slot}:{neighborhood}".encode()
        ).digest()
        return int.from_bytes(digest[:8], "big") / (2**64 - 1)

    def _id(self, cycle: int, slot: int, neighborhood: str, kind: str) -> UUID:
        return uuid5(
            NAMESPACE_URL,
            f"resonance:decay:{self._seed}:{cycle}:{slot}:{neighborhood}:{kind}",
        )

    def _cost(self, action: ActionType) -> int:
        return int(self._costs.get(action.value, 0))

    def choose(self, agent_id: UUID, context: DecisionContext) -> ActionRequest:
        del agent_id
        metadata = context.observation.metadata
        cycle = int(metadata["cycle"])
        slot = int(metadata["agent_slot"])
        neighborhood = str(metadata["neighborhood"])
        threshold = float(metadata["resurrection_energy_threshold"])
        reinforcement = float(metadata["reinforcement_amount"])
        balance = int(metadata["balance"])
        roll = self._draw(cycle, slot, neighborhood)

        cooling = [
            (rank, item)
            for rank, item in enumerate(context.retrieved, start=1)
            if rank > 1 and item.energy <= threshold
        ]
        if cooling and roll < 0.55 and balance >= self._cost(ActionType.REINFORCE_TRACE):
            rank, target = min(cooling, key=lambda pair: (pair[1].energy, -pair[0]))
            return ActionRequest(
                ActionType.REINFORCE_TRACE,
                {
                    "trace_id": target.trace.trace_id,
                    "reinforcement": reinforcement,
                    "pre_rank": rank,
                    "pre_energy": target.energy,
                    "neighborhood": neighborhood,
                },
                confidence=0.80,
                request_id=self._id(cycle, slot, neighborhood, "request"),
                correlation_id=self._id(cycle, slot, neighborhood, "correlation"),
            )

        return ActionRequest(
            ActionType.QUERY_SUBSTRATE,
            {},
            confidence=0.70,
            request_id=self._id(cycle, slot, neighborhood, "request"),
            correlation_id=self._id(cycle, slot, neighborhood, "correlation"),
        )
