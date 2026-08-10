from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from resonance.economy import TREASURY_ACCOUNT_ID, PostgresEconomyRepository
from resonance.experiments.integration_campaign import (
    ArmSpec,
    IntegrationCampaignConfig,
    IntegrationEnvironment,
    run_integration_arm,
    validated_policy,
)
from resonance.market import BidSignal, PostgresMarketService

pytestmark = pytest.mark.integration


def _apply_migrations(connection: psycopg.Connection[dict[str, object]]) -> None:
    for path in sorted(Path("migrations").glob("*.sql")):
        connection.execute(path.read_text())


def _reset_state(connection: psycopg.Connection[dict[str, object]]) -> None:
    connection.execute(
        """
        TRUNCATE integration_campaign_outcomes, integration_campaign_runs,
                 market_auction_scores, reputation_evidence, reputation_states,
                 experiment_snapshots, experiment_action_costs, experiment_agents,
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


@pytest.fixture
def db() -> psycopg.Connection[dict[str, object]]:
    dsn = os.getenv("RESONANCE_TEST_DSN")
    if not dsn:
        pytest.skip("RESONANCE_TEST_DSN is not configured")
    connection = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
    _apply_migrations(connection)
    _reset_state(connection)
    try:
        yield connection
    finally:
        connection.close()


class FavoredBidderSignal:
    def __init__(self, favored: UUID) -> None:
        self.favored = favored

    def signal(self, task, bid, *, at):
        del task, at
        adjustment = 0.40 if bid.bidder_agent_id == self.favored else 0.0
        return BidSignal(
            adjustment=adjustment,
            provider_label="test-system-signal",
            components={"favored": float(bid.bidder_agent_id == self.favored)},
        )


def test_system_signal_changes_winner_and_is_append_only(
    db: psycopg.Connection[dict[str, object]],
) -> None:
    economy = PostgresEconomyRepository(db)
    start = datetime(2026, 8, 10, tzinfo=UTC)
    requester = uuid4()
    bidder_a = uuid4()
    bidder_b = uuid4()
    for agent in (requester, bidder_a, bidder_b):
        economy.register_agent(agent, at=start, initial_credits=100)

    market = PostgresMarketService(
        db,
        economy,
        bid_signal_provider=FavoredBidderSignal(bidder_a),
    )
    task = market.post_task(
        requester,
        description="signal audit",
        budget=20,
        deadline=start + timedelta(seconds=20),
        at=start,
    )
    bid_a = market.submit_bid(
        bidder_a,
        task_id=task.task_id,
        price=15,
        confidence=0.50,
        estimated_completion_seconds=15,
        strategy_summary="favored by system signal only",
        at=start + timedelta(seconds=1),
    )
    market.submit_bid(
        bidder_b,
        task_id=task.task_id,
        price=8,
        confidence=0.90,
        estimated_completion_seconds=5,
        strategy_summary="stronger baseline bid",
        at=start + timedelta(seconds=2),
    )

    award = market.award(task.task_id, at=task.deadline)
    assert award is not None
    assert award.winning_bid.bid_id == bid_a.bid_id

    scores = db.execute(
        """
        SELECT auction_score_id, bid_id, provider_label, signal_adjustment, selected
        FROM market_auction_scores
        WHERE task_id = %s
        ORDER BY bid_id
        """,
        (task.task_id,),
    ).fetchall()
    assert len(scores) == 2
    assert all(row["provider_label"] == "test-system-signal" for row in scores)
    selected = next(row for row in scores if row["selected"])
    assert selected["bid_id"] == bid_a.bid_id
    assert float(selected["signal_adjustment"]) == pytest.approx(0.40)

    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute(
            "UPDATE market_auction_scores SET total_score = 0 WHERE auction_score_id = %s",
            (selected["auction_score_id"],),
        )

    market.settle(task.task_id, at=task.deadline + timedelta(seconds=1))
    total = db.execute("SELECT SUM(balance) AS total FROM compute_accounts").fetchone()
    assert total is not None and int(total["total"]) == 1000000000000


def _tiny_config() -> IntegrationCampaignConfig:
    env = IntegrationEnvironment(
        agents=5,
        domains=("a", "b", "c"),
        cycles=8,
        cycle_seconds=10,
        shift_period=4,
        candidate_count=2,
        task_budget=8,
        bid_deadline_seconds=6,
        trace_half_life_cycles=4.0,
        initial_credits=300,
        base_success_probability=0.38,
        practice_gain=0.10,
        maximum_success_probability=0.90,
        confidence_base=0.35,
        confidence_evidence_weight=0.35,
        confidence_noise_weight=0.20,
        price_floor=0.45,
        price_span=0.35,
        completion_min_seconds=2,
        completion_span_seconds=3,
    )
    return IntegrationCampaignConfig(
        name="integration-postgres-test",
        environment=env,
        seeds=(31,),
        holdout_seeds=(41,),
        holdout_cycles=10,
        holdout_shift_period=5,
        holdout_candidate_count=2,
        success_tolerance=0.02,
        incumbent_tolerance=0.06,
        economic_tolerance=0.10,
    )


def test_real_integration_arm_preserves_hard_invariants(
    db: psycopg.Connection[dict[str, object]],
) -> None:
    config = _tiny_config()
    arm = ArmSpec("validated", validated_policy(), config.environment)
    summary = run_integration_arm(
        db,
        config=config,
        config_hash="tiny",
        experiment_number=14,
        arm=arm,
        seed=31,
        code_sha="test",
    )
    assert all(summary["invariants"].values())
    assert summary["metrics"]["success_rate"] >= 0.0

    run_count = db.execute("SELECT COUNT(*) AS count FROM integration_campaign_runs").fetchone()
    outcome_count = db.execute("SELECT COUNT(*) AS count FROM integration_campaign_outcomes").fetchone()
    evidence_count = db.execute("SELECT COUNT(*) AS count FROM reputation_evidence").fetchone()
    assert run_count is not None and int(run_count["count"]) == 1
    assert outcome_count is not None and int(outcome_count["count"]) == 8
    assert evidence_count is not None and int(evidence_count["count"]) == 16


def test_default_market_remains_reputation_neutral(
    db: psycopg.Connection[dict[str, object]],
) -> None:
    economy = PostgresEconomyRepository(db)
    start = datetime(2026, 8, 11, tzinfo=UTC)
    requester = uuid4()
    bidder = uuid4()
    economy.register_agent(requester, at=start, initial_credits=50)
    economy.register_agent(bidder, at=start, initial_credits=10)
    market = PostgresMarketService(db, economy)
    task = market.post_task(
        requester,
        description="neutral default",
        budget=10,
        deadline=start + timedelta(seconds=20),
        at=start,
    )
    market.submit_bid(
        bidder,
        task_id=task.task_id,
        price=5,
        confidence=0.5,
        estimated_completion_seconds=5,
        strategy_summary="ordinary bid",
        at=start + timedelta(seconds=1),
    )
    award = market.award(task.task_id, at=task.deadline)
    assert award is not None
    row = db.execute(
        """
        SELECT provider_label, signal_adjustment, components
        FROM market_auction_scores
        WHERE task_id = %s AND selected
        """,
        (task.task_id,),
    ).fetchone()
    assert row is not None
    assert row["provider_label"] == "neutral"
    assert float(row["signal_adjustment"]) == 0.0
    assert dict(row["components"]) == {}
