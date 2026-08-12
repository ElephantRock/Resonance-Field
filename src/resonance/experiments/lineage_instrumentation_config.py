"""Frozen configuration for Discrete Causal-Event Lineage Experiment 138."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_EVENT_CLASSES = (
    "auction_award",
    "settlement_transfer",
    "success_outcome",
    "practice_update",
    "trace_evidence_gate",
    "trace_retrieval_selection",
    "feedback_domain_choice",
    "public_knowledge_write",
)


@dataclass(frozen=True, slots=True)
class LineageConfig:
    name: str
    schema_version: str
    canonical_endogenous_config: str
    canonical_auction_margin_config: str
    feedback_strength: float
    target_radius: float
    probe_epsilon: float
    cycles: int
    shift_period: int
    candidate_count: int
    activation_cycle: int
    primary_window: tuple[int, int]
    calibration_seeds: tuple[int, ...]
    validation_seeds: tuple[int, ...]
    event_classes: tuple[str, ...]
    attribution_threshold: float
    single_parent_threshold: float
    maximum_corrective_revisions: int
    channel_edge_share_threshold: float
    channel_pair_prevalence: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> LineageConfig:
        environment = value["environment"]
        gates = value["gates"]
        future = value["future_channel_qualification"]
        assert isinstance(environment, Mapping)
        assert isinstance(gates, Mapping)
        assert isinstance(future, Mapping)
        config = cls(
            name=str(value["name"]),
            schema_version=str(value["schema_version"]),
            canonical_endogenous_config=str(value["canonical_endogenous_config"]),
            canonical_auction_margin_config=str(value["canonical_auction_margin_config"]),
            feedback_strength=float(value["feedback_strength"]),
            target_radius=float(value["target_radius"]),
            probe_epsilon=float(value["probe_epsilon"]),
            cycles=int(environment["cycles"]),
            shift_period=int(environment["shift_period"]),
            candidate_count=int(environment["candidate_count"]),
            activation_cycle=int(environment["activation_cycle"]),
            primary_window=tuple(int(x) for x in environment["primary_window"]),  # type: ignore[arg-type]
            calibration_seeds=tuple(int(x) for x in value["calibration_seeds"]),
            validation_seeds=tuple(int(x) for x in value["validation_seeds"]),
            event_classes=tuple(str(x) for x in value["event_classes"]),
            attribution_threshold=float(gates["attribution_threshold"]),
            single_parent_threshold=float(gates["single_parent_threshold"]),
            maximum_corrective_revisions=int(gates["maximum_corrective_revisions"]),
            channel_edge_share_threshold=float(future["edge_share_threshold"]),
            channel_pair_prevalence=int(future["minimum_pair_prevalence"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.schema_version != "v1":
            raise ValueError("initial Experiment 138 implementation must be schema v1")
        if (self.feedback_strength, self.target_radius, self.probe_epsilon) != (0.5, 0.01, 0.1):
            raise ValueError("validated causal-root controller changed")
        if (
            self.cycles,
            self.shift_period,
            self.candidate_count,
            self.activation_cycle,
            self.primary_window,
        ) != (90, 18, 7, 36, (36, 53)):
            raise ValueError("Experiment 138 environment or primary window changed")
        if self.calibration_seeds != tuple(range(3101, 3107)):
            raise ValueError("calibration seeds changed")
        if self.validation_seeds != tuple(range(3107, 3113)):
            raise ValueError("held-out validation seeds changed")
        if set(self.calibration_seeds) & set(self.validation_seeds):
            raise ValueError("calibration and validation seeds must be disjoint")
        if self.event_classes != _EVENT_CLASSES:
            raise ValueError("frozen eight-class event ontology changed")
        if (self.attribution_threshold, self.single_parent_threshold) != (0.90, 0.75):
            raise ValueError("lineage quality thresholds changed")
        if self.maximum_corrective_revisions != 2:
            raise ValueError("calibration revision budget changed")
        if (self.channel_edge_share_threshold, self.channel_pair_prevalence) != (0.25, 4):
            raise ValueError("future channel qualification thresholds changed")


def load_lineage_config(path: str | Path) -> tuple[LineageConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, Mapping):
        raise ValueError("Experiment 138 config must be a JSON object")
    config = LineageConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


__all__ = ["LineageConfig", "load_lineage_config"]
