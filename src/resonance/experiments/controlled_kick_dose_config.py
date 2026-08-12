"""Frozen configuration for Controlled Kick-Dose Experiments 135–137."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class InstrumentationCell:
    seed: int
    dose: int
    kick_cycles: tuple[int, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> InstrumentationCell:
        return cls(
            seed=int(value["seed"]),
            dose=int(value["dose"]),
            kick_cycles=tuple(int(x) for x in value["kick_cycles"]),
        )


@dataclass(frozen=True, slots=True)
class KickDoseConfig:
    name: str
    canonical_endogenous_config: str
    canonical_auction_margin_config: str
    feedback_strength: float
    target_radius: float
    probe_epsilon: float
    cycles: int
    shift_period: int
    candidate_count: int
    activation_cycle: int
    burst_cycles: tuple[int, ...]
    landmark_cycle: int
    gap_cycles: tuple[int, int]
    mediator_cycles: tuple[int, int]
    macro_threshold: float
    persistent_hits: int
    persistent_window: int
    censor_duration: int
    maximum_success_loss: float
    maximum_knowledge_loss: float
    minimum_attenuation: float
    alpha: float
    doses: tuple[int, ...]
    instrumentation: tuple[InstrumentationCell, ...]
    discovery_seeds: tuple[int, ...]
    replication_seeds: tuple[int, ...]
    timing_sequences: Mapping[int, tuple[tuple[int, ...], ...]]
    k4_zero_within_arm_timing_variance: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> KickDoseConfig:
        environment = value["environment"]
        recovery = value["recovery"]
        quality = value["quality_gates"]
        mediation = value["mediation"]
        timing = value["timing_sequences"]
        limitations = value["accepted_limitations"]
        assert isinstance(environment, Mapping)
        assert isinstance(recovery, Mapping)
        assert isinstance(quality, Mapping)
        assert isinstance(mediation, Mapping)
        assert isinstance(timing, Mapping)
        assert isinstance(limitations, Mapping)
        timing_sequences = {
            int(dose): tuple(tuple(int(cycle) for cycle in schedule) for schedule in schedules)
            for dose, schedules in timing.items()
        }
        config = cls(
            name=str(value["name"]),
            canonical_endogenous_config=str(value["canonical_endogenous_config"]),
            canonical_auction_margin_config=str(value["canonical_auction_margin_config"]),
            feedback_strength=float(value["feedback_strength"]),
            target_radius=float(value["target_radius"]),
            probe_epsilon=float(value["probe_epsilon"]),
            cycles=int(environment["cycles"]),
            shift_period=int(environment["shift_period"]),
            candidate_count=int(environment["candidate_count"]),
            activation_cycle=int(environment["activation_cycle"]),
            burst_cycles=tuple(int(x) for x in environment["burst_cycles"]),
            landmark_cycle=int(environment["landmark_cycle"]),
            gap_cycles=tuple(int(x) for x in environment["gap_cycles"]),  # type: ignore[arg-type]
            mediator_cycles=tuple(int(x) for x in environment["mediator_cycles"]),  # type: ignore[arg-type]
            macro_threshold=float(recovery["macro_threshold"]),
            persistent_hits=int(recovery["persistent_hits"]),
            persistent_window=int(recovery["persistent_window"]),
            censor_duration=int(recovery["censor_duration"]),
            maximum_success_loss=float(quality["maximum_success_loss"]),
            maximum_knowledge_loss=float(quality["maximum_knowledge_loss"]),
            minimum_attenuation=float(mediation["minimum_attenuation"]),
            alpha=float(mediation["alpha"]),
            doses=tuple(int(x) for x in value["doses"]),
            instrumentation=tuple(
                InstrumentationCell.from_mapping(item) for item in value["instrumentation"]
            ),
            discovery_seeds=tuple(int(x) for x in value["discovery_seeds"]),
            replication_seeds=tuple(int(x) for x in value["replication_seeds"]),
            timing_sequences=timing_sequences,
            k4_zero_within_arm_timing_variance=bool(
                limitations["k4_zero_within_arm_timing_variance"]
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.feedback_strength != 0.5:
            raise ValueError("feedback strength is frozen at 0.5")
        if (self.target_radius, self.probe_epsilon) != (0.01, 0.1):
            raise ValueError("validated auction-margin controls changed")
        if (
            self.cycles,
            self.shift_period,
            self.candidate_count,
            self.activation_cycle,
            self.burst_cycles,
            self.landmark_cycle,
            self.gap_cycles,
            self.mediator_cycles,
        ) != (234, 18, 7, 36, (36, 37, 38, 39), 54, (40, 53), (54, 71)):
            raise ValueError("controlled-kick environment changed")
        if (self.macro_threshold, self.persistent_hits, self.persistent_window) != (0.05, 3, 5):
            raise ValueError("recovery definition changed")
        if self.censor_duration != 180:
            raise ValueError("recovery censoring horizon changed")
        if (self.maximum_success_loss, self.maximum_knowledge_loss) != (0.015, 0.10):
            raise ValueError("quality gates changed")
        if (self.minimum_attenuation, self.alpha) != (0.20, 0.05):
            raise ValueError("mediation gates changed")
        if self.doses != (1, 2, 4):
            raise ValueError("kick doses changed")
        expected_instrumentation = (
            InstrumentationCell(2891, 1, (36,)),
            InstrumentationCell(2892, 2, (36, 39)),
            InstrumentationCell(2893, 4, (36, 37, 38, 39)),
            InstrumentationCell(2894, 1, (39,)),
            InstrumentationCell(2895, 2, (37, 38)),
            InstrumentationCell(2896, 4, (36, 37, 38, 39)),
        )
        if self.instrumentation != expected_instrumentation:
            raise ValueError("Experiment 135 schedule changed")
        if self.discovery_seeds != tuple(range(2901, 2937)):
            raise ValueError("Experiment 136 seeds changed")
        if self.replication_seeds != tuple(range(3001, 3037)):
            raise ValueError("Experiment 137 seeds changed")
        expected_timing = {
            1: ((36,), (37,), (38,), (39,)),
            2: ((36, 37), (36, 38), (36, 39), (37, 38), (37, 39), (38, 39)),
            4: ((36, 37, 38, 39),),
        }
        if dict(self.timing_sequences) != expected_timing:
            raise ValueError("inferential timing balance changed")
        if not self.k4_zero_within_arm_timing_variance:
            raise ValueError("accepted K=4 timing-dispersion limitation must remain recorded")
        if any(len(cell.kick_cycles) != cell.dose for cell in self.instrumentation):
            raise ValueError("instrumentation kick count must equal dose")
        if any(
            cycle not in self.burst_cycles
            for cell in self.instrumentation
            for cycle in cell.kick_cycles
        ):
            raise ValueError("instrumentation kick outside frozen burst")


def load_controlled_kick_dose_config(path: str | Path) -> tuple[KickDoseConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, Mapping):
        raise ValueError("controlled-kick config must be a JSON object")
    config = KickDoseConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


__all__ = ["InstrumentationCell", "KickDoseConfig", "load_controlled_kick_dose_config"]
