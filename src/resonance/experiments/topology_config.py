"""Configuration for Coordination Topology Experiments 087–092."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .integration_campaign import IntegrationCampaignConfig, IntegrationEnvironment


@dataclass(frozen=True, slots=True)
class TopologySpec:
    """Pre-award task-domain -> agent opportunity routing rule."""

    mode: str = "baseline"
    structured_fraction: float = 0.0
    cooldown_cycles: int = 0
    reset_each_regime: bool = False
    restore_after_cycle: int | None = None

    def __post_init__(self) -> None:
        allowed = {
            "baseline",
            "global_balance",
            "domain_balance",
            "winner_cooldown",
            "hybrid",
        }
        if self.mode not in allowed:
            raise ValueError(f"unsupported topology mode: {self.mode}")
        if not 0.0 <= self.structured_fraction <= 1.0:
            raise ValueError("structured_fraction must be in [0, 1]")
        if self.mode == "baseline" and self.structured_fraction != 0.0:
            raise ValueError("baseline topology must have zero structured_fraction")
        if self.mode != "baseline" and self.structured_fraction <= 0.0:
            raise ValueError("topology intervention requires structured_fraction > 0")
        if self.mode in {"winner_cooldown", "hybrid"}:
            if self.cooldown_cycles <= 0:
                raise ValueError("winner-cooldown topology requires cooldown_cycles > 0")
        elif self.cooldown_cycles != 0:
            raise ValueError("cooldown_cycles only applies to winner-cooldown/hybrid modes")
        if self.restore_after_cycle is not None and self.restore_after_cycle <= 0:
            raise ValueError("restore_after_cycle must be positive")

    @property
    def intervention(self) -> bool:
        return self.mode != "baseline"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> TopologySpec:
        raw_restore = value.get("restore_after_cycle")
        return cls(
            mode=str(value.get("mode", "baseline")),
            structured_fraction=float(value.get("structured_fraction", 0.0)),
            cooldown_cycles=int(value.get("cooldown_cycles", 0)),
            reset_each_regime=bool(value.get("reset_each_regime", False)),
            restore_after_cycle=int(raw_restore) if raw_restore is not None else None,
        )


@dataclass(frozen=True, slots=True)
class TopologyConfig:
    integration: IntegrationCampaignConfig
    public_trace_confidence_weight: float
    knowledge_signal_threshold: float
    retrieval_top_k: int
    knowledge_tolerance: float
    minimum_logical_improvement: float
    minimum_topology_improvement: float
    screen_structured_fraction: float
    screen_cooldown_cycles: int
    response_fractions: tuple[float, ...]
    rapid_shift_period: int
    replication_seeds: tuple[int, ...]
    reversal_restore_fraction: float
    holdout_restore_fraction: float
    minimum_relock_opportunity_rebound: float
    minimum_relock_winner_rebound: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> TopologyConfig:
        integration = IntegrationCampaignConfig.from_mapping(value)
        raw = value["topology"]
        assert isinstance(raw, Mapping)
        config = cls(
            integration=integration,
            public_trace_confidence_weight=float(raw["public_trace_confidence_weight"]),
            knowledge_signal_threshold=float(raw["knowledge_signal_threshold"]),
            retrieval_top_k=int(raw["retrieval_top_k"]),
            knowledge_tolerance=float(raw["knowledge_tolerance"]),
            minimum_logical_improvement=float(raw["minimum_logical_improvement"]),
            minimum_topology_improvement=float(raw["minimum_topology_improvement"]),
            screen_structured_fraction=float(raw["screen_structured_fraction"]),
            screen_cooldown_cycles=int(raw["screen_cooldown_cycles"]),
            response_fractions=tuple(float(item) for item in raw["response_fractions"]),
            rapid_shift_period=int(raw["rapid_shift_period"]),
            replication_seeds=tuple(int(item) for item in raw["replication_seeds"]),
            reversal_restore_fraction=float(raw["reversal_restore_fraction"]),
            holdout_restore_fraction=float(raw["holdout_restore_fraction"]),
            minimum_relock_opportunity_rebound=float(
                raw["minimum_relock_opportunity_rebound"]
            ),
            minimum_relock_winner_rebound=float(raw["minimum_relock_winner_rebound"]),
        )
        for field in (
            config.public_trace_confidence_weight,
            config.knowledge_signal_threshold,
            config.knowledge_tolerance,
            config.minimum_logical_improvement,
            config.minimum_topology_improvement,
            config.minimum_relock_opportunity_rebound,
            config.minimum_relock_winner_rebound,
        ):
            if field < 0:
                raise ValueError("topology weights/tolerances must be non-negative")
        if config.public_trace_confidence_weight > 0.5 or config.knowledge_signal_threshold > 1:
            raise ValueError("trace controls out of range")
        if config.retrieval_top_k <= 0:
            raise ValueError("retrieval_top_k must be positive")
        if not 0 < config.screen_structured_fraction <= 1:
            raise ValueError("screen_structured_fraction must be in (0, 1]")
        if config.screen_cooldown_cycles <= 0:
            raise ValueError("screen_cooldown_cycles must be positive")
        if len(config.response_fractions) < 3:
            raise ValueError("response_fractions must contain at least three values")
        if any(not 0 < item <= 1 for item in config.response_fractions):
            raise ValueError("response fractions must be in (0, 1]")
        if 1.0 not in config.response_fractions:
            raise ValueError("response_fractions must include 1.0")
        if not 1 <= config.rapid_shift_period < integration.environment.cycles:
            raise ValueError("rapid_shift_period must fit inside the environment")
        if not config.replication_seeds:
            raise ValueError("replication seeds required")
        if not 0.5 <= config.reversal_restore_fraction < 1.0:
            raise ValueError("reversal_restore_fraction must be in [0.5, 1)")
        if not 0.5 <= config.holdout_restore_fraction < 1.0:
            raise ValueError("holdout_restore_fraction must be in [0.5, 1)")
        return config


def load_topology_config(path: str | Path) -> tuple[TopologyConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    config = TopologyConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


def topology_environment(
    config: TopologyConfig,
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


def with_fraction(spec: TopologySpec, fraction: float) -> TopologySpec:
    if spec.mode == "baseline":
        return spec
    return replace(spec, structured_fraction=max(0.01, min(1.0, fraction)))
