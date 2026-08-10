"""Seeded general-purpose policy used to validate the experiment apparatus."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from uuid import UUID

from resonance.agents.actions import ActionRequest, ActionType
from resonance.agents.runtime import AgentPolicy, DecisionContext


class SeededExperimentPolicy(AgentPolicy):
    """One policy for every agent; variation comes from context and seeded events."""

    def __init__(self, *, seed: int, action_costs: Mapping[str, int]) -> None:
        self._seed = seed
        self._costs = dict(action_costs)

    def _draws(self, cycle: int, slot: int, topic: str) -> tuple[float, float, float]:
        digest = hashlib.sha256(f"{self._seed}:{cycle}:{slot}:{topic}".encode()).digest()
        values = []
        for offset in (0, 8, 16):
            integer = int.from_bytes(digest[offset : offset + 8], "big")
            values.append(integer / (2**64 - 1))
        return values[0], values[1], values[2]

    def _cost(self, action: ActionType) -> int:
        return int(self._costs.get(action.value, 0))

    def choose(self, agent_id: UUID, context: DecisionContext) -> ActionRequest:
        del agent_id
        metadata = context.observation.metadata
        cycle = int(metadata["cycle"])
        slot = int(metadata["agent_slot"])
        topic = str(metadata["topic"])
        balance = int(metadata["balance"])
        market_enabled = bool(metadata["market_enabled"])
        half_life_seconds = float(metadata["half_life_seconds"])
        post_budget = int(metadata["post_budget"])
        post_deadline = metadata["post_deadline"]
        open_task = metadata.get("open_task")
        roll, roll2, roll3 = self._draws(cycle, slot, topic)
        confidence = 0.55 + 0.40 * roll3

        if market_enabled and isinstance(open_task, Mapping) and roll < 0.22:
            task_budget = int(open_task["budget"])
            price = max(1, int(task_budget * (0.45 + 0.35 * roll2)))
            if balance >= self._cost(ActionType.BID_TASK):
                return ActionRequest(
                    ActionType.BID_TASK,
                    {
                        "task_id": open_task["task_id"],
                        "price": price,
                        "estimated_completion_seconds": max(30, int(180 * (1.0 - roll3))),
                        "strategy_summary": f"Seeded independent evaluation for {topic}",
                    },
                    confidence=confidence,
                )

        if market_enabled and roll < 0.38:
            total_required = post_budget + self._cost(ActionType.POST_TASK)
            if balance >= total_required:
                return ActionRequest(
                    ActionType.POST_TASK,
                    {
                        "description": f"Evaluate a competing hypothesis about {topic}",
                        "budget": post_budget,
                        "deadline": post_deadline,
                        "required_capabilities": ["analysis", "verification"],
                        "success_condition": {"synthetic": "controller_settlement"},
                    },
                    confidence=confidence,
                )

        if context.retrieved and roll < 0.66 and balance >= self._cost(ActionType.REINFORCE_TRACE):
            target = context.retrieved[0].trace
            return ActionRequest(
                ActionType.REINFORCE_TRACE,
                {
                    "trace_id": target.trace_id,
                    "reinforcement": 0.15 + 0.25 * roll2,
                    "adoption": 0.10 if target.author_agent_id is not None else 0.0,
                },
                confidence=confidence,
            )

        if balance >= self._cost(ActionType.WRITE_TRACE):
            return ActionRequest(
                ActionType.WRITE_TRACE,
                {
                    "kind": "HYPOTHESIS",
                    "content": f"{topic} hypothesis from cycle {cycle} slot {slot}",
                    "initial_energy": 0.45 + 0.35 * roll2,
                    "half_life_seconds": half_life_seconds,
                    "quality_score": 0.35 + 0.55 * roll3,
                },
                confidence=confidence,
            )

        return ActionRequest(ActionType.ABSTAIN, {}, confidence=confidence)
