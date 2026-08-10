"""Configuration for the controlled trace-decay stress experiment."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class DecayExperimentConfig:
    name: str
    agents: int
    cycles: int
    cycle_seconds: int
    snapshot_every: int
    initial_credits: int
    neighborhoods: tuple[str, ...]
    traces_per_neighborhood: int
    retrieval_limit: int
    fast_half_life_seconds: float
    slow_half_life_seconds: float
    no_decay_half_life_seconds: float
    reinforcement_amount: float
    resurrection_energy_threshold: float
    novel_trace_every_cycles: int
    probe_every_cycles: int
    action_costs: Mapping[str, int]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("experiment name must not be empty")
        for field_name in (
            "agents",
            "cycles",
            "cycle_seconds",
            "snapshot_every",
            "initial_credits",
            "traces_per_neighborhood",
            "retrieval_limit",
            "novel_trace_every_cycles",
            "probe_every_cycles",
        ):
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be positive")
        if not self.neighborhoods or any(not item.strip() for item in self.neighborhoods):
            raise ValueError("neighborhoods must contain non-empty values")
        for value in (
            self.fast_half_life_seconds,
            self.slow_half_life_seconds,
            self.no_decay_half_life_seconds,
        ):
            if value <= 0:
                raise ValueError("half-lives must be positive")
        if not self.fast_half_life_seconds < self.slow_half_life_seconds < self.no_decay_half_life_seconds:
            raise ValueError("half-lives must satisfy fast < slow < no_decay")
        if not 0 < self.reinforcement_amount <= 1:
            raise ValueError("reinforcement_amount must be in (0, 1]")
        if not 0 <= self.resurrection_energy_threshold <= 1:
            raise ValueError("resurrection_energy_threshold must be between 0 and 1")
        costs = dict(self.action_costs)
        if any(not key.strip() or value < 0 for key, value in costs.items()):
            raise ValueError("action costs must be non-negative and named")
        object.__setattr__(self, "action_costs", MappingProxyType(costs))

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DecayExperimentConfig:
        raw_costs = dict(value["action_costs"])
        return cls(
            name=str(value["name"]),
            agents=int(value["agents"]),
            cycles=int(value["cycles"]),
            cycle_seconds=int(value["cycle_seconds"]),
            snapshot_every=int(value["snapshot_every"]),
            initial_credits=int(value["initial_credits"]),
            neighborhoods=tuple(str(item) for item in value["neighborhoods"]),
            traces_per_neighborhood=int(value["traces_per_neighborhood"]),
            retrieval_limit=int(value["retrieval_limit"]),
            fast_half_life_seconds=float(value["fast_half_life_seconds"]),
            slow_half_life_seconds=float(value["slow_half_life_seconds"]),
            no_decay_half_life_seconds=float(value["no_decay_half_life_seconds"]),
            reinforcement_amount=float(value["reinforcement_amount"]),
            resurrection_energy_threshold=float(value["resurrection_energy_threshold"]),
            novel_trace_every_cycles=int(value["novel_trace_every_cycles"]),
            probe_every_cycles=int(value["probe_every_cycles"]),
            action_costs={str(key): int(cost) for key, cost in raw_costs.items()},
        )

    def half_life_for(self, arm: str) -> float:
        if arm == "fast_decay":
            return self.fast_half_life_seconds
        if arm == "slow_decay":
            return self.slow_half_life_seconds
        if arm == "no_decay":
            return self.no_decay_half_life_seconds
        raise ValueError(f"unsupported decay arm: {arm}")

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "agents": self.agents,
            "cycles": self.cycles,
            "cycle_seconds": self.cycle_seconds,
            "snapshot_every": self.snapshot_every,
            "initial_credits": self.initial_credits,
            "neighborhoods": list(self.neighborhoods),
            "traces_per_neighborhood": self.traces_per_neighborhood,
            "retrieval_limit": self.retrieval_limit,
            "fast_half_life_seconds": self.fast_half_life_seconds,
            "slow_half_life_seconds": self.slow_half_life_seconds,
            "no_decay_half_life_seconds": self.no_decay_half_life_seconds,
            "reinforcement_amount": self.reinforcement_amount,
            "resurrection_energy_threshold": self.resurrection_energy_threshold,
            "novel_trace_every_cycles": self.novel_trace_every_cycles,
            "probe_every_cycles": self.probe_every_cycles,
            "action_costs": dict(self.action_costs),
        }


def load_decay_experiment_config(path: str | Path) -> tuple[DecayExperimentConfig, str]:
    raw = Path(path).read_bytes()
    config_hash = hashlib.sha256(raw).hexdigest()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("decay experiment config must contain a JSON object")
    return DecayExperimentConfig.from_mapping(value), config_hash
