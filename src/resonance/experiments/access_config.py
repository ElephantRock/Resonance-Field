"""Configuration for Capability-Preserving Access Experiments 075–080."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from .integration_campaign import IntegrationCampaignConfig, IntegrationEnvironment


@dataclass(frozen=True, slots=True)
class AccessControlConfig:
    integration: IntegrationCampaignConfig
    public_trace_confidence_weight: float
    knowledge_signal_threshold: float
    retrieval_top_k: int
    diversified_lineages: int
    knowledge_tolerance: float
    minimum_logical_improvement: float
    screen_exposure_penalty: float
    screen_exposure_window: int
    screen_challenger_inflation: float
    response_scales: tuple[float, ...]
    rapid_shift_period: int
    replication_seeds: tuple[int, ...]
    holdout_strength_scale: float
    holdout_exposure_window: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> AccessControlConfig:
        integration = IntegrationCampaignConfig.from_mapping(value)
        raw = value["access_control"]
        assert isinstance(raw, Mapping)
        config = cls(
            integration=integration,
            public_trace_confidence_weight=float(raw["public_trace_confidence_weight"]),
            knowledge_signal_threshold=float(raw["knowledge_signal_threshold"]),
            retrieval_top_k=int(raw["retrieval_top_k"]),
            diversified_lineages=int(raw["diversified_lineages"]),
            knowledge_tolerance=float(raw["knowledge_tolerance"]),
            minimum_logical_improvement=float(raw["minimum_logical_improvement"]),
            screen_exposure_penalty=float(raw["screen_exposure_penalty"]),
            screen_exposure_window=int(raw["screen_exposure_window"]),
            screen_challenger_inflation=float(raw["screen_challenger_inflation"]),
            response_scales=tuple(float(item) for item in raw["response_scales"]),
            rapid_shift_period=int(raw["rapid_shift_period"]),
            replication_seeds=tuple(int(item) for item in raw["replication_seeds"]),
            holdout_strength_scale=float(raw["holdout_strength_scale"]),
            holdout_exposure_window=int(raw["holdout_exposure_window"]),
        )
        if not 0 <= config.public_trace_confidence_weight <= 0.5:
            raise ValueError("public_trace_confidence_weight must be in [0, 0.5]")
        if not 0 <= config.knowledge_signal_threshold <= 1:
            raise ValueError("knowledge_signal_threshold must be in [0, 1]")
        if config.retrieval_top_k <= 0 or config.diversified_lineages <= 0:
            raise ValueError("retrieval controls must be positive")
        if min(config.knowledge_tolerance, config.minimum_logical_improvement) < 0:
            raise ValueError("access-control tolerances must be non-negative")
        if config.screen_exposure_penalty <= 0:
            raise ValueError("screen_exposure_penalty must be positive")
        if config.screen_exposure_window <= 0:
            raise ValueError("screen_exposure_window must be positive")
        if not 0 < config.screen_challenger_inflation <= 0.5:
            raise ValueError("screen_challenger_inflation must be in (0, 0.5]")
        if len(config.response_scales) < 3 or any(scale <= 0 for scale in config.response_scales):
            raise ValueError("response_scales must contain at least three positive values")
        if 1.0 not in config.response_scales:
            raise ValueError("response_scales must include the reference scale 1.0")
        if not 1 <= config.rapid_shift_period < integration.environment.cycles:
            raise ValueError("rapid_shift_period must fit inside the environment")
        if not config.replication_seeds:
            raise ValueError("replication_seeds are required")
        if not 0 < config.holdout_strength_scale <= 1.5:
            raise ValueError("holdout_strength_scale must be in (0, 1.5]")
        if config.holdout_exposure_window <= 0:
            raise ValueError("holdout_exposure_window must be positive")
        return config


def load_access_config(path: str | Path) -> tuple[AccessControlConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    config = AccessControlConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


def access_environment(
    config: AccessControlConfig,
    *,
    challenger_inflation: float = 0.0,
    cycles: int | None = None,
    shift_period: int | None = None,
    candidate_count: int | None = None,
) -> IntegrationEnvironment:
    base = config.integration.environment
    return replace(
        base,
        confidence_inflation=challenger_inflation,
        cycles=cycles if cycles is not None else base.cycles,
        shift_period=shift_period if shift_period is not None else base.shift_period,
        candidate_count=candidate_count if candidate_count is not None else base.candidate_count,
    )
