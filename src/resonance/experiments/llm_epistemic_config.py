"""Frozen controls for Experiments 142–145 external-validity replication."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

EXPECTED_EXPERIMENTS = {
    "142": "pile",
    "143": "shared_memory",
    "144": "provenance_graph",
    "145": "resonance_field",
}
EXPECTED_CONTRASTS = (
    ("shared_memory", "pile"),
    ("provenance_graph", "shared_memory"),
    ("resonance_field", "provenance_graph"),
    ("resonance_field", "pile"),
)
EXPECTED_INSTRUMENTATION_CASE_COUNT = 24
EXPECTED_CONFIRMATORY_CASE_COUNT = 512


@dataclass(frozen=True, slots=True)
class LLMEpistemicConfig:
    name: str
    stage: str
    experiments: tuple[tuple[str, str], ...]
    instrumentation_case_count: int
    confirmatory_case_count: int
    confirmatory_cases_sealed: bool
    evaluator_draws: int
    primary_endpoint: str
    planned_contrasts: tuple[tuple[str, str], ...]
    minimum_total_effect: float
    minimum_incremental_effect: float

    def validate(self) -> None:
        if self.name != "llm-epistemic-substrate-142-145-v0.1":
            raise ValueError("campaign name changed")
        if self.stage != "instrumentation_scaffold":
            raise ValueError("campaign stage changed before seal")
        if dict(self.experiments) != EXPECTED_EXPERIMENTS:
            raise ValueError("experiment-to-arm assignment changed")
        expected_counts = (EXPECTED_INSTRUMENTATION_CASE_COUNT, EXPECTED_CONFIRMATORY_CASE_COUNT)
        if (self.instrumentation_case_count, self.confirmatory_case_count) != expected_counts:
            raise ValueError("case cohort sizes changed outside the frozen protocol revision")
        if self.confirmatory_cases_sealed:
            raise ValueError("confirmatory cases must remain unsealed during scaffold stage")
        if self.evaluator_draws != 5:
            raise ValueError("evaluator draw count changed")
        if self.primary_endpoint != "post_agent_task_accuracy":
            raise ValueError("primary endpoint changed")
        if self.planned_contrasts != EXPECTED_CONTRASTS:
            raise ValueError("planned contrasts changed")
        if (self.minimum_total_effect, self.minimum_incremental_effect) != (0.08, 0.03):
            raise ValueError("minimum effect gates changed")


def load_llm_epistemic_config(path: str | Path) -> LLMEpistemicConfig:
    value = json.loads(Path(path).read_text())
    corpus = value["corpus"]
    agents = value["agents"]
    analysis = value["analysis"]
    config = LLMEpistemicConfig(
        name=str(value["name"]),
        stage=str(value["stage"]),
        experiments=tuple((str(k), str(v)) for k, v in value["experiments"].items()),
        instrumentation_case_count=int(corpus["instrumentation_case_count"]),
        confirmatory_case_count=int(corpus["confirmatory_case_count"]),
        confirmatory_cases_sealed=bool(corpus["confirmatory_cases_sealed"]),
        evaluator_draws=int(agents["independent_evaluator_draws_per_case_arm"]),
        primary_endpoint=str(value["primary_endpoint"]),
        planned_contrasts=tuple(tuple(str(x) for x in item) for item in value["planned_contrasts"]),
        minimum_total_effect=float(analysis["minimum_total_effect_r_minus_p"]),
        minimum_incremental_effect=float(analysis["minimum_incremental_effect_r_minus_g"]),
    )
    config.validate()
    return config


__all__ = [
    "EXPECTED_CONFIRMATORY_CASE_COUNT",
    "EXPECTED_INSTRUMENTATION_CASE_COUNT",
    "LLMEpistemicConfig",
    "load_llm_epistemic_config",
]
