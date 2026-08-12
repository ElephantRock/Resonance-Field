"""Frozen configuration for Epistemic Substrate Experiments 138–141."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


EXPECTED_EXPERIMENTS = {
    "138": "pile",
    "139": "shared_memory",
    "140": "provenance_graph",
    "141": "resonance_field",
}
EXPECTED_PRIMARY_ENDPOINTS = (
    "transfer_accuracy",
    "collective_emergence_ratio",
)
EXPECTED_CONFIRMATORY_CONTRASTS = (
    ("shared_memory", "pile"),
    ("provenance_graph", "shared_memory"),
    ("resonance_field", "provenance_graph"),
    ("resonance_field", "pile"),
)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _int_tuple(value: object, label: str) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be an array")
    return tuple(int(item) for item in value)


@dataclass(frozen=True, slots=True)
class EpistemicSubstrateConfig:
    name: str
    experiments: tuple[tuple[str, str], ...]
    entity_count: int
    relation_count: int
    source_packet_count: int
    agent_count: int
    observations_per_agent: int
    discovery_query_count: int
    transfer_query_count: int
    transfer_path_hops: tuple[int, ...]
    producer_memory_destroyed_before_transfer: bool
    max_substrate_writes_per_agent: int
    max_retrieval_items_per_query: int
    max_graph_hops_per_query: int
    max_reasoning_steps_per_query: int
    primary_endpoints: tuple[str, ...]
    confirmatory_contrasts: tuple[tuple[str, str], ...]
    alpha: float
    bootstrap_resamples: int
    minimum_total_effect_transfer_accuracy: float
    minimum_total_effect_collective_emergence_ratio: float
    maximum_false_synthesis_rate: float
    maximum_provenance_loss_graph_arms: float
    instrumentation_seeds: tuple[int, ...]
    confirmatory_seeds: tuple[int, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> EpistemicSubstrateConfig:
        benchmark = _mapping(value["benchmark"], "benchmark")
        budget = _mapping(value["budget"], "budget")
        analysis = _mapping(value["analysis"], "analysis")
        gates = _mapping(value["quality_gates"], "quality_gates")
        experiments = _mapping(value["experiments"], "experiments")

        raw_contrasts = value["confirmatory_contrasts"]
        if not isinstance(raw_contrasts, Sequence) or isinstance(raw_contrasts, (str, bytes)):
            raise ValueError("confirmatory_contrasts must be an array")
        contrasts: list[tuple[str, str]] = []
        for item in raw_contrasts:
            if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) != 2:
                raise ValueError("each confirmatory contrast must contain two arm names")
            contrasts.append((str(item[0]), str(item[1])))

        raw_endpoints = value["primary_endpoints"]
        if not isinstance(raw_endpoints, Sequence) or isinstance(raw_endpoints, (str, bytes)):
            raise ValueError("primary_endpoints must be an array")

        config = cls(
            name=str(value["name"]),
            experiments=tuple((str(k), str(v)) for k, v in experiments.items()),
            entity_count=int(benchmark["entity_count"]),
            relation_count=int(benchmark["relation_count"]),
            source_packet_count=int(benchmark["source_packet_count"]),
            agent_count=int(benchmark["agent_count"]),
            observations_per_agent=int(benchmark["observations_per_agent"]),
            discovery_query_count=int(benchmark["discovery_query_count"]),
            transfer_query_count=int(benchmark["transfer_query_count"]),
            transfer_path_hops=_int_tuple(benchmark["transfer_path_hops"], "transfer_path_hops"),
            producer_memory_destroyed_before_transfer=bool(
                benchmark["producer_memory_destroyed_before_transfer"]
            ),
            max_substrate_writes_per_agent=int(budget["max_substrate_writes_per_agent"]),
            max_retrieval_items_per_query=int(budget["max_retrieval_items_per_query"]),
            max_graph_hops_per_query=int(budget["max_graph_hops_per_query"]),
            max_reasoning_steps_per_query=int(budget["max_reasoning_steps_per_query"]),
            primary_endpoints=tuple(str(item) for item in raw_endpoints),
            confirmatory_contrasts=tuple(contrasts),
            alpha=float(analysis["alpha"]),
            bootstrap_resamples=int(analysis["bootstrap_resamples"]),
            minimum_total_effect_transfer_accuracy=float(
                analysis["minimum_total_effect_transfer_accuracy"]
            ),
            minimum_total_effect_collective_emergence_ratio=float(
                analysis["minimum_total_effect_collective_emergence_ratio"]
            ),
            maximum_false_synthesis_rate=float(gates["maximum_false_synthesis_rate"]),
            maximum_provenance_loss_graph_arms=float(
                gates["maximum_provenance_loss_graph_arms"]
            ),
            instrumentation_seeds=_int_tuple(value["instrumentation_seeds"], "instrumentation_seeds"),
            confirmatory_seeds=_int_tuple(value["confirmatory_seeds"], "confirmatory_seeds"),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.name != "epistemic-substrate-138-141-v0.1":
            raise ValueError("epistemic-substrate campaign name changed")
        if dict(self.experiments) != EXPECTED_EXPERIMENTS:
            raise ValueError("experiment-to-arm assignment changed")
        if (
            self.entity_count,
            self.relation_count,
            self.source_packet_count,
            self.agent_count,
            self.observations_per_agent,
        ) != (96, 192, 64, 32, 6):
            raise ValueError("benchmark population or evidence geometry changed")
        if (self.discovery_query_count, self.transfer_query_count) != (24, 32):
            raise ValueError("query counts changed")
        if self.transfer_path_hops != (2, 3, 4):
            raise ValueError("transfer path-depth schedule changed")
        if not self.producer_memory_destroyed_before_transfer:
            raise ValueError("producer memory must be destroyed before transfer")
        if (
            self.max_substrate_writes_per_agent,
            self.max_retrieval_items_per_query,
            self.max_graph_hops_per_query,
            self.max_reasoning_steps_per_query,
        ) != (6, 12, 4, 8):
            raise ValueError("cross-arm budget changed")
        if self.primary_endpoints != EXPECTED_PRIMARY_ENDPOINTS:
            raise ValueError("primary endpoints changed")
        if self.confirmatory_contrasts != EXPECTED_CONFIRMATORY_CONTRASTS:
            raise ValueError("confirmatory contrast set changed")
        if self.alpha != 0.05 or self.bootstrap_resamples != 10000:
            raise ValueError("confirmatory analysis settings changed")
        if (
            self.minimum_total_effect_transfer_accuracy,
            self.minimum_total_effect_collective_emergence_ratio,
        ) != (0.10, 0.10):
            raise ValueError("minimum total-effect gates changed")
        if (self.maximum_false_synthesis_rate, self.maximum_provenance_loss_graph_arms) != (
            0.05,
            0.01,
        ):
            raise ValueError("quality gates changed")
        if len(self.instrumentation_seeds) != 8 or len(self.confirmatory_seeds) != 64:
            raise ValueError("cohort sizes changed")
        flat = self.instrumentation_seeds + self.confirmatory_seeds
        if len(flat) != len(set(flat)):
            raise ValueError("instrumentation and confirmatory seeds must be disjoint")


def load_epistemic_substrate_config(
    path: str | Path,
) -> tuple[EpistemicSubstrateConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, Mapping):
        raise ValueError("epistemic-substrate config must be a JSON object")
    config = EpistemicSubstrateConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


__all__ = ["EpistemicSubstrateConfig", "load_epistemic_substrate_config"]
