"""PostgreSQL task market backed by compute-credit escrow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from resonance.economy.repository import EconomyRepository

from .models import AuctionResult, MarketBid, MarketTask, bid_score
from .signals import BidSignal, BidSignalProvider

_TASK_COLUMNS = """
task_id, requester_agent_id, escrow_account_id, description, budget, deadline,
required_capabilities, success_condition, status, awarded_agent_id, winning_bid_id,
created_at, awarded_at, completed_at
"""

_BID_COLUMNS = """
bid_id, task_id, bidder_agent_id, price, confidence, estimated_completion_seconds,
strategy_summary, status, submitted_at
"""


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _task_from_row(row: Mapping[str, Any]) -> MarketTask:
    return MarketTask(
        task_id=row["task_id"],
        requester_agent_id=row["requester_agent_id"],
        escrow_account_id=row["escrow_account_id"],
        description=row["description"],
        budget=row["budget"],
        deadline=row["deadline"],
        required_capabilities=tuple(row["required_capabilities"] or ()),
        success_condition=row["success_condition"] or {},
        status=row["status"],
        awarded_agent_id=row["awarded_agent_id"],
        winning_bid_id=row["winning_bid_id"],
        created_at=row["created_at"],
        awarded_at=row["awarded_at"],
        completed_at=row["completed_at"],
    )


def _bid_from_row(row: Mapping[str, Any]) -> MarketBid:
    return MarketBid(
        bid_id=row["bid_id"],
        task_id=row["task_id"],
        bidder_agent_id=row["bidder_agent_id"],
        price=row["price"],
        confidence=row["confidence"],
        estimated_completion_seconds=row["estimated_completion_seconds"],
        strategy_summary=row["strategy_summary"],
        status=row["status"],
        submitted_at=row["submitted_at"],
    )


class PostgresMarketService:
    """Sealed-bid task market with per-task escrow accounts."""

    def __init__(
        self,
        connection: Connection[Any],
        economy: EconomyRepository,
        *,
        bid_signal_provider: BidSignalProvider | None = None,
    ) -> None:
        if not connection.autocommit:
            raise ValueError("PostgresMarketService requires an autocommit connection")
        connection.row_factory = dict_row
        self._connection = connection
        self._economy = economy
        self._bid_signal_provider = bid_signal_provider

    def post_task(
        self,
        requester_agent_id: UUID,
        *,
        description: str,
        budget: int,
        deadline: datetime,
        at: datetime,
        required_capabilities: Sequence[str] = (),
        success_condition: Mapping[str, object] | None = None,
    ) -> MarketTask:
        _aware("at", at)
        _aware("deadline", deadline)
        if not description.strip():
            raise ValueError("description must not be empty")
        if budget <= 0:
            raise ValueError("budget must be positive")
        if deadline <= at:
            raise ValueError("deadline must be after task creation")
        if any(not item.strip() for item in required_capabilities):
            raise ValueError("required capabilities must not be empty strings")

        agent = self._economy.get_agent(requester_agent_id)
        if agent is None or agent.status != "active":
            raise ValueError("requester must be an active registered agent")

        task_id = uuid4()
        with self._connection.transaction():
            escrow = self._economy.create_system_account(
                "task_escrow",
                at=at,
                reference_id=task_id,
            )
            self._connection.execute(
                """
                INSERT INTO market_tasks (
                    task_id, requester_agent_id, escrow_account_id, description, budget,
                    deadline, required_capabilities, success_condition, status, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'open', %s)
                """,
                (
                    task_id,
                    requester_agent_id,
                    escrow.account_id,
                    description,
                    budget,
                    deadline,
                    Jsonb(list(required_capabilities)),
                    Jsonb(dict(success_condition or {})),
                    at,
                ),
            )
            requester_account = self._economy.account_for_agent(requester_agent_id)
            self._economy.transfer(
                requester_account.account_id,
                escrow.account_id,
                budget,
                at=at,
                reason="task budget escrow",
                reference_type="task",
                reference_id=task_id,
            )

        task = self.get_task(task_id)
        assert task is not None
        return task

    def submit_bid(
        self,
        bidder_agent_id: UUID,
        *,
        task_id: UUID,
        price: int,
        confidence: float,
        estimated_completion_seconds: int,
        strategy_summary: str,
        at: datetime,
    ) -> MarketBid:
        _aware("at", at)
        bidder = self._economy.get_agent(bidder_agent_id)
        if bidder is None or bidder.status != "active":
            raise ValueError("bidder must be an active registered agent")

        with self._connection.transaction():
            row = self._connection.execute(
                f"SELECT {_TASK_COLUMNS} FROM market_tasks WHERE task_id = %s FOR UPDATE",
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            task = _task_from_row(row)
            if task.status != "open":
                raise ValueError("task is not open for bids")
            if at >= task.deadline:
                raise ValueError("task bidding deadline has passed")
            if bidder_agent_id == task.requester_agent_id:
                raise ValueError("requester cannot bid on its own task")
            if price > task.budget:
                raise ValueError("bid price exceeds task budget")

            bid = MarketBid(
                bid_id=uuid4(),
                task_id=task_id,
                bidder_agent_id=bidder_agent_id,
                price=price,
                confidence=confidence,
                estimated_completion_seconds=estimated_completion_seconds,
                strategy_summary=strategy_summary,
                submitted_at=at,
            )
            self._connection.execute(
                """
                INSERT INTO market_bids (
                    bid_id, task_id, bidder_agent_id, price, confidence,
                    estimated_completion_seconds, strategy_summary, status, submitted_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'sealed', %s)
                """,
                (
                    bid.bid_id,
                    bid.task_id,
                    bid.bidder_agent_id,
                    bid.price,
                    bid.confidence,
                    bid.estimated_completion_seconds,
                    bid.strategy_summary,
                    bid.submitted_at,
                ),
            )
        return bid

    def get_task(self, task_id: UUID) -> MarketTask | None:
        row = self._connection.execute(
            f"SELECT {_TASK_COLUMNS} FROM market_tasks WHERE task_id = %s",
            (task_id,),
        ).fetchone()
        return None if row is None else _task_from_row(row)

    def _signal(self, task: MarketTask, bid: MarketBid, *, at: datetime) -> BidSignal:
        if self._bid_signal_provider is None:
            return BidSignal()
        return self._bid_signal_provider.signal(task, bid, at=at)

    def award(self, task_id: UUID, *, at: datetime) -> AuctionResult | None:
        _aware("at", at)
        with self._connection.transaction():
            row = self._connection.execute(
                f"SELECT {_TASK_COLUMNS} FROM market_tasks WHERE task_id = %s FOR UPDATE",
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            task = _task_from_row(row)
            if task.status != "open":
                raise ValueError("task is not open")
            if at < task.deadline:
                raise ValueError("cannot award before bidding deadline")

            bid_rows = self._connection.execute(
                f"""
                SELECT {_BID_COLUMNS}
                FROM market_bids
                WHERE task_id = %s AND status = 'sealed' AND price <= %s
                ORDER BY submitted_at, bid_id
                """,
                (task_id, task.budget),
            ).fetchall()
            bids = [_bid_from_row(item) for item in bid_rows]

            if not bids:
                requester = self._economy.account_for_agent(task.requester_agent_id)
                self._economy.transfer(
                    task.escrow_account_id,
                    requester.account_id,
                    task.budget,
                    at=at,
                    reason="task cancelled without bids",
                    reference_type="task",
                    reference_id=task.task_id,
                )
                self._connection.execute(
                    "UPDATE market_tasks SET status = 'cancelled', completed_at = %s WHERE task_id = %s",
                    (at, task_id),
                )
                return None

            scored: list[tuple[float, MarketBid, float, BidSignal]] = []
            for bid in bids:
                baseline = bid_score(task, bid)
                signal = self._signal(task, bid, at=at)
                total = baseline + signal.adjustment
                scored.append((total, bid, baseline, signal))

            ranked = sorted(
                scored,
                key=lambda item: (-item[0], item[1].submitted_at, str(item[1].bid_id)),
            )
            score, winner, _, _ = ranked[0]

            for total, bid, baseline, signal in ranked:
                self._connection.execute(
                    """
                    INSERT INTO market_auction_scores (
                        auction_score_id, task_id, bid_id, bidder_agent_id,
                        baseline_score, signal_adjustment, total_score,
                        provider_label, components, selected, captured_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        uuid4(),
                        task.task_id,
                        bid.bid_id,
                        bid.bidder_agent_id,
                        baseline,
                        signal.adjustment,
                        total,
                        signal.provider_label,
                        Jsonb(dict(signal.components)),
                        bid.bid_id == winner.bid_id,
                        at,
                    ),
                )

            self._connection.execute(
                "UPDATE market_bids SET status = 'selected' WHERE bid_id = %s AND status = 'sealed'",
                (winner.bid_id,),
            )
            self._connection.execute(
                """
                UPDATE market_bids
                SET status = 'rejected'
                WHERE task_id = %s AND status = 'sealed'
                """,
                (task_id,),
            )
            self._connection.execute(
                """
                UPDATE market_tasks
                SET status = 'awarded', awarded_agent_id = %s, winning_bid_id = %s, awarded_at = %s
                WHERE task_id = %s
                """,
                (winner.bidder_agent_id, winner.bid_id, at, task_id),
            )
            winner = replace(winner, status="selected")

        awarded = self.get_task(task_id)
        assert awarded is not None
        return AuctionResult(task=awarded, winning_bid=winner, score=score)

    def settle(self, task_id: UUID, *, at: datetime) -> MarketTask:
        _aware("at", at)
        with self._connection.transaction():
            row = self._connection.execute(
                f"SELECT {_TASK_COLUMNS} FROM market_tasks WHERE task_id = %s FOR UPDATE",
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            task = _task_from_row(row)
            if task.status != "awarded" or task.winning_bid_id is None:
                raise ValueError("task must be awarded before settlement")

            bid_row = self._connection.execute(
                f"SELECT {_BID_COLUMNS} FROM market_bids WHERE bid_id = %s",
                (task.winning_bid_id,),
            ).fetchone()
            if bid_row is None:
                raise RuntimeError("winning bid is missing")
            winning_bid = _bid_from_row(bid_row)

            winner_account = self._economy.account_for_agent(winning_bid.bidder_agent_id)
            requester_account = self._economy.account_for_agent(task.requester_agent_id)
            self._economy.transfer(
                task.escrow_account_id,
                winner_account.account_id,
                winning_bid.price,
                at=at,
                reason="task settlement",
                reference_type="task",
                reference_id=task.task_id,
            )
            refund = task.budget - winning_bid.price
            if refund:
                self._economy.transfer(
                    task.escrow_account_id,
                    requester_account.account_id,
                    refund,
                    at=at,
                    reason="unused task budget refund",
                    reference_type="task",
                    reference_id=task.task_id,
                )
            self._connection.execute(
                "UPDATE market_tasks SET status = 'completed', completed_at = %s WHERE task_id = %s",
                (at, task_id),
            )

        completed = self.get_task(task_id)
        assert completed is not None
        return completed
