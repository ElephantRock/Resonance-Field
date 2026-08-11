"""Configuration helpers for Lifecycle & Succession Experiments 063–074."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from .integration_campaign import IntegrationCampaignConfig, IntegrationEnvironment


@dataclass(frozen=True, slots=True)
class LifecycleConfig:
    integration: IntegrationCampaignConfig
    reference_practice_gain: float
    fixed_lifetime_cycles: int
    lifetime_candidates: tuple[int, ...]
    stochastic_min_age: int
    advisor_weight: float
    public_trace_confidence_weight: float
    knowledge_signal_threshold: float
    retrieval_top_k: int
    diversified_lineages: int
    knowledge_tolerance: float
    minimum_incumbent_improvement: float
    minimum_hhi_improvement: float
    rapid_shift_period: int
    synthesis_cycles: int
    replication_seeds: tuple[int, ...]
    holdout_lifetime_cycles: int
    holdout_shift_period: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "LifecycleConfig":
        integration = IntegrationCampaignConfig.from_mapping(value)
        raw = value["lifecycle"]
        assert isinstance(raw, Mapping)
        config = cls(
            integration=integration,
            reference_practice_gain=float(raw["reference_practice_gain"]),
            fixed_lifetime_cycles=int(raw["fixed_lifetime_cycles"]),
            lifetime_candidates=tuple(int(item) for item in raw["lifetime_candidates"]),
            stochastic_min_age=int(raw["stochastic_min_age"]),
            advisor_weight=float(raw["advisor_weight"]),
            public_trace_confidence_weight=float(raw["public_trace_confidence_weight"]),
            knowledge_signal_threshold=float(raw["knowledge_signal_threshold"]),
            retrieval_top_k=int(raw["retrieval_top_k"]),
            diversified_lineages=int(raw["diversified_lineages"]),
            knowledge_tolerance=float(raw["knowledge_tolerance"]),
            minimum_incumbent_improvement=float(raw["minimum_incumbent_improvement"]),
            minimum_hhi_improvement=float(raw["minimum_hhi_improvement"]),
            rapid_shift_period=int(raw["rapid_shift_period"]),
            synthesis_cycles=int(raw["synthesis_cycles"]),
            replication_seeds=tuple(int(item) for item in raw["replication_seeds"]),
            holdout_lifetime_cycles=int(raw["holdout_lifetime_cycles"]),
            holdout_shift_period=int(raw["holdout_shift_period"]),
        )
        if config.reference_practice_gain <= 0:
            raise ValueError("reference_practice_gain must be positive")
        if config.fixed_lifetime_cycles <= 2:
            raise ValueError("fixed_lifetime_cycles must exceed two cycles")
        if not config.lifetime_candidates:
            raise ValueError("lifetime_candidates are required")
        if any(item <= 2 for item in config.lifetime_candidates):
            raise ValueError("lifetime candidates must exceed two cycles")
        if config.stochastic_min_age < 0:
            raise ValueError("stochastic_min_age must be non-negative")
        if not 0 <= config.advisor_weight <= 0.5:
            raise ValueError("advisor_weight must be in [0, 0.5]")
        if not 0 <= config.public_trace_confidence_weight <= 0.5:
            raise ValueError("public_trace_confidence_weight must be in [0, 0.5]")
        if not 0 <= config.knowledge_signal_threshold <= 1:
            raise ValueError("knowledge_signal_threshold must be in [0, 1]")
        if config.retrieval_top_k <= 0 or config.diversified_lineages <= 0:
            raise ValueError("retrieval controls must be positive")
        if min(
            config.knowledge_tolerance,
            config.minimum_incumbent_improvement,
            config.minimum_hhi_improvement,
        ) < 0:
            raise ValueError("lifecycle tolerances must be non-negative")
        if not 1 <= config.rapid_shift_period < integration.environment.cycles:
            raise ValueError("rapid_shift_period must fit inside the environment")
        if config.synthesis_cycles <= config.rapid_shift_period:
            raise ValueError("synthesis_cycles must contain at least one rapid shift")
        if not config.replication_seeds:
            raise ValueError("replication_seeds are required")
        if config.holdout_lifetime_cycles <= 2:
            raise ValueError("holdout_lifetime_cycles must exceed two cycles")
        if not 1 <= config.holdout_shift_period < integration.holdout_cycles:
            raise ValueError("holdout_shift_period must fit inside holdout_cycles")
        return config


def load_lifecycle_config(path: str | Path) -> tuple[LifecycleConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    config = LifecycleConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


def high_practice_environment(
    config: LifecycleConfig,
    *,
    cycles: int | None = None,
    shift_period: int | None = None,
) -> IntegrationEnvironment:
    base = config.integration.environment
    return replace(
        base,
        practice_gain=config.reference_practice_gain,
        cycles=cycles if cycles is not None else base.cycles,
        shift_period=shift_period if shift_period is not None else base.shift_period,
    )
