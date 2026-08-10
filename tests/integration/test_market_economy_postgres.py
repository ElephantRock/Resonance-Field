from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from resonance.agents import (
    ActionRequest,
    ActionType,
    AgentObservation,
    AgentRuntime,
    DefaultPolicyGateway,
    OutcomeStatus,
)
from resonance.agents.postgres_events import PostgresDecisionEventStore
from resonance.agents.runtime import DecisionContext
from resonance.economy import TREASURY_ACCOUNT_ID, PostgresEconomyRepository
from resonance.market import PostgresMarketService
from resonance.substrate.postgres import PostgresTraceRepository

pytestmark = pytest.mark.integration


def _embedding() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 1535


def _apply_migrations(connection: psycopg.Connection[dict[str, object]]) -> None:
    for path in sorted(Path("migrations").glob("*.sql")):
        connection.execute(path.read_text())


def _reset_state(connection: psycopg.Connection[dict[str, object]]) -> None:
    connection.execute(
        """
        TRUNCATE market_bids, market_tasks, compute_postings, compute_transactions,
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


def test_double_entry_escrow_auction_and_settlement(
    db: psycopg.Connection[dict[str, object]],
) -> None:
    economy = PostgresEconomyRepository(db)
    market = PostgresMarketService(db, economy)
    start = datetime(2026, 1, 2, tzinfo=UTC)
    requester = uuid4()
    bidder_a = uuid4()
    bidder_b = uuid4()

    economy.register_agent(requester, at=start, initial_credits=100)
    economy.register_agent(bidder_a, at=start, initial_credits=10)
    economy.register_agent(bidder_b, at=start, initial_credits=10)

    total = db.execute("SELECT SUM(balance) AS total FROM compute_accounts").fetchone()
    assert total is not None
    assert total["total"] == 1000000000000

    task = market.post_task(
        requester,
        description="Evaluate two competing substrate hypotheses",
        budget=60,
        deadline=start + timedelta(hours=1),
        at=start,
        required_capabilities=("analysis", "verification"),
        success_condition={"metric": "validated_result"},
    )
    assert economy.balance(requester) == 40
    escrow = db.execute(
        "SELECT balance FROM compute_accounts WHERE account_id = %s",
        (task.escrow_account_id,),
    ).fetchone()
    assert escrow is not None
    assert escrow["balance"] == 60

    bid_a = market.submit_bid(
        bidder_a,
        task_id=task.task_id,
        price=45,
        confidence=0.90,
        estimated_completion_seconds=1800,
        strategy_summary="Run a careful independent comparison",
        at=start + timedelta(minutes=10),
    )
    bid_b = market.submit_bid(
        bidder_b,
        task_id=task.task_id,
        price=30,
        confidence=0.75,
        estimated_completion_seconds=900,
        strategy_summary="Run a faster targeted benchmark",
        at=start + timedelta(minutes=12),
    )

    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        db.execute("UPDATE market_bids SET price = 1 WHERE bid_id = %s", (bid_a.bid_id,))

    award = market.award(task.task_id, at=start + timedelta(hours=1, minutes=1))
    assert award is not None
    assert award.winning_bid.bid_id == bid_b.bid_id
    assert award.task.awarded_agent_id == bidder_b

    statuses = db.execute(
        "SELECT bid_id, status FROM market_bids WHERE task_id = %s ORDER BY bid_id",
        (task.task_id,),
    ).fetchall()
    status_by_id = {row["bid_id"]: row["status"] for row in statuses}
    assert status_by_id[bid_a.bid_id] == "rejected"
    assert status_by_id[bid_b.bid_id] == "selected"

    completed = market.settle(task.task_id, at=start + timedelta(hours=2))
    assert completed.status == "completed"
    assert economy.balance(requester) == 70
    assert economy.balance(bidder_a) == 10
    assert economy.balance(bidder_b) == 40

    escrow_after = db.execute(
        "SELECT balance FROM compute_accounts WHERE account_id = %s",
        (task.escrow_account_id,),
    ).fetchone()
    assert escrow_after is not None
    assert escrow_after["balance"] == 0

    total_after = db.execute("SELECT SUM(balance) AS total FROM compute_accounts").fetchone()
    assert total_after is not None
    assert total_after["total"] == 1000000000000

    unbalanced = db.execute(
        """
        SELECT transaction_id, SUM(amount) AS net
        FROM compute_postings
        GROUP BY transaction_id
        HAVING SUM(amount) <> 0
        """
    ).fetchall()
    assert unbalanced == []

    transaction = db.execute(
        "SELECT transaction_id FROM compute_transactions ORDER BY created_at LIMIT 1"
    ).fetchone()
    assert transaction is not None
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute(
            "UPDATE compute_transactions SET reason = 'tampered' WHERE transaction_id = %s",
            (transaction["transaction_id"],),
        )


class FixedPolicy:
    def __init__(self, request: ActionRequest) -> None:
        self.request = request

    def choose(self, agent_id: UUID, context: DecisionContext) -> ActionRequest:
        del agent_id, context
        return self.request


def test_runtime_posts_and_bids_against_persistent_market(
    db: psycopg.Connection[dict[str, object]],
) -> None:
    economy = PostgresEconomyRepository(db)
    market = PostgresMarketService(db, economy)
    traces = PostgresTraceRepository(db)
    events = PostgresDecisionEventStore(db)
    start = datetime(2026, 1, 3, tzinfo=UTC)
    requester = uuid4()
    bidder = uuid4()
    economy.register_agent(requester, at=start, initial_credits=80)
    economy.register_agent(bidder, at=start, initial_credits=5)

    post = ActionRequest(
        ActionType.POST_TASK,
        {
            "description": "Validate a bridge hypothesis",
            "budget": 50,
            "deadline": (start + timedelta(hours=1)).isoformat(),
            "required_capabilities": ["verification"],
            "success_condition": {"test": "passes"},
        },
        confidence=0.84,
    )
    post_runtime = AgentRuntime(
        traces=traces,
        events=events,
        gateway=DefaultPolicyGateway(),
        policy=FixedPolicy(post),
        market=market,
    )
    posted = post_runtime.step(
        requester,
        AgentObservation("publish market task", start, _embedding()),
    )
    assert posted.outcome.status == OutcomeStatus.SUCCEEDED
    task_id = UUID(str(posted.outcome.data["task_id"]))
    assert economy.balance(requester) == 30

    bid = ActionRequest(
        ActionType.BID_TASK,
        {
            "task_id": task_id,
            "price": 35,
            "estimated_completion_seconds": 1200,
            "strategy_summary": "Verify independently and report evidence",
        },
        confidence=0.78,
    )
    bid_runtime = AgentRuntime(
        traces=traces,
        events=events,
        gateway=DefaultPolicyGateway(),
        policy=FixedPolicy(bid),
        market=market,
    )
    submitted = bid_runtime.step(
        bidder,
        AgentObservation("bid for market task", start + timedelta(minutes=5), _embedding()),
    )
    assert submitted.outcome.status == OutcomeStatus.SUCCEEDED
    assert submitted.event.proposed_action == ActionType.BID_TASK
    assert events.get(posted.event.event_id) == posted.event
    assert events.get(submitted.event.event_id) == submitted.event
