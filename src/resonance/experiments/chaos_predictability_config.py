"""Configuration for Chaos / Predictability-Decay Experiments 123–128."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_EPSILONS = (1e-6, 1e-4, 1e-2, 1e-1, 1.0)


@dataclass(frozen=True, slots=True)
class ChaosEnvironment:
    cycles: int
    shift_period: int
    candidate_count: int

    def __post_init__(self) -> None:
        if self.cycles <= self.shift_period * 2:
            raise ValueError("chaos environment requires at least three regimes")
        if self.shift_period <= 0 or self.candidate_count <= 0:
            raise ValueError("invalid chaos environment")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ChaosEnvironment":
        return cls(
            cycles=int(value["cycles"]),
            shift_period=int(value["shift_period"]),
            candidate_count=int(value["candidate_count"]),
        )


@dataclass(frozen=True, slots=True)
class ChaosPredictabilityConfig:
    name: str
    canonical_endogenous_config: str
    feedback_strength: float
    perturb_cycle: int
    trace_min_cycle: int
    feedback_delay_cycles: int
    epsilons: tuple[float, ...]
    delta_micro: float
    delta_meso: float
    delta_macro: float
    persistent_hits: int
    persistent_window: int
    maximum_scaling_spearman: float
    minimum_distinct_finite_horizons: int
    minimum_local_micro_meso_crossing: float
    minimum_local_macro_crossing: float
    minimum_bounded_crossing_share: float
    maximum_saturation_cv: float
    minimum_org_chaos_macro_crossing: float
    minimum_org_chaos_basin_disagreement: float
    minimum_final_success: float
    minimum_final_winners: int
    minimum_final_domains: int
    saturation_growth_limit: float
    lock_in_incumbency: float
    plastic_incumbency: float
    plastic_success_tolerance: float
    minimum_mixture_share: float
    standard: ChaosEnvironment
    holdout: ChaosEnvironment
    instrumentation_seeds: tuple[int, ...]
    discovery_seeds: tuple[int, ...]
    replication_seeds: tuple[int, ...]
    holdout_seeds: tuple[int, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ChaosPredictabilityConfig":
        thresholds = value["distance_thresholds"]
        scaling = value["scaling_gates"]
        bounded = value["boundedness"]
        basins = value["basins"]
        assert isinstance(thresholds, Mapping)
        assert isinstance(scaling, Mapping)
        assert isinstance(bounded, Mapping)
        assert isinstance(basins, Mapping)
        config = cls(
            name=str(value["name"]),
            canonical_endogenous_config=str(value["canonical_endogenous_config"]),
            feedback_strength=float(value["feedback_strength"]),
            perturb_cycle=int(value["perturb_cycle"]),
            trace_min_cycle=int(value["trace_min_cycle"]),
            feedback_delay_cycles=int(value["feedback_delay_cycles"]),
            epsilons=tuple(float(x) for x in value["epsilons"]),
            delta_micro=float(thresholds["micro"]),
            delta_meso=float(thresholds["meso"]),
            delta_macro=float(thresholds["macro"]),
            persistent_hits=int(thresholds["persistent_hits"]),
            persistent_window=int(thresholds["persistent_window"]),
            maximum_scaling_spearman=float(scaling["maximum_spearman"]),
            minimum_distinct_finite_horizons=int(scaling["minimum_distinct_finite_horizons"]),
            minimum_local_micro_meso_crossing=float(scaling["minimum_local_micro_meso_crossing"]),
            minimum_local_macro_crossing=float(scaling["minimum_local_macro_crossing"]),
            minimum_bounded_crossing_share=float(scaling["minimum_bounded_crossing_share"]),
            maximum_saturation_cv=float(scaling["maximum_saturation_cv"]),
            minimum_org_chaos_macro_crossing=float(scaling["minimum_org_chaos_macro_crossing"]),
            minimum_org_chaos_basin_disagreement=float(scaling["minimum_org_chaos_basin_disagreement"]),
            minimum_final_success=float(bounded["minimum_final_success"]),
            minimum_final_winners=int(bounded["minimum_final_winners"]),
            minimum_final_domains=int(bounded["minimum_final_domains"]),
            saturation_growth_limit=float(bounded["saturation_growth_limit"]),
            lock_in_incumbency=float(basins["lock_in_incumbency"]),
            plastic_incumbency=float(basins["plastic_incumbency"]),
            plastic_success_tolerance=float(basins["plastic_success_tolerance"]),
            minimum_mixture_share=float(basins["minimum_mixture_share"]),
            standard=ChaosEnvironment.from_mapping(value["standard"]),  # type: ignore[arg-type]
            holdout=ChaosEnvironment.from_mapping(value["holdout"]),  # type: ignore[arg-type]
            instrumentation_seeds=tuple(int(x) for x in value["instrumentation_seeds"]),
            discovery_seeds=tuple(int(x) for x in value["discovery_seeds"]),
            replication_seeds=tuple(int(x) for x in value["replication_seeds"]),
            holdout_seeds=tuple(int(x) for x in value["holdout_seeds"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.feedback_strength != 0.5:
            raise ValueError("feedback strength is frozen at 0.5")
        if self.perturb_cycle != 5 or self.trace_min_cycle != 5:
            raise ValueError("microscopic perturbation locations are frozen at cycle 5")
        if self.feedback_delay_cycles != 1:
            raise ValueError("feedback timing control is frozen at +1 cycle")
        if self.epsilons != _EPSILONS:
            raise ValueError("epsilon grid changed")
        if self.standard != ChaosEnvironment(126, 18, 7):
            raise ValueError("standard chaos environment changed")
        if self.holdout != ChaosEnvironment(120, 15, 7):
            raise ValueError("holdout chaos environment changed")
        groups = (
            self.instrumentation_seeds,
            self.discovery_seeds,
            self.replication_seeds,
            self.holdout_seeds,
        )
        if tuple(map(len, groups)) != (4, 8, 8, 8):
            raise ValueError("chaos seed cohort sizes changed")
        flat = [seed for group in groups for seed in group]
        if len(flat) != len(set(flat)):
            raise ValueError("chaos seed cohorts must be disjoint")
        if not (0 < self.persistent_hits <= self.persistent_window):
            raise ValueError("invalid persistent crossing rule")
        if self.maximum_scaling_spearman != -0.70:
            raise ValueError("scaling Spearman gate changed")
        bounded = (
            self.delta_micro,
            self.delta_meso,
            self.delta_macro,
            self.minimum_local_micro_meso_crossing,
            self.minimum_local_macro_crossing,
            self.minimum_bounded_crossing_share,
            self.maximum_saturation_cv,
            self.minimum_org_chaos_macro_crossing,
            self.minimum_org_chaos_basin_disagreement,
            self.minimum_final_success,
            self.saturation_growth_limit,
            self.lock_in_incumbency,
            self.plastic_incumbency,
            self.plastic_success_tolerance,
            self.minimum_mixture_share,
        )
        if any(not 0 <= x <= 1 for x in bounded):
            raise ValueError("bounded chaos controls must lie in [0,1]")


def load_chaos_predictability_config(
    path: str | Path,
) -> tuple[ChaosPredictabilityConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, Mapping):
        raise ValueError("chaos config must be a JSON object")
    config = ChaosPredictabilityConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


__all__ = ["ChaosEnvironment", "ChaosPredictabilityConfig", "load_chaos_predictability_config"]
