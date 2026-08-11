"""Configuration for Endogenous Demand Feedback Experiments 105–110."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .integration_campaign import IntegrationCampaignConfig, IntegrationEnvironment

_ALLOWED_MODES = {"exogenous", "closed_loop", "permuted_source"}


@dataclass(frozen=True, slots=True)
class EndogenousDemandSpec:
    """Success-reinforced task-domain generator used only by the experimental campaign."""

    mode: str = "exogenous"
    strength: float = 0.0
    phase_strengths: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in _ALLOWED_MODES:
            raise ValueError(f"unsupported endogenous-demand mode: {self.mode}")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError("feedback strength must be in [0, 1]")
        if any(not 0.0 <= value <= 1.0 for value in self.phase_strengths):
            raise ValueError("phase strengths must be in [0, 1]")
        if self.mode == "exogenous" and (self.strength != 0.0 or any(self.phase_strengths)):
            raise ValueError("exogenous mode must have zero feedback strength")

    def strength_for_cycle(self, cycle: int, cycles: int) -> float:
        if not self.phase_strengths:
            return self.strength
        phase = min(len(self.phase_strengths) - 1, cycle * len(self.phase_strengths) // cycles)
        return self.phase_strengths[phase]

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["phase_strengths"] = list(self.phase_strengths)
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> EndogenousDemandSpec:
        raw_phases = value.get("phase_strengths", ())
        if isinstance(raw_phases, Sequence) and not isinstance(raw_phases, str):
            phases = tuple(float(item) for item in raw_phases)
        else:
            phases = ()
        return cls(
            mode=str(value.get("mode", "exogenous")),
            strength=float(value.get("strength", 0.0)),
            phase_strengths=phases,
        )


@dataclass(frozen=True, slots=True)
class EndogenousDemandConfig:
    integration: IntegrationCampaignConfig
    public_trace_confidence_weight: float
    knowledge_signal_threshold: float
    retrieval_top_k: int
    knowledge_tolerance: float
    minimum_logical_change: float
    minimum_feedback_override: float
    feedback_window: int
    strengths: tuple[float, ...]
    replication_seeds: tuple[int, ...]
    minimum_winner_repeat_change: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> EndogenousDemandConfig:
        integration = IntegrationCampaignConfig.from_mapping(value)
        raw = value["endogenous_demand"]
        assert isinstance(raw, Mapping)
        config = cls(
            integration=integration,
            public_trace_confidence_weight=float(raw["public_trace_confidence_weight"]),
            knowledge_signal_threshold=float(raw["knowledge_signal_threshold"]),
            retrieval_top_k=int(raw["retrieval_top_k"]),
            knowledge_tolerance=float(raw["knowledge_tolerance"]),
            minimum_logical_change=float(raw["minimum_logical_change"]),
            minimum_feedback_override=float(raw["minimum_feedback_override"]),
            feedback_window=int(raw["feedback_window"]),
            strengths=tuple(float(item) for item in raw["strengths"]),
            replication_seeds=tuple(int(item) for item in raw["replication_seeds"]),
            minimum_winner_repeat_change=float(raw["minimum_winner_repeat_change"]),
        )
        if min(
            config.public_trace_confidence_weight,
            config.knowledge_signal_threshold,
            config.knowledge_tolerance,
            config.minimum_logical_change,
            config.minimum_feedback_override,
            config.minimum_winner_repeat_change,
        ) < 0:
            raise ValueError("endogenous-demand weights/tolerances must be non-negative")
        if config.public_trace_confidence_weight > 0.5 or config.knowledge_signal_threshold > 1:
            raise ValueError("trace controls out of range")
        if config.retrieval_top_k <= 0 or config.feedback_window <= 0:
            raise ValueError("retrieval_top_k and feedback_window must be positive")
        if config.strengths != (0.25, 0.5, 0.75):
            raise ValueError("feedback strength bracket is frozen at 0.25, 0.50, 0.75")
        if not config.replication_seeds:
            raise ValueError("replication seeds required")
        return config


def load_endogenous_demand_config(
    path: str | Path,
) -> tuple[EndogenousDemandConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    config = EndogenousDemandConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


def endogenous_environment(
    config: EndogenousDemandConfig,
    *,
    cycles: int | None = None,
    shift_period: int | None = None,
    candidate_count: int | None = None,
) -> IntegrationEnvironment:
    base = config.integration.environment
    return replace(
        base,
        confidence_inflation=0.0,
        cycles=cycles if cycles is not None else base.cycles,
        shift_period=shift_period if shift_period is not None else base.shift_period,
        candidate_count=candidate_count if candidate_count is not None else base.candidate_count,
    )


__all__ = [
    "EndogenousDemandConfig",
    "EndogenousDemandSpec",
    "endogenous_environment",
    "load_endogenous_demand_config",
]
