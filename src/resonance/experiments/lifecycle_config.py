"""Configuration helpers for the lifecycle campaign."""

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
    expected_lifetime: int
    short_lifetime: int
    long_lifetime: int
    holdout_lifetime: int
    minimum_actor_incumbency_reduction: float
    minimum_knowledge_retention: float
    public_retrieval_k: int
    public_success_gain: float
    public_confidence_gain: float
    advisory_success_gain: float
    cultural_diversity_per_lineage: int
    rapid_shift_period: int
    replication_seeds: tuple[int, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> LifecycleConfig:
        integration = IntegrationCampaignConfig.from_mapping(value)
        raw = value["lifecycle"]
        assert isinstance(raw, Mapping)
        config = cls(
            integration=integration,
            expected_lifetime=int(raw["expected_lifetime"]),
            short_lifetime=int(raw["short_lifetime"]),
            long_lifetime=int(raw["long_lifetime"]),
            holdout_lifetime=int(raw["holdout_lifetime"]),
            minimum_actor_incumbency_reduction=float(raw["minimum_actor_incumbency_reduction"]),
            minimum_knowledge_retention=float(raw["minimum_knowledge_retention"]),
            public_retrieval_k=int(raw["public_retrieval_k"]),
            public_success_gain=float(raw["public_success_gain"]),
            public_confidence_gain=float(raw["public_confidence_gain"]),
            advisory_success_gain=float(raw["advisory_success_gain"]),
            cultural_diversity_per_lineage=int(raw["cultural_diversity_per_lineage"]),
            rapid_shift_period=int(raw["rapid_shift_period"]),
            replication_seeds=tuple(int(item) for item in raw["replication_seeds"]),
        )
        if min(
            config.expected_lifetime,
            config.short_lifetime,
            config.long_lifetime,
            config.holdout_lifetime,
            config.public_retrieval_k,
            config.cultural_diversity_per_lineage,
            config.rapid_shift_period,
        ) <= 0:
            raise ValueError("lifecycle durations and retrieval bounds must be positive")
        if not config.short_lifetime < config.expected_lifetime < config.long_lifetime:
            raise ValueError("short/expected/long lifetimes must be ordered")
        if config.rapid_shift_period >= integration.environment.cycles:
            raise ValueError("rapid_shift_period must fit inside the campaign horizon")
        if not 0 <= config.minimum_actor_incumbency_reduction <= 1:
            raise ValueError("minimum_actor_incumbency_reduction must be in [0, 1]")
        if not 0 <= config.minimum_knowledge_retention <= 1:
            raise ValueError("minimum_knowledge_retention must be in [0, 1]")
        if min(config.public_success_gain, config.public_confidence_gain, config.advisory_success_gain) < 0:
            raise ValueError("knowledge/advisory gains must be non-negative")
        if not config.replication_seeds:
            raise ValueError("replication_seeds are required")
        return config


def load_lifecycle_config(path: str | Path) -> tuple[LifecycleConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    config = LifecycleConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


def with_shift(base: IntegrationEnvironment, shift_period: int) -> IntegrationEnvironment:
    return replace(base, shift_period=shift_period)
