"""Configuration models for reproducible Resonance Field experiments."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    name: str
    agents: int
    cycles: int
    cycle_seconds: int
    initial_credits: int
    snapshot_every: int
    trace_half_life_seconds: float
    no_decay_half_life_seconds: float
    task_deadline_cycles: int
    task_budget_min: int
    task_budget_max: int
    topics: tuple[str, ...]
    action_costs: Mapping[str, int]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("experiment name must not be empty")
        positive_fields = (
            "agents",
            "cycles",
            "cycle_seconds",
            "initial_credits",
            "snapshot_every",
        )
        for name in positive_fields:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.trace_half_life_seconds <= 0 or self.no_decay_half_life_seconds <= 0:
            raise ValueError("trace half-lives must be positive")
        if self.task_deadline_cycles <= 0:
            raise ValueError("task_deadline_cycles must be positive")
        if self.task_budget_min <= 0 or self.task_budget_max < self.task_budget_min:
            raise ValueError("task budget bounds are invalid")
        if not self.topics or any(not topic.strip() for topic in self.topics):
            raise ValueError("topics must contain non-empty values")
        costs = dict(self.action_costs)
        if any(not key.strip() or value < 0 for key, value in costs.items()):
            raise ValueError("action costs must be non-negative and named")
        object.__setattr__(self, "action_costs", MappingProxyType(costs))

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ExperimentConfig:
        raw_costs = dict(value["action_costs"])
        return cls(
            name=str(value["name"]),
            agents=int(value["agents"]),
            cycles=int(value["cycles"]),
            cycle_seconds=int(value["cycle_seconds"]),
            initial_credits=int(value["initial_credits"]),
            snapshot_every=int(value["snapshot_every"]),
            trace_half_life_seconds=float(value["trace_half_life_seconds"]),
            no_decay_half_life_seconds=float(value["no_decay_half_life_seconds"]),
            task_deadline_cycles=int(value["task_deadline_cycles"]),
            task_budget_min=int(value["task_budget_min"]),
            task_budget_max=int(value["task_budget_max"]),
            topics=tuple(str(item) for item in value["topics"]),
            action_costs={str(key): int(cost) for key, cost in raw_costs.items()},
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "agents": self.agents,
            "cycles": self.cycles,
            "cycle_seconds": self.cycle_seconds,
            "initial_credits": self.initial_credits,
            "snapshot_every": self.snapshot_every,
            "trace_half_life_seconds": self.trace_half_life_seconds,
            "no_decay_half_life_seconds": self.no_decay_half_life_seconds,
            "task_deadline_cycles": self.task_deadline_cycles,
            "task_budget_min": self.task_budget_min,
            "task_budget_max": self.task_budget_max,
            "topics": list(self.topics),
            "action_costs": dict(self.action_costs),
        }


def load_experiment_config(path: str | Path) -> tuple[ExperimentConfig, str]:
    raw = Path(path).read_bytes()
    config_hash = hashlib.sha256(raw).hexdigest()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("experiment config must contain a JSON object")
    return ExperimentConfig.from_mapping(value), config_hash
