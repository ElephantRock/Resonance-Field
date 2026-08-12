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
EXPECTED_ARMS = {
    "pile": {
        "persistent_reports": True,
        "cross_agent_reads_during_discovery": False,
        "relational_edges": False,
        "provenance": False,
        "activation_dynamics": False,
    },
    "shared_memory": {
        "persistent_reports": True,
        "cross_agent_reads_during_discovery": True,
        "relational_edges": False,
        "provenance": True,
        "activation_dynamics": False,
    },
    "provenance_graph": {
        "persistent_reports": True,
        "cross_agent_reads_during_discovery": True,
        "relational_edges": True,
        "provenance": True,
        "activation_dynamics": False,
    },
    "resonance_field": {
        "persistent_reports": True,
        "cross_agent_reads_during_discovery": True,
        "relational_edges": True,
        "provenance": True,
        "activation_dynamics": True,
    },
}
EXPECTED_EVIDENCE_REGIMES = {
    "fast_change": 8,
    "slow_change": 8,
    "recent_rumor": 8,
    "stable_confirmation": 24,
}
EXPECTED_RESONANCE = {
    "initial_activation": 1.0,
    "decay_factor_per_epoch": 0.97,
    "independent_confirmation_gain": 0.25,
    "contradiction_gain": 0.10,
    "bridge_gain": 0.20,
    "maximum_activation": 3.0,
    "contradiction_override_margin": 0.60,
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


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class EpistemicSubstrateConfig:
    name: str
    experiments: tuple[tuple[str, str], ...]
    benchmark_mode: str
    entity_count: int
    relation_count: int
    relation_count_semantics: str
    relation_type_count: int
    source_packet_count: int
    agent_count: int
    observations_per_agent: int
    discovery_query_count: int
    transfer_query_count: int
    transfer_path_hops: tuple[int, ...]
    final_epoch: int
    evidence_regimes_canonical: str
    producer_memory_destroyed_before_transfer: bool
    max_substrate_writes_per_agent: int
    max_retrieval_items_per_query: int
    pile_claim_cost: int
    shared_claim_cost: int
    graph_claim_cost: int
    max_graph_hops_per_query: int
    max_reasoning_steps_per_query: int
    arms_canonical: str
    resonance_canonical: str
    contradiction_override_margin: float
    primary_endpoints: tuple[str, ...]
    confirmatory_contrasts: tuple[tuple[str, str], ...]
    paired_by_world_seed: bool
    multiple_testing: str
    alpha: float
    confidence_interval: float
    bootstrap_resamples: int
    minimum_total_effect_transfer_accuracy: float
    minimum_total_effect_collective_emergence_ratio: float
    identical_worlds_required: bool
    identical_observations_required: bool
    identical_queries_required: bool
    identical_budgets_required: bool
    no_cross_arm_leakage_required: bool
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
        arms = _mapping(value["arms"], "arms")
        resonance = _mapping(value["resonance"], "resonance")
        evidence_regimes = _mapping(benchmark["evidence_regimes"], "evidence_regimes")

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
            benchmark_mode=str(benchmark["mode"]),
            entity_count=int(benchmark["entity_count"]),
            relation_count=int(benchmark["relation_count"]),
            relation_count_semantics=str(benchmark["relation_count_semantics"]),
            relation_type_count=int(benchmark["relation_type_count"]),
            source_packet_count=int(benchmark["source_packet_count"]),
            agent_count=int(benchmark["agent_count"]),
            observations_per_agent=int(benchmark["observations_per_agent"]),
            discovery_query_count=int(benchmark["discovery_query_count"]),
            transfer_query_count=int(benchmark["transfer_query_count"]),
            transfer_path_hops=_int_tuple(benchmark["transfer_path_hops"], "transfer_path_hops"),
            final_epoch=int(benchmark["final_epoch"]),
            evidence_regimes_canonical=_canonical(evidence_regimes),
            producer_memory_destroyed_before_transfer=bool(
                benchmark["producer_memory_destroyed_before_transfer"]
            ),
            max_substrate_writes_per_agent=int(budget["max_substrate_writes_per_agent"]),
            max_retrieval_items_per_query=int(budget["max_retrieval_items_per_query"]),
            pile_claim_cost=int(budget["pile_claim_cost"]),
            shared_claim_cost=int(budget["shared_claim_cost"]),
            graph_claim_cost=int(budget["graph_claim_cost"]),
            max_graph_hops_per_query=int(budget["max_graph_hops_per_query"]),
            max_reasoning_steps_per_query=int(budget["max_reasoning_steps_per_query"]),
            arms_canonical=_canonical(arms),
            resonance_canonical=_canonical(resonance),
            contradiction_override_margin=float(resonance["contradiction_override_margin"]),
            primary_endpoints=tuple(str(item) for item in raw_endpoints),
            confirmatory_contrasts=tuple(contrasts),
            paired_by_world_seed=bool(analysis["paired_by_world_seed"]),
            multiple_testing=str(analysis["multiple_testing"]),
            alpha=float(analysis["alpha"]),
            confidence_interval=float(analysis["confidence_interval"]),
            bootstrap_resamples=int(analysis["bootstrap_resamples"]),
            minimum_total_effect_transfer_accuracy=float(
                analysis["minimum_total_effect_transfer_accuracy"]
            ),
            minimum_total_effect_collective_emergence_ratio=float(
                analysis["minimum_total_effect_collective_emergence_ratio"]
            ),
            identical_worlds_required=bool(gates["require_identical_worlds_across_arms"]),
            identical_observations_required=bool(
                gates["require_identical_agent_observations_across_arms"]
            ),
            identical_queries_required=bool(gates["require_identical_query_sets_across_arms"]),
            identical_budgets_required=bool(gates["require_identical_budgets_across_arms"]),
            no_cross_arm_leakage_required=bool(gates["require_no_cross_arm_state_leakage"]),
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
        if self.arms_canonical != _canonical(EXPECTED_ARMS):
            raise ValueError("substrate arm semantics changed")
        if self.evidence_regimes_canonical != _canonical(EXPECTED_EVIDENCE_REGIMES):
            raise ValueError("evidence regime mixture changed")
        if self.resonance_canonical != _canonical(EXPECTED_RESONANCE):
            raise ValueError("resonance dynamics changed")
        if self.benchmark_mode != "deterministic_relational_world":
            raise ValueError("benchmark mode changed")
        if self.relation_count_semantics != "observation_claims":
            raise ValueError("relation count semantics changed")
        if (
            self.entity_count,
            self.relation_count,
            self.relation_type_count,
            self.source_packet_count,
            self.agent_count,
            self.observations_per_agent,
            self.final_epoch,
        ) != (96, 192, 4, 64, 32, 6, 40):
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
            self.pile_claim_cost,
            self.shared_claim_cost,
            self.graph_claim_cost,
            self.max_graph_hops_per_query,
            self.max_reasoning_steps_per_query,
        ) != (6, 12, 3, 1, 1, 4, 8):
            raise ValueError("cross-arm budget or representation costs changed")
        if self.contradiction_override_margin != 0.60:
            raise ValueError("contradiction override margin changed")
        if self.primary_endpoints != EXPECTED_PRIMARY_ENDPOINTS:
            raise ValueError("primary endpoints changed")
        if self.confirmatory_contrasts != EXPECTED_CONFIRMATORY_CONTRASTS:
            raise ValueError("confirmatory contrast set changed")
        if (
            not self.paired_by_world_seed
            or self.multiple_testing != "holm"
            or self.alpha != 0.05
            or self.confidence_interval != 0.95
            or self.bootstrap_resamples != 10000
        ):
            raise ValueError("confirmatory analysis settings changed")
        if (
            self.minimum_total_effect_transfer_accuracy,
            self.minimum_total_effect_collective_emergence_ratio,
        ) != (0.10, 0.10):
            raise ValueError("minimum total-effect gates changed")
        if not all(
            (
                self.identical_worlds_required,
                self.identical_observations_required,
                self.identical_queries_required,
                self.identical_budgets_required,
                self.no_cross_arm_leakage_required,
            )
        ):
            raise ValueError("cross-arm identity gates changed")
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
