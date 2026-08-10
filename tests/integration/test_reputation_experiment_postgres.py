from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from resonance.economy import TREASURY_ACCOUNT_ID
from resonance.experiments.reputation_models import ReputationExperimentConfig
from resonance.experiments.reputation_runner import run_reputation_experiment
from resonance.experiments.runner import apply_migrations

pytestmark = pytest.mark.integration


@pytest.fixture
def db() -> psycopg.Connection[dict[str, object]]:
    dsn = os.getenv("RESONANCE_TEST_DSN")
    if not dsn:
        pytest.skip("RESONANCE_TEST_DSN is not configured")
    connection = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
    apply_migrations(connection)
    connection.execute(
        """
        TRUNCATE reputation_auction_scores, reputation_delegation_outcomes,
                 reputation_evidence, reputation_states, decay_resurrection_events,
                 decay_retrieval_observations, experiment_snapshots,
                 experiment_action_costs, experiment_agents, experiment_runs,
                 market_bids, market_tasks, compute_postings, compute_transactions,
                 decision_events, trace_reinforcements, trace_relations, traces CASCADE
        """
    )
    connection.execute(
        "DELETE FROM compute_accounts WHERE account_id <> %s",
        (TREASURY_ACCOUNT_ID,),
    )
    connection.execute("DELETE FROM agents")
    connection.execute(
        "UPDATE compute_accounts SET balance = 1000000000000 WHERE account_id = %s",
        (TREASURY_ACCOUNT_ID,),
    )
    try:
        yield connection
    finally:
        connection.close()


def _config() -> ReputationExperimentConfig:
    return ReputationExperimentConfig(
        name="integration-reputation",
        agents=6,
        cycles=24,
        cycle_seconds=10,
        shift_cycle=12,
        snapshot_every=6,
        initial_credits=200,
        domains=("alpha", "beta", "gamma"),
        candidate_count=3,
        task_budget=8,
        bid_deadline_seconds=5,
        fast_half_life_seconds=30.0,
        slow_half_life_seconds=120.0,
        evidence_initial_energy=0.9,
        reputation_weight=0.4,
        base_success_probability=1.0,
        practice_gain=0.0,
        maximum_success_probability=1.0,
        early_post_shift_cycles=6,
        late_post_shift_cycles=6,
    )


def test_reputation_runner_persists_outcomes_evidence_and_artifacts(
    db: psycopg.Connection[dict[str, object]], tmp_path: Path
) -> None:
    summary = run_reputation_experiment(
        db,
        config=_config(),
        config_hash="integration-reputation-config",
        seed=17,
        arm="slow_reputation",
        code_sha="integration-reputation-sha",
        output_dir=tmp_path,
    )

    run = db.execute(
        "SELECT status, cycles_completed FROM experiment_runs WHERE run_id = %s",
        (summary["run_id"],),
    ).fetchone()
    assert run is not None
    assert run["status"] == "completed"
    assert run["cycles_completed"] == 24

    outcomes = db.execute("SELECT COUNT(*) AS count FROM reputation_delegation_outcomes").fetchone()
    scores = db.execute("SELECT COUNT(*) AS count FROM reputation_auction_scores").fetchone()
    evidence = db.execute("SELECT COUNT(*) AS count FROM reputation_evidence").fetchone()
    traces = db.execute("SELECT COUNT(*) AS count FROM traces WHERE kind = 'VERIFIED_OUTCOME'").fetchone()
    snapshots = db.execute("SELECT COUNT(*) AS count FROM experiment_snapshots").fetchone()
    assert outcomes is not None and outcomes["count"] == 24
    assert scores is not None and scores["count"] == 72
    assert evidence is not None and evidence["count"] == 24
    assert traces is not None and traces["count"] == 24
    assert snapshots is not None and snapshots["count"] == 4

    selected = db.execute(
        "SELECT COUNT(*) AS count FROM reputation_auction_scores WHERE selected"
    ).fetchone()
    assert selected is not None and selected["count"] == 24

    total = db.execute("SELECT SUM(balance) AS total FROM compute_accounts").fetchone()
    assert total is not None and total["total"] == 1000000000000

    assert summary["metrics"]["task_count"] == 24
    assert summary["metrics"]["overall_success_rate"] == 1.0
    assert summary["metrics"]["reputation_evidence_count"] == 24
    assert summary["metrics"]["verified_evidence_trace_count"] == 24

    for filename in (
        "experiment.json",
        "outcomes.csv",
        "auction_scores.csv",
        "reputation.csv",
        "reputation_evidence.csv",
        "tasks.csv",
        "traces.csv",
    ):
        assert (tmp_path / filename).exists()
