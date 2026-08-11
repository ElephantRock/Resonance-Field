"""Configuration for Auction Margin Control Experiments 129–134."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MarginEnvironment:
    cycles: int
    shift_period: int
    candidate_count: int
    activation_cycle: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> MarginEnvironment:
        return cls(
            cycles=int(value["cycles"]),
            shift_period=int(value["shift_period"]),
            candidate_count=int(value["candidate_count"]),
            activation_cycle=int(value["activation_cycle"]),
        )

    def validate(self) -> None:
        if self.cycles <= self.activation_cycle or self.shift_period <= 0:
            raise ValueError("invalid auction-margin environment horizon")
        if self.activation_cycle % self.shift_period:
            raise ValueError("activation must be on a regime boundary")
        if self.candidate_count <= 1:
            raise ValueError("auction-margin environment needs at least two candidates")


@dataclass(frozen=True, slots=True)
class AuctionMarginConfig:
    name: str
    canonical_endogenous_config: str
    feedback_strength: float
    near_radius: float
    buffered_radius: float
    probe_epsilon: float
    delta_micro: float
    delta_meso: float
    delta_macro: float
    persistent_hits: int
    persistent_window: int
    minimum_macro_crossing_share: float
    minimum_basin_disagreement_share: float
    minimum_bounded_share: float
    maximum_success_loss: float
    maximum_knowledge_loss: float
    standard: MarginEnvironment
    timing_transfer: MarginEnvironment
    holdout: MarginEnvironment
    instrumentation_seeds: tuple[int, ...]
    discovery_seeds: tuple[int, ...]
    timing_transfer_seeds: tuple[int, ...]
    replication_seeds: tuple[int, ...]
    holdout_seeds: tuple[int, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> AuctionMarginConfig:
        thresholds = value["distance_thresholds"]
        gates = value["propagation_gates"]
        assert isinstance(thresholds, Mapping) and isinstance(gates, Mapping)
        config = cls(
            name=str(value["name"]),
            canonical_endogenous_config=str(value["canonical_endogenous_config"]),
            feedback_strength=float(value["feedback_strength"]),
            near_radius=float(value["near_radius"]),
            buffered_radius=float(value["buffered_radius"]),
            probe_epsilon=float(value["probe_epsilon"]),
            delta_micro=float(thresholds["micro"]),
            delta_meso=float(thresholds["meso"]),
            delta_macro=float(thresholds["macro"]),
            persistent_hits=int(thresholds["persistent_hits"]),
            persistent_window=int(thresholds["persistent_window"]),
            minimum_macro_crossing_share=float(gates["minimum_macro_crossing_share"]),
            minimum_basin_disagreement_share=float(gates["minimum_basin_disagreement_share"]),
            minimum_bounded_share=float(gates["minimum_bounded_share"]),
            maximum_success_loss=float(gates["maximum_success_loss"]),
            maximum_knowledge_loss=float(gates["maximum_knowledge_loss"]),
            standard=MarginEnvironment.from_mapping(value["standard"]),  # type: ignore[arg-type]
            timing_transfer=MarginEnvironment.from_mapping(value["timing_transfer"]),  # type: ignore[arg-type]
            holdout=MarginEnvironment.from_mapping(value["holdout"]),  # type: ignore[arg-type]
            instrumentation_seeds=tuple(int(x) for x in value["instrumentation_seeds"]),
            discovery_seeds=tuple(int(x) for x in value["discovery_seeds"]),
            timing_transfer_seeds=tuple(int(x) for x in value["timing_transfer_seeds"]),
            replication_seeds=tuple(int(x) for x in value["replication_seeds"]),
            holdout_seeds=tuple(int(x) for x in value["holdout_seeds"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.feedback_strength != 0.5:
            raise ValueError("feedback strength is frozen at 0.5")
        if (self.near_radius, self.buffered_radius, self.probe_epsilon) != (0.01, 1.0, 0.1):
            raise ValueError("auction-margin radius/probe controls changed")
        if (self.delta_micro, self.delta_meso, self.delta_macro) != (0.10, 0.10, 0.05):
            raise ValueError("auction-margin distance thresholds changed")
        if (self.persistent_hits, self.persistent_window) != (3, 5):
            raise ValueError("persistent crossing rule changed")
        if (
            self.minimum_macro_crossing_share,
            self.minimum_basin_disagreement_share,
            self.minimum_bounded_share,
            self.maximum_success_loss,
            self.maximum_knowledge_loss,
        ) != (0.40, 0.30, 0.75, 0.015, 0.10):
            raise ValueError("auction-margin propagation gates changed")
        expected = (
            MarginEnvironment(126, 18, 7, 36),
            MarginEnvironment(144, 18, 7, 54),
            MarginEnvironment(120, 15, 7, 30),
        )
        observed = (self.standard, self.timing_transfer, self.holdout)
        if observed != expected:
            raise ValueError("auction-margin environments changed")
        for env in observed:
            env.validate()
        groups = (
            self.instrumentation_seeds,
            self.discovery_seeds,
            self.timing_transfer_seeds,
            self.replication_seeds,
            self.holdout_seeds,
        )
        if tuple(map(len, groups)) != (4, 12, 8, 8, 8):
            raise ValueError("auction-margin cohort sizes changed")
        flat = [seed for group in groups for seed in group]
        if len(flat) != len(set(flat)):
            raise ValueError("auction-margin seed cohorts must be disjoint")


def load_auction_margin_config(path: str | Path) -> tuple[AuctionMarginConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, Mapping):
        raise ValueError("auction-margin config must be a JSON object")
    config = AuctionMarginConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


__all__ = ["AuctionMarginConfig", "MarginEnvironment", "load_auction_margin_config"]
