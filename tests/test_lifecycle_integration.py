from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.rows import dict_row

from resonance.experiments.integration_campaign import (
    IntegrationCampaignConfig,
    IntegrationEnvironment,
    ReputationPolicy,
)
from resonance.experiments.lifecycle_campaign import (
    LifecycleArmSpec,
    LifecycleSpec,
    run_lifecycle_arm,
)
from resonance.experiments.runner import apply_migrations

pytestmark = pytest.mark.integration


def test_fixed_exit_replaces_agents_and_preserves_market_invariants() -> None:
    dsn = os.getenv("RESONANCE_TEST_DSN")
    if not dsn:
        pytest.skip("RESONANCE_TEST_DSN is required")

    env = IntegrationEnvironment(
        agents=6,
        domains=("a", "b", "c"),
        cycles=12,
        cycle_seconds=10,
        shift_period=6,
        candidate_count=3,
        task_budget=10,
        bid_deadline_seconds=6,
        trace_half_life_cycles=6.0,
        initial_credits=300,
        base_success_probability=0.38,
        practice_gain=0.14,
        maximum_success_probability=0.90,
        confidence_base=0.35,
        confidence_evidence_weight=0.35,
        confidence_noise_weight=0.20,
        price_floor=0.45,
        price_span=0.35,
        completion_min_seconds=2,
        completion_span_seconds=3,
    )
    config = IntegrationCampaignConfig(
        name="lifecycle-integration-test",
        environment=env,
        seeds=(101,),
        holdout_seeds=(707,),
        holdout_cycles=12,
        holdout_shift_period=6,
        holdout_candidate_count=3,
        success_tolerance=0.015,
        incumbent_tolerance=0.05,
        economic_tolerance=0.08,
    )
    arm = LifecycleArmSpec(
        label="fixed_exit",
        policy=ReputationPolicy(),
        environment=env,
        lifecycle=LifecycleSpec(mode="fixed", lifetime_cycles=4),
        public_trace_confidence_weight=0.10,
        retrieval_top_k=3,
        diversified_lineages=2,
        knowledge_signal_threshold=0.20,
    )

    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as connection:
        apply_migrations(connection)
        result = run_lifecycle_arm(
            connection,
            config=config,
            config_hash="integration-test",
            experiment_number=63,
            arm=arm,
            seed=101,
            code_sha="integration-test",
        )
        assert all(bool(value) for value in result["invariants"].values())
        assert result["metrics"]["exit_count"] > 0
        assert result["metrics"]["max_generation"] >= 1

        event_count = connection.execute(
            "SELECT COUNT(*) AS count FROM lifecycle_events WHERE run_id = %s",
            (result["run_id"],),
        ).fetchone()
        assert event_count is not None
        assert int(event_count["count"]) == int(result["metrics"]["exit_count"])

        generations = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM agents
            WHERE generation > 0
            """
        ).fetchone()
        assert generations is not None
        assert int(generations["count"]) > 0
