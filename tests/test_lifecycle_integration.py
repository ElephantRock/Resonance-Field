from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from resonance.economy import PostgresEconomyRepository
from resonance.experiments import lifecycle_campaign
from resonance.experiments.integration_campaign import (
    IntegrationCampaignConfig,
    IntegrationEnvironment,
    ReputationPolicy,
)
from resonance.experiments.lifecycle_campaign import LifecycleArmSpec, LifecycleSpec
from resonance.experiments.lifecycle_corrections import install_lifecycle_corrections
from resonance.experiments.lifecycle_retrieval import (
    install_diversified_retrieval_fix,
    selected_public_trace_stats,
)
from resonance.experiments.runner import apply_migrations
from resonance.substrate.models import Trace
from resonance.substrate.postgres import PostgresTraceRepository

pytestmark = pytest.mark.integration


@contextmanager
def _fresh_database(dsn: str):
    """Give each lifecycle integration regression an independently migrated database."""
    params = conninfo_to_dict(dsn)
    database_name = f"lifecycle_test_{uuid4().hex}"
    admin_dsn = make_conninfo(**{**params, "dbname": "postgres"})
    test_dsn = make_conninfo(**{**params, "dbname": database_name})
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        with psycopg.connect(test_dsn, autocommit=True, row_factory=dict_row) as connection:
            apply_migrations(connection)
            yield connection
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


def _environment() -> IntegrationEnvironment:
    return IntegrationEnvironment(
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


def test_fixed_exit_replaces_agents_and_preserves_market_invariants() -> None:
    dsn = os.getenv("RESONANCE_TEST_DSN")
    if not dsn:
        pytest.skip("RESONANCE_TEST_DSN is required")

    install_lifecycle_corrections()
    install_diversified_retrieval_fix()
    env = _environment()
    config = IntegrationCampaignConfig(
        name="lifecycle-integration-test-corrected",
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

    with _fresh_database(dsn) as connection:
        result = lifecycle_campaign.run_lifecycle_arm(
            connection,
            config=config,
            config_hash="integration-test-corrected",
            experiment_number=63,
            arm=arm,
            seed=101,
            code_sha="integration-test-corrected",
        )
        assert all(bool(value) for value in result["invariants"].values())
        assert result["invariants"]["succession_balance_preserved"] is True
        assert result["invariants"]["cell_trace_isolated"] is True
        assert result["metrics"]["exit_count"] > 0
        assert result["metrics"]["max_generation"] >= 1
        assert result["metrics"]["foreign_trace_retrieval_share"] == 0.0

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
            """,
        ).fetchone()
        assert generations is not None
        assert int(generations["count"]) > 0


def test_public_trace_retrieval_is_isolated_and_diversity_metrics_match_selected_set() -> None:
    dsn = os.getenv("RESONANCE_TEST_DSN")
    if not dsn:
        pytest.skip("RESONANCE_TEST_DSN is required")

    now = datetime(2031, 1, 1, tzinfo=UTC)
    lineage_zero_best = uuid4()
    lineage_zero_second = uuid4()
    lineage_one = uuid4()
    foreign = uuid4()
    with _fresh_database(dsn) as connection:
        economy = PostgresEconomyRepository(connection)
        for agent_id in (lineage_zero_best, lineage_zero_second, lineage_one, foreign):
            economy.register_agent(agent_id, at=now)
        traces = PostgresTraceRepository(connection)
        for agent_id, energy in (
            (lineage_zero_best, 0.8),
            (lineage_zero_second, 0.7),
            (lineage_one, 0.6),
            (foreign, 0.9),
        ):
            traces.add(
                Trace(
                    author_agent_id=agent_id,
                    kind="VERIFIED_OUTCOME",
                    content="skill-evidence:isolation-probe",
                    created_at=now,
                    updated_at=now,
                    initial_energy=energy,
                    half_life_seconds=3600,
                    confidence=1.0,
                    quality_score=1.0,
                )
            )

        authors = {
            lineage_zero_best: 0,
            lineage_zero_second: 0,
            lineage_one: 1,
        }
        standard = selected_public_trace_stats(
            connection,
            skill="isolation-probe",
            at=now,
            author_lineage=authors,
            departed_agents=set(),
            top_k=2,
            diversified=False,
            diversified_lineages=2,
        )
        diversified = selected_public_trace_stats(
            connection,
            skill="isolation-probe",
            at=now,
            author_lineage=authors,
            departed_agents=set(),
            top_k=2,
            diversified=True,
            diversified_lineages=2,
        )

        # The stronger foreign trace is excluded. Standard top-2 is one lineage;
        # diversified retrieval selects the best trace from each of two lineages.
        assert standard["signal"] == pytest.approx(0.8)
        assert standard["lineage_hhi"] == pytest.approx(1.0)
        assert diversified["signal"] == pytest.approx(0.7)
        assert diversified["lineage_hhi"] == pytest.approx(0.5)
