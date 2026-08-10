"""Configuration helpers for the two-timescale campaign."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from .integration_campaign import IntegrationCampaignConfig, IntegrationEnvironment


@dataclass(frozen=True, slots=True)
class TwoTimescaleConfig:
    integration: IntegrationCampaignConfig
    stable_cycles: int
    measurement_shift_period: int
    formation_target_fraction: float
    formation_window: int
    forgetting_window: int
    incumbent_reference_window: int
    forgetting_target_fraction: float
    persistence_windows: int
    effect_epsilon: float
    slow_practice_gain: float
    fast_practice_gain: float
    interpolation_practice_gain: float
    holdout_practice_gain: float
    model_min_shift_period: int
    model_max_shift_period: int
    challenge_multiplier: float
    holdout_multiplier: float
    model_neutral_band: float
    minimum_model_accuracy: float
    replication_seeds: tuple[int, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "TwoTimescaleConfig":
        integration = IntegrationCampaignConfig.from_mapping(value)
        raw = value["two_timescale"]
        assert isinstance(raw, Mapping)
        config = cls(
            integration=integration,
            stable_cycles=int(raw["stable_cycles"]),
            measurement_shift_period=int(raw["measurement_shift_period"]),
            formation_target_fraction=float(raw["formation_target_fraction"]),
            formation_window=int(raw["formation_window"]),
            forgetting_window=int(raw["forgetting_window"]),
            incumbent_reference_window=int(raw["incumbent_reference_window"]),
            forgetting_target_fraction=float(raw["forgetting_target_fraction"]),
            persistence_windows=int(raw["persistence_windows"]),
            effect_epsilon=float(raw["effect_epsilon"]),
            slow_practice_gain=float(raw["slow_practice_gain"]),
            fast_practice_gain=float(raw["fast_practice_gain"]),
            interpolation_practice_gain=float(raw["interpolation_practice_gain"]),
            holdout_practice_gain=float(raw["holdout_practice_gain"]),
            model_min_shift_period=int(raw["model_min_shift_period"]),
            model_max_shift_period=int(raw["model_max_shift_period"]),
            challenge_multiplier=float(raw["challenge_multiplier"]),
            holdout_multiplier=float(raw["holdout_multiplier"]),
            model_neutral_band=float(raw["model_neutral_band"]),
            minimum_model_accuracy=float(raw["minimum_model_accuracy"]),
            replication_seeds=tuple(int(item) for item in raw["replication_seeds"]),
        )
        base_gain = integration.environment.practice_gain
        if config.stable_cycles <= config.formation_window:
            raise ValueError("stable_cycles must exceed formation_window")
        if not 1 <= config.measurement_shift_period < config.stable_cycles:
            raise ValueError("measurement_shift_period must fit inside stable_cycles")
        if min(config.formation_window, config.forgetting_window, config.persistence_windows) <= 0:
            raise ValueError("measurement windows must be positive")
        if config.incumbent_reference_window <= 0:
            raise ValueError("incumbent_reference_window must be positive")
        if not 0 < config.formation_target_fraction < 1:
            raise ValueError("formation_target_fraction must be in (0, 1)")
        if not 0 < config.forgetting_target_fraction < 1:
            raise ValueError("forgetting_target_fraction must be in (0, 1)")
        if config.effect_epsilon < 0:
            raise ValueError("effect_epsilon must be non-negative")
        if not 0 < config.slow_practice_gain < base_gain < config.fast_practice_gain:
            raise ValueError("practice gains must bracket the baseline gain")
        if not config.slow_practice_gain < config.holdout_practice_gain < base_gain:
            raise ValueError("holdout_practice_gain must interpolate slow and baseline gains")
        if not base_gain < config.interpolation_practice_gain < config.fast_practice_gain:
            raise ValueError("interpolation_practice_gain must interpolate baseline and fast gains")
        if not 1 <= config.model_min_shift_period < config.model_max_shift_period:
            raise ValueError("model shift bounds are invalid")
        if not 0 < config.challenge_multiplier < 1 < config.holdout_multiplier:
            raise ValueError("challenge multiplier must be below one and holdout multiplier above one")
        if not 0 <= config.model_neutral_band < 0.5:
            raise ValueError("model_neutral_band must be in [0, 0.5)")
        if not 0 <= config.minimum_model_accuracy <= 1:
            raise ValueError("minimum_model_accuracy must be in [0, 1]")
        if not config.replication_seeds:
            raise ValueError("replication_seeds are required")
        return config


def load_two_timescale_config(path: str | Path) -> tuple[TwoTimescaleConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    config = TwoTimescaleConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


def stable_environment(
    base: IntegrationEnvironment,
    *,
    cycles: int,
    practice_gain: float,
) -> IntegrationEnvironment:
    return replace(base, cycles=cycles, shift_period=cycles - 1, practice_gain=practice_gain)


def shift_environment(
    base: IntegrationEnvironment,
    *,
    shift_period: int,
    practice_gain: float,
) -> IntegrationEnvironment:
    cycles = max(shift_period * 2, shift_period + 12)
    return replace(base, cycles=cycles, shift_period=shift_period, practice_gain=practice_gain)


def clamp_shift(config: TwoTimescaleConfig, value: float) -> int:
    return max(
        config.model_min_shift_period,
        min(config.model_max_shift_period, int(round(value))),
    )
