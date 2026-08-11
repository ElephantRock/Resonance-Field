"""Configuration for Demand-Structure Experiments 099–104."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .integration_campaign import IntegrationCampaignConfig, IntegrationEnvironment

_ALLOWED_MODES = {"baseline", "shuffled", "interleaved", "paired", "blocked"}


@dataclass(frozen=True, slots=True)
class DemandScheduleSpec:
    """Pure temporal reordering of exogenous task packets within each regime."""

    mode: str = "baseline"
    phase_modes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in _ALLOWED_MODES:
            raise ValueError(f"unsupported demand schedule mode: {self.mode}")
        if any(mode not in _ALLOWED_MODES - {"baseline"} for mode in self.phase_modes):
            raise ValueError("phase_modes may contain only non-baseline schedule modes")

    def mode_for_regime(self, regime: int) -> str:
        if not self.phase_modes:
            return self.mode
        return self.phase_modes[min(regime, len(self.phase_modes) - 1)]

    @property
    def intervention(self) -> bool:
        return self.mode != "baseline" or bool(self.phase_modes)

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["phase_modes"] = list(self.phase_modes)
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DemandScheduleSpec:
        raw_phases = value.get("phase_modes", ())
        if isinstance(raw_phases, str):
            phases: tuple[str, ...] = (raw_phases,)
        elif isinstance(raw_phases, Sequence):
            phases = tuple(str(item) for item in raw_phases)
        else:
            phases = ()
        return cls(mode=str(value.get("mode", "baseline")), phase_modes=phases)


@dataclass(frozen=True, slots=True)
class DemandConfig:
    integration: IntegrationCampaignConfig
    public_trace_confidence_weight: float
    knowledge_signal_threshold: float
    retrieval_top_k: int
    knowledge_tolerance: float
    minimum_logical_improvement: float
    minimum_persistence_change: float
    response_modes: tuple[str, ...]
    replication_seeds: tuple[int, ...]
    minimum_unlock_winner_change: float
    minimum_relock_winner_rebound: float
    holdout_restore_fraction: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DemandConfig:
        integration = IntegrationCampaignConfig.from_mapping(value)
        raw = value["demand"]
        assert isinstance(raw, Mapping)
        config = cls(
            integration=integration,
            public_trace_confidence_weight=float(raw["public_trace_confidence_weight"]),
            knowledge_signal_threshold=float(raw["knowledge_signal_threshold"]),
            retrieval_top_k=int(raw["retrieval_top_k"]),
            knowledge_tolerance=float(raw["knowledge_tolerance"]),
            minimum_logical_improvement=float(raw["minimum_logical_improvement"]),
            minimum_persistence_change=float(raw["minimum_persistence_change"]),
            response_modes=tuple(str(item) for item in raw["response_modes"]),
            replication_seeds=tuple(int(item) for item in raw["replication_seeds"]),
            minimum_unlock_winner_change=float(raw["minimum_unlock_winner_change"]),
            minimum_relock_winner_rebound=float(raw["minimum_relock_winner_rebound"]),
            holdout_restore_fraction=float(raw["holdout_restore_fraction"]),
        )
        if min(
            config.public_trace_confidence_weight,
            config.knowledge_signal_threshold,
            config.knowledge_tolerance,
            config.minimum_logical_improvement,
            config.minimum_persistence_change,
            config.minimum_unlock_winner_change,
            config.minimum_relock_winner_rebound,
        ) < 0:
            raise ValueError("demand weights/tolerances must be non-negative")
        if config.public_trace_confidence_weight > 0.5 or config.knowledge_signal_threshold > 1:
            raise ValueError("trace controls out of range")
        if config.retrieval_top_k <= 0:
            raise ValueError("retrieval_top_k must be positive")
        if len(config.response_modes) < 3:
            raise ValueError("response_modes must contain at least three modes")
        if any(mode not in _ALLOWED_MODES - {"baseline"} for mode in config.response_modes):
            raise ValueError("response_modes contain unsupported modes")
        if not config.replication_seeds:
            raise ValueError("replication seeds required")
        if not 0.5 <= config.holdout_restore_fraction < 1.0:
            raise ValueError("holdout_restore_fraction must be in [0.5, 1)")
        return config


def load_demand_config(path: str | Path) -> tuple[DemandConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    config = DemandConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


def demand_environment(
    config: DemandConfig,
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


__all__ = ["DemandConfig", "DemandScheduleSpec", "demand_environment", "load_demand_config"]
