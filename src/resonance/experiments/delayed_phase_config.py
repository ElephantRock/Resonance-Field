"""Configuration for Delayed-Onset Phase Observability Experiments 111–116."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


_FROZEN_FEATURES = (
    "winner_domain_mi",
    "success_domain_hhi",
    "practice_concentration",
    "incumbent_share",
    "activation_regime_alignment",
)


@dataclass(frozen=True, slots=True)
class PhaseEnvironment:
    shift_period: int
    burn_in_cycles: int
    cycles: int
    candidate_count: int

    def __post_init__(self) -> None:
        if self.shift_period <= 0 or self.burn_in_cycles <= self.shift_period:
            raise ValueError("burn-in must span more than one positive-length regime")
        if self.burn_in_cycles % self.shift_period:
            raise ValueError("burn-in must end exactly on a regime boundary")
        if self.cycles < self.burn_in_cycles:
            raise ValueError("environment cannot end before the activation boundary")
        if self.candidate_count <= 0:
            raise ValueError("candidate_count must be positive")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PhaseEnvironment:
        return cls(
            shift_period=int(value["shift_period"]),
            burn_in_cycles=int(value["burn_in_cycles"]),
            cycles=int(value["cycles"]),
            candidate_count=int(value["candidate_count"]),
        )


@dataclass(frozen=True, slots=True)
class DelayedPhaseConfig:
    name: str
    canonical_endogenous_config: str
    feedback_strength: float
    knowledge_tolerance: float
    success_tolerance: float
    state_features: tuple[str, ...]
    standard: PhaseEnvironment
    timing_transfer: PhaseEnvironment
    holdout: PhaseEnvironment
    equivalence_seeds: tuple[int, ...]
    discovery_seeds: tuple[int, ...]
    replication_seeds: tuple[int, ...]
    timing_transfer_seeds: tuple[int, ...]
    holdout_seeds: tuple[int, ...]
    minimum_positive_signs: int
    minimum_negative_signs: int
    minimum_loo_balanced_accuracy: float
    minimum_loo_accuracy: float
    minimum_abs_spearman: float
    maximum_familywise_p: float
    minimum_validation_accuracy: float
    minimum_validation_balanced_accuracy: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DelayedPhaseConfig:
        selection = value["selection"]
        validation = value["validation"]
        assert isinstance(selection, Mapping) and isinstance(validation, Mapping)
        raw_features = value["state_features"]
        assert isinstance(raw_features, Sequence) and not isinstance(raw_features, str)
        config = cls(
            name=str(value["name"]),
            canonical_endogenous_config=str(value["canonical_endogenous_config"]),
            feedback_strength=float(value["feedback_strength"]),
            knowledge_tolerance=float(value["knowledge_tolerance"]),
            success_tolerance=float(value["success_tolerance"]),
            state_features=tuple(str(item) for item in raw_features),
            standard=PhaseEnvironment.from_mapping(value["standard"]),  # type: ignore[arg-type]
            timing_transfer=PhaseEnvironment.from_mapping(value["timing_transfer"]),  # type: ignore[arg-type]
            holdout=PhaseEnvironment.from_mapping(value["holdout"]),  # type: ignore[arg-type]
            equivalence_seeds=tuple(int(item) for item in value["equivalence_seeds"]),
            discovery_seeds=tuple(int(item) for item in value["discovery_seeds"]),
            replication_seeds=tuple(int(item) for item in value["replication_seeds"]),
            timing_transfer_seeds=tuple(int(item) for item in value["timing_transfer_seeds"]),
            holdout_seeds=tuple(int(item) for item in value["holdout_seeds"]),
            minimum_positive_signs=int(value["minimum_positive_signs"]),
            minimum_negative_signs=int(value["minimum_negative_signs"]),
            minimum_loo_balanced_accuracy=float(selection["minimum_loo_balanced_accuracy"]),
            minimum_loo_accuracy=float(selection["minimum_loo_accuracy"]),
            minimum_abs_spearman=float(selection["minimum_abs_spearman"]),
            maximum_familywise_p=float(selection["maximum_familywise_p"]),
            minimum_validation_accuracy=float(validation["minimum_accuracy"]),
            minimum_validation_balanced_accuracy=float(validation["minimum_balanced_accuracy"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("name is required")
        if self.feedback_strength != 0.5:
            raise ValueError("feedback strength is frozen at 0.5")
        if self.state_features != _FROZEN_FEATURES:
            raise ValueError("state feature vector is frozen")
        if self.standard != PhaseEnvironment(18, 36, 108, 7):
            raise ValueError("standard delayed-onset environment is frozen")
        if self.timing_transfer != PhaseEnvironment(18, 54, 126, 7):
            raise ValueError("timing-transfer environment is frozen")
        if self.holdout != PhaseEnvironment(15, 30, 90, 7):
            raise ValueError("holdout environment is frozen")
        seed_groups = (
            self.equivalence_seeds,
            self.discovery_seeds,
            self.replication_seeds,
            self.timing_transfer_seeds,
            self.holdout_seeds,
        )
        if tuple(map(len, seed_groups)) != (4, 12, 8, 8, 8):
            raise ValueError("frozen cohort sizes changed")
        flattened = [seed for group in seed_groups for seed in group]
        if len(flattened) != len(set(flattened)):
            raise ValueError("seed cohorts must be disjoint")
        if self.minimum_positive_signs != 3 or self.minimum_negative_signs != 3:
            raise ValueError("sign-heterogeneity gate is frozen at 3/3")
        if min(self.knowledge_tolerance, self.success_tolerance) < 0:
            raise ValueError("tolerances must be non-negative")
        for value in (
            self.minimum_loo_balanced_accuracy,
            self.minimum_loo_accuracy,
            self.minimum_abs_spearman,
            self.maximum_familywise_p,
            self.minimum_validation_accuracy,
            self.minimum_validation_balanced_accuracy,
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError("selection and validation thresholds must be in [0, 1]")


def load_delayed_phase_config(path: str | Path) -> tuple[DelayedPhaseConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, Mapping):
        raise ValueError("delayed phase config must be a JSON object")
    config = DelayedPhaseConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


__all__ = ["DelayedPhaseConfig", "PhaseEnvironment", "load_delayed_phase_config"]
