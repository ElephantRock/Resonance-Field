"""Configuration model for Experiment 003 reputation plasticity."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ReputationExperimentConfig:
    name: str
    agents: int
    cycles: int
    cycle_seconds: int
    shift_cycle: int
    snapshot_every: int
    initial_credits: int
    domains: tuple[str, ...]
    candidate_count: int
    task_budget: int
    bid_deadline_seconds: int
    fast_half_life_seconds: float
    slow_half_life_seconds: float
    evidence_initial_energy: float
    reputation_weight: float
    base_success_probability: float
    practice_gain: float
    maximum_success_probability: float
    early_post_shift_cycles: int
    late_post_shift_cycles: int

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.domains:
            raise ValueError("experiment name and domains are required")
        if any(not item.strip() for item in self.domains):
            raise ValueError("domains must not contain empty values")
        if self.agents <= 1 or self.cycles <= 1 or self.cycle_seconds <= 0:
            raise ValueError("population and horizon must be positive")
        if not 0 < self.shift_cycle < self.cycles:
            raise ValueError("shift_cycle must fall inside the experiment")
        if self.snapshot_every <= 0 or self.initial_credits <= 0:
            raise ValueError("snapshot_every and initial_credits must be positive")
        if not 1 <= self.candidate_count < self.agents:
            raise ValueError("candidate_count must be smaller than the population")
        if self.task_budget <= 1 or self.bid_deadline_seconds <= 0:
            raise ValueError("task budget and deadline must be positive")
        if self.fast_half_life_seconds <= 0 or self.slow_half_life_seconds <= 0:
            raise ValueError("trace half-lives must be positive")
        if not 0 < self.evidence_initial_energy <= 1:
            raise ValueError("evidence_initial_energy must be in (0, 1]")
        for name in (
            "reputation_weight",
            "base_success_probability",
            "practice_gain",
            "maximum_success_probability",
        ):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.maximum_success_probability < self.base_success_probability:
            raise ValueError("maximum success probability cannot be below base")
        if self.early_post_shift_cycles <= 0 or self.late_post_shift_cycles <= 0:
            raise ValueError("post-shift windows must be positive")

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> ReputationExperimentConfig:
        return cls(
            name=str(value["name"]),
            agents=int(value["agents"]),
            cycles=int(value["cycles"]),
            cycle_seconds=int(value["cycle_seconds"]),
            shift_cycle=int(value["shift_cycle"]),
            snapshot_every=int(value["snapshot_every"]),
            initial_credits=int(value["initial_credits"]),
            domains=tuple(str(item) for item in value["domains"]),
            candidate_count=int(value["candidate_count"]),
            task_budget=int(value["task_budget"]),
            bid_deadline_seconds=int(value["bid_deadline_seconds"]),
            fast_half_life_seconds=float(value["fast_half_life_seconds"]),
            slow_half_life_seconds=float(value["slow_half_life_seconds"]),
            evidence_initial_energy=float(value["evidence_initial_energy"]),
            reputation_weight=float(value["reputation_weight"]),
            base_success_probability=float(value["base_success_probability"]),
            practice_gain=float(value["practice_gain"]),
            maximum_success_probability=float(value["maximum_success_probability"]),
            early_post_shift_cycles=int(value["early_post_shift_cycles"]),
            late_post_shift_cycles=int(value["late_post_shift_cycles"]),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "agents": self.agents,
            "cycles": self.cycles,
            "cycle_seconds": self.cycle_seconds,
            "shift_cycle": self.shift_cycle,
            "snapshot_every": self.snapshot_every,
            "initial_credits": self.initial_credits,
            "domains": list(self.domains),
            "candidate_count": self.candidate_count,
            "task_budget": self.task_budget,
            "bid_deadline_seconds": self.bid_deadline_seconds,
            "fast_half_life_seconds": self.fast_half_life_seconds,
            "slow_half_life_seconds": self.slow_half_life_seconds,
            "evidence_initial_energy": self.evidence_initial_energy,
            "reputation_weight": self.reputation_weight,
            "base_success_probability": self.base_success_probability,
            "practice_gain": self.practice_gain,
            "maximum_success_probability": self.maximum_success_probability,
            "early_post_shift_cycles": self.early_post_shift_cycles,
            "late_post_shift_cycles": self.late_post_shift_cycles,
        }

    def half_life_for(self, arm: str) -> float:
        return self.fast_half_life_seconds if arm.startswith("fast_") else self.slow_half_life_seconds

    def reputation_enabled(self, arm: str) -> bool:
        return arm.endswith("_reputation")


def load_reputation_experiment_config(
    path: str | Path,
) -> tuple[ReputationExperimentConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("experiment config must contain a JSON object")
    return ReputationExperimentConfig.from_mapping(value), hashlib.sha256(raw).hexdigest()
