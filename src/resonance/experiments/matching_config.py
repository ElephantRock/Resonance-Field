"""Configuration for Matching Objective Experiments 093–098."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .integration_campaign import IntegrationCampaignConfig, IntegrationEnvironment


@dataclass(frozen=True, slots=True)
class MatchingObjectiveSpec:
    """Deterministic sealed-bid assignment objective used only by the experiment."""

    mode: str = "baseline"
    confidence_weight: float = 0.45
    price_weight: float = 0.35
    speed_weight: float = 0.20
    confidence_cap: float = 1.0
    blend: float = 1.0
    restore_after_cycle: int | None = None

    def __post_init__(self) -> None:
        allowed = {"baseline", "weighted", "capped_confidence", "geometric"}
        if self.mode not in allowed:
            raise ValueError(f"unsupported matching objective: {self.mode}")
        if any(value < 0 for value in (self.confidence_weight, self.price_weight, self.speed_weight)):
            raise ValueError("matching weights must be non-negative")
        if self.mode in {"weighted", "capped_confidence"}:
            total = self.confidence_weight + self.price_weight + self.speed_weight
            if abs(total - 1.0) > 1e-9:
                raise ValueError("weighted matching objective must sum to 1")
        if not 0 < self.confidence_cap <= 1:
            raise ValueError("confidence_cap must be in (0, 1]")
        if not 0 <= self.blend <= 1:
            raise ValueError("blend must be in [0, 1]")
        if self.mode == "baseline" and self.blend != 1.0:
            raise ValueError("baseline objective cannot be blended")
        if self.restore_after_cycle is not None and self.restore_after_cycle <= 0:
            raise ValueError("restore_after_cycle must be positive")

    @property
    def intervention(self) -> bool:
        return self.mode != "baseline"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> MatchingObjectiveSpec:
        raw_restore = value.get("restore_after_cycle")
        return cls(
            mode=str(value.get("mode", "baseline")),
            confidence_weight=float(value.get("confidence_weight", 0.45)),
            price_weight=float(value.get("price_weight", 0.35)),
            speed_weight=float(value.get("speed_weight", 0.20)),
            confidence_cap=float(value.get("confidence_cap", 1.0)),
            blend=float(value.get("blend", 1.0)),
            restore_after_cycle=int(raw_restore) if raw_restore is not None else None,
        )


@dataclass(frozen=True, slots=True)
class MatchingConfig:
    integration: IntegrationCampaignConfig
    public_trace_confidence_weight: float
    knowledge_signal_threshold: float
    retrieval_top_k: int
    knowledge_tolerance: float
    minimum_logical_improvement: float
    minimum_objective_override_rate: float
    minimum_same_bid_logical_improvement: float
    response_blends: tuple[float, ...]
    rapid_shift_period: int
    replication_seeds: tuple[int, ...]
    reversal_restore_fraction: float
    holdout_restore_fraction: float
    minimum_relock_winner_rebound: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> MatchingConfig:
        integration = IntegrationCampaignConfig.from_mapping(value)
        raw = value["matching"]
        assert isinstance(raw, Mapping)
        config = cls(
            integration=integration,
            public_trace_confidence_weight=float(raw["public_trace_confidence_weight"]),
            knowledge_signal_threshold=float(raw["knowledge_signal_threshold"]),
            retrieval_top_k=int(raw["retrieval_top_k"]),
            knowledge_tolerance=float(raw["knowledge_tolerance"]),
            minimum_logical_improvement=float(raw["minimum_logical_improvement"]),
            minimum_objective_override_rate=float(raw["minimum_objective_override_rate"]),
            minimum_same_bid_logical_improvement=float(
                raw["minimum_same_bid_logical_improvement"]
            ),
            response_blends=tuple(float(item) for item in raw["response_blends"]),
            rapid_shift_period=int(raw["rapid_shift_period"]),
            replication_seeds=tuple(int(item) for item in raw["replication_seeds"]),
            reversal_restore_fraction=float(raw["reversal_restore_fraction"]),
            holdout_restore_fraction=float(raw["holdout_restore_fraction"]),
            minimum_relock_winner_rebound=float(raw["minimum_relock_winner_rebound"]),
        )
        nonnegative = (
            config.public_trace_confidence_weight,
            config.knowledge_signal_threshold,
            config.knowledge_tolerance,
            config.minimum_logical_improvement,
            config.minimum_objective_override_rate,
            config.minimum_same_bid_logical_improvement,
            config.minimum_relock_winner_rebound,
        )
        if any(value < 0 for value in nonnegative):
            raise ValueError("matching weights/tolerances must be non-negative")
        if config.public_trace_confidence_weight > 0.5 or config.knowledge_signal_threshold > 1:
            raise ValueError("trace controls out of range")
        if config.retrieval_top_k <= 0:
            raise ValueError("retrieval_top_k must be positive")
        if len(config.response_blends) < 3 or any(not 0 < item <= 1 for item in config.response_blends):
            raise ValueError("response_blends must contain at least three values in (0, 1]")
        if 1.0 not in config.response_blends:
            raise ValueError("response_blends must include 1.0")
        if not 1 <= config.rapid_shift_period < integration.environment.cycles:
            raise ValueError("rapid_shift_period must fit inside the environment")
        if not config.replication_seeds:
            raise ValueError("replication seeds required")
        if not 0.5 <= config.reversal_restore_fraction < 1.0:
            raise ValueError("reversal_restore_fraction must be in [0.5, 1)")
        if not 0.5 <= config.holdout_restore_fraction < 1.0:
            raise ValueError("holdout_restore_fraction must be in [0.5, 1)")
        return config


def load_matching_config(path: str | Path) -> tuple[MatchingConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    config = MatchingConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


def matching_environment(
    config: MatchingConfig,
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


def with_blend(spec: MatchingObjectiveSpec, blend: float) -> MatchingObjectiveSpec:
    if spec.mode == "baseline":
        return spec
    return replace(spec, blend=max(0.01, min(1.0, blend)), restore_after_cycle=None)
