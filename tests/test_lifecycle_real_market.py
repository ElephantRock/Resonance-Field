from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.rows import dict_row

from resonance.experiments.lifecycle_campaign import finite_arm, immortal_arm, run_succession_experiment
from resonance.experiments.lifecycle_config import LifecycleConfig
from resonance.experiments.phase_boundary_campaign import reference_policy
from resonance.experiments.runner import apply_migrations


@pytest.mark.integration
def test_lifecycle_succession_runs_through_real_market() -> None:
    dsn = os.getenv("RESONANCE_TEST_DSN")
    if not dsn:
        pytest.skip("RESONANCE_TEST_DSN is required")
    mapping = {
        "name": "lifecycle-real-market-test",
        "environment": {
            "agents": 6,
            "domains": ["a", "b", "c"],
            "cycles": 16,
            "cycle_seconds": 10,
            "shift_period": 8,
            "candidate_count": 3,
            "task_budget": 10,
            "bid_deadline_seconds": 6,
            "trace_half_life_cycles": 6.0,
            "initial_credits": 500,
            "base_success_probability": 0.38,
            "practice_gain": 0.14,
            "maximum_success_probability": 0.90,
            "confidence_base": 0.35,
            "confidence_evidence_weight": 0.35,
            "confidence_noise_weight": 0.20,
            "price_floor": 0.45,
            "price_span": 0.35,
            "completion_min_seconds": 2,
            "completion_span_seconds": 3,
        },
        "seeds": [11],
        "holdout_seeds": [99],
        "holdout_cycles": 18,
        "holdout_shift_period": 7,
        "holdout_candidate_count": 3,
        "success_tolerance": 0.02,
        "incumbent_tolerance": 0.05,
        "economic_tolerance": 0.08,
        "lifecycle": {
            "expected_lifetime": 8,
            "short_lifetime": 4,
            "long_lifetime": 12,
            "holdout_lifetime": 9,
            "minimum_actor_incumbency_reduction": 0.0,
            "minimum_knowledge_retention": 0.0,
            "public_retrieval_k": 4,
            "public_success_gain": 0.04,
            "public_confidence_gain": 0.08,
            "advisory_success_gain": 0.03,
            "cultural_diversity_per_lineage": 1,
            "rapid_shift_period": 4,
            "replication_seeds": [55],
        },
    }
    config = LifecycleConfig.from_mapping(mapping)
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as connection:
        apply_migrations(connection)
        arms = run_succession_experiment(
            connection,
            config=config,
            config_hash="lifecycle-real-market-config",
            code_sha="lifecycle-real-market-sha",
            number=63,
            seeds=[11],
            arms=[
                immortal_arm("immortal", policy=reference_policy(), env=config.integration.environment),
                finite_arm(
                    "finite",
                    policy=reference_policy(),
                    env=config.integration.environment,
                    lifetime=8,
                    disposition="retire",
                ),
            ],
        )
        finite = next(arm for arm in arms if arm["label"] == "finite")
        assert finite["metrics"]["turnover_events"] > 0
        assert finite["metrics"]["max_generation"] >= 1
        assert all(finite["invariants"].values())
        event_count = connection.execute("SELECT COUNT(*) AS n FROM succession_events").fetchone()
        assert event_count is not None and int(event_count["n"]) > 0
        retired = connection.execute(
            """
            SELECT DISTINCT a.status, c.balance
            FROM succession_events s
            JOIN agents a ON a.agent_id = s.old_agent_id
            JOIN compute_accounts c ON c.owner_agent_id = s.old_agent_id
            """
        ).fetchall()
        assert retired
        assert all(row["status"] == "retired" and int(row["balance"]) == 0 for row in retired)
        successors = connection.execute(
            """
            SELECT DISTINCT a.generation
            FROM succession_events s
            JOIN agents a ON a.agent_id = s.new_agent_id
            """
        ).fetchall()
        assert successors and all(int(row["generation"]) >= 1 for row in successors)
