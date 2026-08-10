from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from resonance.economy import TREASURY_ACCOUNT_ID
from resonance.experiments.models import ExperimentConfig
from resonance.experiments.runner import apply_migrations, run_experiment

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
        TRUNCATE experiment_snapshots, experiment_action_costs, experiment_agents,
                 experiment_runs, market_bids, market_tasks, compute_postings,
                 compute_transactions, decision_events, trace_reinforcements,
                 trace_relations, traces CASCADE
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


def _config() -> ExperimentConfig:
    return ExperimentConfig(
        name="integration-emergence",
        agents=4,
        cycles=6,
        cycle_seconds=60,
        initial_credits=100,
        snapshot_every=3,
        trace_half_life_seconds=180.0,
        no_decay_half_life_seconds=1_000_000_000.0,
        task_deadline_cycles=2,
        task_budget_min=2,
        task_budget_max=4,
        topics=("alpha", "beta", "gamma"),
        action_costs={
            "WRITE_TRACE": 3,
            "REINFORCE_TRACE": 2,
            "POST_TASK": 2,
            "BID_TASK": 2,
            "ABSTAIN": 0,
        },
    )


def test_runner_persists_evidence_metrics_and_artifacts(
    db: psycopg.Connection[dict[str, object]], tmp_path: Path
) -> None:
    summary = run_experiment(
        db,
        config=_config(),
        config_hash="integration-config-hash",
        seed=17,
        ablation="full",
        code_sha="integration-sha",
        output_dir=tmp_path,
    )

    run = db.execute(
        "SELECT status, cycles_completed FROM experiment_runs WHERE run_id = %s",
        (summary["run_id"],),
    ).fetchone()
    assert run is not None
    assert run["status"] == "completed"
    assert run["cycles_completed"] == 6

    events = db.execute("SELECT COUNT(*) AS count FROM decision_events").fetchone()
    costs = db.execute("SELECT COUNT(*) AS count FROM experiment_action_costs").fetchone()
    snapshots = db.execute("SELECT COUNT(*) AS count FROM experiment_snapshots").fetchone()
    assert events is not None and events["count"] == 24
    assert costs is not None and costs["count"] == 24
    assert snapshots is not None and snapshots["count"] == 2

    total = db.execute("SELECT SUM(balance) AS total FROM compute_accounts").fetchone()
    assert total is not None
    assert total["total"] == 1000000000000

    assert summary["metrics"]["agent_count"] == 4
    assert summary["metrics"]["event_count"] == 24
    assert 0.0 <= summary["metrics"]["mean_specialization"] <= 1.0
    assert 0.0 <= summary["metrics"]["topic_coverage"] <= 1.0

    for filename in ("experiment.json", "events.jsonl", "agents.csv", "tasks.csv", "traces.csv"):
        assert (tmp_path / filename).exists()
