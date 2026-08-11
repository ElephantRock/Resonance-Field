"""Configuration for Capability Decay Experiments 081–086."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .integration_campaign import IntegrationCampaignConfig, IntegrationEnvironment


@dataclass(frozen=True, slots=True)
class CapabilityDecaySpec:
    """Private effective-practice memory model.

    Cumulative practice is never modified. This spec only controls the effective
    practice value used to derive current task competence.
    """

    mode: str = "none"
    half_life_cycles: float | None = None
    inactive_cycles: int | None = None
    retention_floor: float = 0.0

    def __post_init__(self) -> None:
        if self.mode not in {"none", "exponential", "step", "exponential_floor"}:
            raise ValueError(f"unsupported capability-decay mode: {self.mode}")
        if self.mode in {"exponential", "exponential_floor"}:
            if self.half_life_cycles is None or self.half_life_cycles <= 0:
                raise ValueError("exponential decay requires a positive half_life_cycles")
        elif self.half_life_cycles is not None:
            raise ValueError("half_life_cycles is only valid for exponential decay")
        if self.mode == "step":
            if self.inactive_cycles is None or self.inactive_cycles <= 0:
                raise ValueError("step decay requires positive inactive_cycles")
        elif self.inactive_cycles is not None:
            raise ValueError("inactive_cycles is only valid for step decay")
        if not 0.0 <= self.retention_floor < 1.0:
            raise ValueError("retention_floor must be in [0, 1)")
        if self.mode != "exponential_floor" and self.retention_floor != 0.0:
            raise ValueError("retention_floor is only valid for exponential_floor")

    @property
    def decays(self) -> bool:
        return self.mode != "none"

    @property
    def timescale(self) -> float | None:
        if self.mode in {"exponential", "exponential_floor"}:
            return self.half_life_cycles
        if self.mode == "step":
            return float(self.inactive_cycles) if self.inactive_cycles is not None else None
        return None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "CapabilityDecaySpec":
        half_life = value.get("half_life_cycles")
        inactive = value.get("inactive_cycles")
        return cls(
            mode=str(value.get("mode", "none")),
            half_life_cycles=float(half_life) if half_life is not None else None,
            inactive_cycles=int(inactive) if inactive is not None else None,
            retention_floor=float(value.get("retention_floor", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class CapabilityDecayConfig:
    integration: IntegrationCampaignConfig
    public_trace_confidence_weight: float
    knowledge_signal_threshold: float
    retrieval_top_k: int
    knowledge_tolerance: float
    minimum_logical_improvement: float
    minimum_dormant_erosion: float
    dormant_inactivity_threshold: int
    screen_exponential_half_lives: tuple[float, ...]
    screen_step_inactive_cycles: int
    screen_floor_half_life: float
    screen_retention_floor: float
    response_scales: tuple[float, ...]
    rapid_shift_period: int
    replication_seeds: tuple[int, ...]
    formation_target_fraction: float
    formation_window: int
    formation_persistence: int
    association_reference_window: int
    association_rolling_window: int
    association_target_fraction: float
    association_persistence: int
    clock_visit_margin: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "CapabilityDecayConfig":
        integration = IntegrationCampaignConfig.from_mapping(value)
        raw = value["capability_decay"]
        assert isinstance(raw, Mapping)
        config = cls(
            integration=integration,
            public_trace_confidence_weight=float(raw["public_trace_confidence_weight"]),
            knowledge_signal_threshold=float(raw["knowledge_signal_threshold"]),
            retrieval_top_k=int(raw["retrieval_top_k"]),
            knowledge_tolerance=float(raw["knowledge_tolerance"]),
            minimum_logical_improvement=float(raw["minimum_logical_improvement"]),
            minimum_dormant_erosion=float(raw["minimum_dormant_erosion"]),
            dormant_inactivity_threshold=int(raw["dormant_inactivity_threshold"]),
            screen_exponential_half_lives=tuple(
                float(item) for item in raw["screen_exponential_half_lives"]
            ),
            screen_step_inactive_cycles=int(raw["screen_step_inactive_cycles"]),
            screen_floor_half_life=float(raw["screen_floor_half_life"]),
            screen_retention_floor=float(raw["screen_retention_floor"]),
            response_scales=tuple(float(item) for item in raw["response_scales"]),
            rapid_shift_period=int(raw["rapid_shift_period"]),
            replication_seeds=tuple(int(item) for item in raw["replication_seeds"]),
            formation_target_fraction=float(raw["formation_target_fraction"]),
            formation_window=int(raw["formation_window"]),
            formation_persistence=int(raw["formation_persistence"]),
            association_reference_window=int(raw["association_reference_window"]),
            association_rolling_window=int(raw["association_rolling_window"]),
            association_target_fraction=float(raw["association_target_fraction"]),
            association_persistence=int(raw["association_persistence"]),
            clock_visit_margin=float(raw["clock_visit_margin"]),
        )
        if not 0 <= config.public_trace_confidence_weight <= 0.5:
            raise ValueError("public_trace_confidence_weight must be in [0, 0.5]")
        if not 0 <= config.knowledge_signal_threshold <= 1:
            raise ValueError("knowledge_signal_threshold must be in [0, 1]")
        if config.retrieval_top_k <= 0:
            raise ValueError("retrieval_top_k must be positive")
        if min(
            config.knowledge_tolerance,
            config.minimum_logical_improvement,
            config.minimum_dormant_erosion,
        ) < 0:
            raise ValueError("capability-decay tolerances must be non-negative")
        if config.dormant_inactivity_threshold <= 0:
            raise ValueError("dormant_inactivity_threshold must be positive")
        if len(config.screen_exponential_half_lives) < 2:
            raise ValueError("screen requires at least two exponential half-lives")
        if any(value <= 0 for value in config.screen_exponential_half_lives):
            raise ValueError("screen half-lives must be positive")
        if config.screen_step_inactive_cycles <= 0 or config.screen_floor_half_life <= 0:
            raise ValueError("screen decay timescales must be positive")
        if not 0 < config.screen_retention_floor < 1:
            raise ValueError("screen_retention_floor must be in (0, 1)")
        if len(config.response_scales) < 3 or any(scale <= 0 for scale in config.response_scales):
            raise ValueError("response_scales must contain at least three positive values")
        if 1.0 not in config.response_scales:
            raise ValueError("response_scales must include 1.0")
        if not 1 <= config.rapid_shift_period < integration.environment.cycles:
            raise ValueError("rapid_shift_period must fit inside the environment")
        if not config.replication_seeds:
            raise ValueError("replication_seeds are required")
        if not 0 < config.formation_target_fraction < 1:
            raise ValueError("formation_target_fraction must be in (0, 1)")
        if min(config.formation_window, config.formation_persistence) <= 0:
            raise ValueError("formation windows must be positive")
        if min(config.association_reference_window, config.association_rolling_window) <= 0:
            raise ValueError("association windows must be positive")
        if not 0 < config.association_target_fraction < 1:
            raise ValueError("association_target_fraction must be in (0, 1)")
        if config.association_persistence <= 0 or config.clock_visit_margin <= 1:
            raise ValueError("association persistence and clock margin are invalid")
        return config


def load_capability_decay_config(
    path: str | Path,
) -> tuple[CapabilityDecayConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    config = CapabilityDecayConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


def capability_environment(
    config: CapabilityDecayConfig,
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


def scaled_decay(spec: CapabilityDecaySpec, scale: float) -> CapabilityDecaySpec:
    """Scale the absolute decay timescale while preserving the kernel family."""
    if scale <= 0:
        raise ValueError("scale must be positive")
    if spec.mode in {"exponential", "exponential_floor"}:
        assert spec.half_life_cycles is not None
        return replace(spec, half_life_cycles=spec.half_life_cycles * scale)
    if spec.mode == "step":
        assert spec.inactive_cycles is not None
        return replace(spec, inactive_cycles=max(1, int(round(spec.inactive_cycles * scale))))
    return spec
