"""Configuration for Trajectory/Hysteresis Experiments 117–122."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_ENDPOINT_FEATURES = (
    "winner_domain_mi",
    "success_domain_hhi",
    "practice_concentration",
    "incumbent_share",
    "activation_regime_alignment",
)

_TRAJECTORY_FEATURES = (
    "path_length",
    "basin_transitions",
    "momentum",
    "trajectory_roughness",
)

_HISTORY_KINDS = (
    "smooth_reference",
    "aligned_history",
    "counter_history",
    "annealed_history",
)


@dataclass(frozen=True, slots=True)
class TrajectoryEnvironment:
    shift_period: int
    activation_cycle: int
    history_start: int
    history_end: int
    cycles: int
    candidate_count: int

    def __post_init__(self) -> None:
        if self.shift_period <= 0:
            raise ValueError("shift_period must be positive")
        if not 0 <= self.history_start < self.history_end <= self.activation_cycle <= self.cycles:
            raise ValueError("history/washout/activation ordering invalid")
        if self.activation_cycle - self.history_end != self.shift_period:
            raise ValueError("washout must equal exactly one regime")
        if self.history_end - self.history_start != 2 * self.shift_period:
            raise ValueError("history construction must span exactly two regimes")
        if self.candidate_count <= 0:
            raise ValueError("candidate_count must be positive")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> TrajectoryEnvironment:
        return cls(
            shift_period=int(value["shift_period"]),
            activation_cycle=int(value["activation_cycle"]),
            history_start=int(value["history_start"]),
            history_end=int(value["history_end"]),
            cycles=int(value["cycles"]),
            candidate_count=int(value["candidate_count"]),
        )


@dataclass(frozen=True, slots=True)
class TrajectoryHysteresisConfig:
    name: str
    canonical_endogenous_config: str
    feedback_strength: float
    history_feedback_strength: float
    anneal_epsilon: float
    endpoint_features: tuple[str, ...]
    trajectory_features: tuple[str, ...]
    history_kinds: tuple[str, ...]
    max_feature_difference: float
    max_rms_distance: float
    neutral_band: float
    minimum_endpoint_support: float
    minimum_path_gap: float
    minimum_basin_discordance: float
    minimum_momentum_gap: float
    minimum_effect_gap: float
    minimum_sign_discordance: float
    minimum_anneal_concentration_gain: float
    minimum_anneal_entropy_reduction: float
    success_tolerance: float
    knowledge_tolerance: float
    minimum_predictor_loo_accuracy: float
    minimum_predictor_loo_balanced_accuracy: float
    minimum_predictor_abs_spearman: float
    maximum_predictor_familywise_p: float
    minimum_predictor_validation_accuracy: float
    minimum_predictor_validation_balanced_accuracy: float
    standard: TrajectoryEnvironment
    timing_control: TrajectoryEnvironment
    holdout: TrajectoryEnvironment
    instrumentation_seeds: tuple[int, ...]
    discovery_seeds: tuple[int, ...]
    replication_seeds: tuple[int, ...]
    timing_seeds: tuple[int, ...]
    holdout_seeds: tuple[int, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> TrajectoryHysteresisConfig:
        matching = value["matching"]
        gates = value["gates"]
        predictor = value["predictor"]
        assert isinstance(matching, Mapping)
        assert isinstance(gates, Mapping)
        assert isinstance(predictor, Mapping)
        config = cls(
            name=str(value["name"]),
            canonical_endogenous_config=str(value["canonical_endogenous_config"]),
            feedback_strength=float(value["feedback_strength"]),
            history_feedback_strength=float(value["history_feedback_strength"]),
            anneal_epsilon=float(value["anneal_epsilon"]),
            endpoint_features=tuple(str(x) for x in value["endpoint_features"]),
            trajectory_features=tuple(str(x) for x in value["trajectory_features"]),
            history_kinds=tuple(str(x) for x in value["history_kinds"]),
            max_feature_difference=float(matching["max_feature_difference"]),
            max_rms_distance=float(matching["max_rms_distance"]),
            neutral_band=float(gates["neutral_band"]),
            minimum_endpoint_support=float(gates["minimum_endpoint_support"]),
            minimum_path_gap=float(gates["minimum_path_gap"]),
            minimum_basin_discordance=float(gates["minimum_basin_discordance"]),
            minimum_momentum_gap=float(gates["minimum_momentum_gap"]),
            minimum_effect_gap=float(gates["minimum_effect_gap"]),
            minimum_sign_discordance=float(gates["minimum_sign_discordance"]),
            minimum_anneal_concentration_gain=float(gates["minimum_anneal_concentration_gain"]),
            minimum_anneal_entropy_reduction=float(gates["minimum_anneal_entropy_reduction"]),
            success_tolerance=float(gates["success_tolerance"]),
            knowledge_tolerance=float(gates["knowledge_tolerance"]),
            minimum_predictor_loo_accuracy=float(predictor["minimum_loo_accuracy"]),
            minimum_predictor_loo_balanced_accuracy=float(predictor["minimum_loo_balanced_accuracy"]),
            minimum_predictor_abs_spearman=float(predictor["minimum_abs_spearman"]),
            maximum_predictor_familywise_p=float(predictor["maximum_familywise_p"]),
            minimum_predictor_validation_accuracy=float(predictor["minimum_validation_accuracy"]),
            minimum_predictor_validation_balanced_accuracy=float(
                predictor["minimum_validation_balanced_accuracy"]
            ),
            standard=TrajectoryEnvironment.from_mapping(value["standard"]),  # type: ignore[arg-type]
            timing_control=TrajectoryEnvironment.from_mapping(value["timing_control"]),  # type: ignore[arg-type]
            holdout=TrajectoryEnvironment.from_mapping(value["holdout"]),  # type: ignore[arg-type]
            instrumentation_seeds=tuple(int(x) for x in value["instrumentation_seeds"]),
            discovery_seeds=tuple(int(x) for x in value["discovery_seeds"]),
            replication_seeds=tuple(int(x) for x in value["replication_seeds"]),
            timing_seeds=tuple(int(x) for x in value["timing_seeds"]),
            holdout_seeds=tuple(int(x) for x in value["holdout_seeds"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.feedback_strength != 0.5:
            raise ValueError("post-activation feedback is frozen at 0.5")
        if self.history_feedback_strength != 0.25:
            raise ValueError("history feedback is frozen at 0.25")
        if self.anneal_epsilon != 0.10:
            raise ValueError("annealing epsilon is frozen at 0.10")
        if self.endpoint_features != _ENDPOINT_FEATURES:
            raise ValueError("endpoint features changed")
        if self.trajectory_features != _TRAJECTORY_FEATURES:
            raise ValueError("trajectory features changed")
        if self.history_kinds != _HISTORY_KINDS:
            raise ValueError("history conditions changed")
        if self.standard != TrajectoryEnvironment(18, 54, 0, 36, 126, 7):
            raise ValueError("standard environment changed")
        if self.timing_control != TrajectoryEnvironment(18, 63, 9, 45, 144, 7):
            raise ValueError("timing-control environment changed")
        if self.holdout != TrajectoryEnvironment(15, 45, 0, 30, 120, 7):
            raise ValueError("holdout environment changed")
        groups = (
            self.instrumentation_seeds,
            self.discovery_seeds,
            self.replication_seeds,
            self.timing_seeds,
            self.holdout_seeds,
        )
        if tuple(map(len, groups)) != (4, 12, 8, 8, 8):
            raise ValueError("seed cohort sizes changed")
        flat = [seed for group in groups for seed in group]
        if len(flat) != len(set(flat)):
            raise ValueError("seed cohorts must be disjoint")
        bounded = (
            self.max_feature_difference,
            self.max_rms_distance,
            self.neutral_band,
            self.minimum_endpoint_support,
            self.minimum_path_gap,
            self.minimum_basin_discordance,
            self.minimum_momentum_gap,
            self.minimum_effect_gap,
            self.minimum_sign_discordance,
            self.minimum_anneal_concentration_gain,
            self.minimum_anneal_entropy_reduction,
            self.success_tolerance,
            self.knowledge_tolerance,
            self.minimum_predictor_loo_accuracy,
            self.minimum_predictor_loo_balanced_accuracy,
            self.minimum_predictor_abs_spearman,
            self.maximum_predictor_familywise_p,
            self.minimum_predictor_validation_accuracy,
            self.minimum_predictor_validation_balanced_accuracy,
        )
        if any(not 0.0 <= x <= 1.0 for x in bounded):
            raise ValueError("frozen gates must lie in [0,1]")


def load_trajectory_hysteresis_config(
    path: str | Path,
) -> tuple[TrajectoryHysteresisConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, Mapping):
        raise ValueError("trajectory-hysteresis config must be a JSON object")
    config = TrajectoryHysteresisConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


__all__ = [
    "TrajectoryEnvironment",
    "TrajectoryHysteresisConfig",
    "load_trajectory_hysteresis_config",
]
