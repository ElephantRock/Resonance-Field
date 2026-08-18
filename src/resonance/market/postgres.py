from uuid import UUID, uuid4
from datetime import datetime
from dataclasses import replace

from psycopg import Connection
from psycopg.types.json import Jsonb

from resonance.market.domain import (
    MarketTask,
    MarketBid,
    BidSignal,
    AuctionResult,
    bid_score,
)
from resonance.market.timing import _aware
from resonance.economy import EconomyService


_TASK_COLUMNS = """
    task_id, requester_agent_id, escrow_account_id, budget, deadline,
    status, awarded_agent_id, winning_bid_id, created_at, awarded_at, completed_at
""".strip()

_BID_COLUMNS = """
    bid_id, task_id, bidder_agent_id, price, confidence,
    estimated_completion_seconds, strategy_summary, status, submitted_at
""".strip()


def _task_from_row(row: tuple) -> MarketTask:
    return MarketTask(
        task_id=row[0],
        requester_agent_id=row[1],
        escrow_account_id=row[2],
        budget=row[3],
        deadline=row[4],
        status=row[5],
        awarded_agent_id=row[6],
        winning_bid_id=row[7],
        created_at=row[8],
        awarded_at=row[9],
        completed_at=row[10],
    )


def _bid_from_row(row: tuple) -> MarketBid:
    return MarketBid(
        bid_id=row[0],
        task_id=row[1],
        bidder_agent_id=row[2],
        price=row[3],
        confidence=row[4],
        estimated_completion_seconds=row[5],
        strategy_summary=row[6],
        status=row[7],
        submitted_at=row[8],
    )


class PostgresMarketService:
    def __init__(
        self,
        connection: Connection,
        economy: EconomyService,
        bid_signal_provider: object | None = None,
    ) -> None:
        self._connection = connection
        self._economy = economy
        self._bid_signal_provider = bid_signal_provider

    def publish_task(
        self,
        task_id: UUID,
        requester_agent_id: UUID,
        budget: int,
        deadline: datetime,
        *,
        at: datetime,
    ) -> MarketTask:
        _aware("at", at)
        escrow_account_id = self._economy.create_account(
            owner_agent_id=None,
            reason="task escrow",
            reference_type="task",
            reference_id=task_id,
            at=at,
        ).account_id

        self._economy.transfer(
            self._economy.account_for_agent(requester_agent_id).account_id,
            escrow_account_id,
            budget,
            at=at,
            reason="task funding",
            reference_type="task",
            reference_id=task_id,
        )

        self._connection.execute(
            """
            INSERT INTO market_tasks (
                task_id, requester_agent_id, escrow_account_id, budget, deadline,
                status, created_at
            ) VALUES (%s, %s, %s, %s, %s, 'open', %s)
            """,
            (task_id, requester_agent_id, escrow_account_id, budget, deadline, at),
        )

        return self.get_task(task_id)

    def submit_bid(
        self,
        task_id: UUID,
        bidder_agent_id: UUID,
        price: int,
        confidence: float,
        estimated_completion_seconds: int,
        strategy_summary: str,
        *,
        at: datetime,
    ) -> MarketBid:
        _aware("at", at)
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
