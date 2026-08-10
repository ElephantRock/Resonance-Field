from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from resonance.economy import TREASURY_ACCOUNT_ID
from resonance.experiments.decay_models import DecayExperimentConfig
from resonance.experiments.decay_runner import run_decay_experiment
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


def _config() -> DecayExperimentConfig:
    return DecayExperimentConfig(
        name="integration-decay",
        agents=4,
        cycles=12,
        cycle_seconds=30,
        snapshot_every=4,
        initial_credits=100,
        neighborhoods=("alpha", "beta", "gamma"),
        traces_per_neighborhood=3,
        retrieval_limit=3,
        fast_half_life_seconds=30.0,
        slow_half_life_seconds=180.0,
        no_decay_half_life_seconds=1_000_000_000.0,
        reinforcement_amount=0.45,
        resurrection_energy_threshold=0.25,
        novel_trace_every_cycles=3,
        probe_every_cycles=1,
        action_costs={
            "QUERY_SUBSTRATE": 1,
            "REINFORCE_TRACE": 2,
            "ABSTAIN": 0,
        },
    )


def test_decay_runner_persists_probe_and_resurrection_evidence(
    db: psycopg.Connection[dict[str, object]], tmp_path: Path
) -> None:
    summary = run_decay_experiment(
        db,
        config=_config(),
        config_hash="integration-decay-config",
        seed=17,
        arm="fast_decay",
        code_sha="integration-sha",
        output_dir=tmp_path,
    )

    run = db.execute(
        "SELECT status, cycles_completed FROM experiment_runs WHERE run_id = %s",
        (summary["run_id"],),
    ).fetchone()
    assert run is not None
    assert run["status"] == "completed"
    assert run["cycles_completed"] == 12

    events = db.execute("SELECT COUNT(*) AS count FROM decision_events").fetchone()
    costs = db.execute("SELECT COUNT(*) AS count FROM experiment_action_costs").fetchone()
    probes = db.execute(
        "SELECT COUNT(*) AS count FROM decay_retrieval_observations"
    ).fetchone()
    snapshots = db.execute("SELECT COUNT(*) AS count FROM experiment_snapshots").fetchone()
    assert events is not None and events["count"] == 48
    assert costs is not None and costs["count"] == 48
    assert probes is not None and probes["count"] == 216
    assert snapshots is not None and snapshots["count"] == 3

    total = db.execute("SELECT SUM(balance) AS total FROM compute_accounts").fetchone()
    assert total is not None
    assert total["total"] == 1000000000000

    metrics = summary["metrics"]
    assert metrics["event_count"] == 48
    assert metrics["retrieval_observations"] == 216
    assert 0.0 <= metrics["top_turnover_rate"] <= 1.0
    assert 0.0 <= metrics["top_k_jaccard_turnover"] <= 1.0
    assert metrics["reinforcement_actions"] > 0

    for filename in (
        "experiment.json",
        "retrieval.csv",
        "resurrections.csv",
        "events.jsonl",
        "traces.csv",
    ):
        assert (tmp_path / filename).exists()
