from __future__ import annotations

import inspect
from pathlib import Path

from resonance.experiments.epistemic_substrate_campaign import (
    _bridge_triples,
    generate_world,
    run_world,
)
from resonance.experiments.epistemic_substrate_config import load_epistemic_substrate_config


CONFIG_PATH = Path("configs/experiments/epistemic-substrate-138-141.json")


def _config():
    config, _digest = load_epistemic_substrate_config(CONFIG_PATH)
    return config


def test_world_generation_is_deterministic_and_collective_required() -> None:
    config = _config()
    first = generate_world(config.instrumentation_seeds[0], config)
    second = generate_world(config.instrumentation_seeds[0], config)

    assert first == second
    assert len(first.claims) == config.relation_count
    assert len(first.reports) == config.agent_count
    assert all(len(report) == config.observations_per_agent for report in first.reports)

    for query in first.transfer_queries:
        assert all(
            not set(query.path).issubset({claim.triple for claim in report})
            for report in first.reports
        )
        producers = {
            claim.producer_id
            for triple in query.path
            for claim in first.claims
            if claim.triple == triple
        }
        assert len(producers) >= 2


def test_bridge_salience_is_query_independent_by_api() -> None:
    assert tuple(inspect.signature(_bridge_triples).parameters) == ("claims",)


def test_instrumentation_cohort_satisfies_hard_quality_gates() -> None:
    config = _config()
    expected_arms = [arm for _experiment, arm in sorted(config.experiments)]

    for seed in config.instrumentation_seeds:
        metrics = run_world(seed, config)
        assert [result.arm for result in metrics] == expected_arms
        for result in metrics:
            assert result.evidence_coverage == 1.0
            assert result.knowledge_survival_rate == 1.0
            assert result.false_synthesis_rate <= config.maximum_false_synthesis_rate
            assert 0.0 <= result.transfer_accuracy <= 1.0
            assert 0.0 <= result.collective_emergence_ratio <= 1.0
        for result in metrics[2:]:
            provenance_loss = 1.0 - result.provenance_completeness
            assert provenance_loss <= config.maximum_provenance_loss_graph_arms
