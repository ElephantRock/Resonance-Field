from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from resonance.agents import (
    ActionRequest,
    ActionType,
    AgentObservation,
    AgentRuntime,
    DefaultPolicyGateway,
    InMemoryDecisionEventStore,
    OutcomeStatus,
)
from resonance.agents.runtime import DecisionContext
from resonance.market.models import MarketBid, MarketTask, bid_score
from resonance.substrate.models import RetrievedTrace, Trace
from resonance.substrate.retrieval import RetrievalWeights


def _embedding() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 1535


class EmptyTraceRepository:
    def add(self, trace: Trace) -> None:
        del trace

    def get(self, trace_id: UUID) -> Trace | None:
        del trace_id
        return None

    def add_relation(self, parent_trace_id: UUID, child_trace_id: UUID, relation_type: str) -> None:
        del parent_trace_id, child_trace_id, relation_type

    def parents(self, child_trace_id: UUID) -> Sequence[Trace]:
        del child_trace_id
        return ()

    def children(self, parent_trace_id: UUID) -> Sequence[Trace]:
        del parent_trace_id
        return ()

    def reinforce(
        self,
        trace_id: UUID,
        *,
        at: datetime,
        actor_agent_id: UUID | None = None,
        kind: str = "reinforcement",
        reinforcement: float = 0.0,
        adoption: float = 0.0,
        verified_utility: float = 0.0,
    ) -> Trace:
        del trace_id, at, actor_agent_id, kind, reinforcement, adoption, verified_utility
        raise KeyError("no traces")

    def search(
        self,
        query_embedding: Sequence[float],
        *,
        at: datetime,
        limit: int = 10,
        weights: RetrievalWeights | None = None,
    ) -> Sequence[RetrievedTrace]:
        del query_embedding, at, limit, weights
        return ()


class FixedPolicy:
    def __init__(self, request: ActionRequest) -> None:
        self.request = request

    def choose(self, agent_id: UUID, context: DecisionContext) -> ActionRequest:
        del agent_id, context
        return self.request


class FakeMarket:
    def __init__(self) -> None:
        self.task_id = uuid4()
        self.bid_id = uuid4()
        self.posted_by: UUID | None = None
        self.bid_by: UUID | None = None

    def post_task(self, requester_agent_id: UUID, **kwargs: object) -> MarketTask:
        self.posted_by = requester_agent_id
        at = kwargs["at"]
        deadline = kwargs["deadline"]
        assert isinstance(at, datetime)
        assert isinstance(deadline, datetime)
        return MarketTask(
            task_id=self.task_id,
            requester_agent_id=requester_agent_id,
            escrow_account_id=uuid4(),
            description=str(kwargs["description"]),
            budget=int(kwargs["budget"]),
            deadline=deadline,
            created_at=at,
        )

    def submit_bid(self, bidder_agent_id: UUID, **kwargs: object) -> MarketBid:
        self.bid_by = bidder_agent_id
        at = kwargs["at"]
        assert isinstance(at, datetime)
        task_id = kwargs["task_id"]
        assert isinstance(task_id, UUID)
        return MarketBid(
            bid_id=self.bid_id,
            task_id=task_id,
            bidder_agent_id=bidder_agent_id,
            price=int(kwargs["price"]),
            confidence=float(kwargs["confidence"]),
            estimated_completion_seconds=int(kwargs["estimated_completion_seconds"]),
            strategy_summary=str(kwargs["strategy_summary"]),
            submitted_at=at,
        )

    def get_task(self, task_id: UUID) -> MarketTask | None:
        del task_id
        return None

    def award(self, task_id: UUID, *, at: datetime) -> None:
        del task_id, at
        return None

    def settle(self, task_id: UUID, *, at: datetime) -> MarketTask:
        del task_id, at
        raise NotImplementedError


def test_bid_score_rewards_efficient_confident_fast_bid() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    task = MarketTask(
        task_id=uuid4(),
        requester_agent_id=uuid4(),
        escrow_account_id=uuid4(),
        description="Compare two hypotheses",
        budget=100,
        created_at=start,
        deadline=start + timedelta(hours=1),
    )
    strong = MarketBid(
        bid_id=uuid4(),
        task_id=task.task_id,
        bidder_agent_id=uuid4(),
        price=40,
        confidence=0.9,
        estimated_completion_seconds=900,
        strategy_summary="Fast empirical comparison",
        submitted_at=start,
    )
    weak = MarketBid(
        bid_id=uuid4(),
        task_id=task.task_id,
        bidder_agent_id=uuid4(),
        price=80,
        confidence=0.6,
        estimated_completion_seconds=3000,
        strategy_summary="Slower expensive comparison",
        submitted_at=start,
    )

    assert bid_score(task, strong) > bid_score(task, weak)


def test_runtime_executes_post_task_and_bid_task() -> None:
    traces = EmptyTraceRepository()
    market = FakeMarket()
    at = datetime(2026, 1, 1, tzinfo=UTC)
    requester = uuid4()
    events = InMemoryDecisionEventStore()
    post_request = ActionRequest(
        ActionType.POST_TASK,
        {
            "description": "Test a substrate hypothesis",
            "budget": 50,
            "deadline": (at + timedelta(hours=1)).isoformat(),
            "required_capabilities": ["analysis"],
            "success_condition": {"metric": "accuracy"},
        },
        confidence=0.8,
    )
    runtime = AgentRuntime(
        traces=traces,
        events=events,
        gateway=DefaultPolicyGateway(),
        policy=FixedPolicy(post_request),
        market=market,
    )
    posted = runtime.step(
        requester,
        AgentObservation("post work", at, _embedding()),
    )

    assert posted.outcome.status == OutcomeStatus.SUCCEEDED
    assert posted.outcome.data["task_id"] == str(market.task_id)
    assert market.posted_by == requester

    bidder = uuid4()
    bid_request = ActionRequest(
        ActionType.BID_TASK,
        {
            "task_id": market.task_id,
            "price": 30,
            "estimated_completion_seconds": 900,
            "strategy_summary": "Run an independent branch",
        },
        confidence=0.77,
    )
    bid_runtime = AgentRuntime(
        traces=traces,
        events=events,
        gateway=DefaultPolicyGateway(),
        policy=FixedPolicy(bid_request),
        market=market,
    )
    bid = bid_runtime.step(
        bidder,
        AgentObservation("bid for work", at + timedelta(minutes=1), _embedding()),
    )

    assert bid.outcome.status == OutcomeStatus.SUCCEEDED
    assert bid.outcome.data["bid_id"] == str(market.bid_id)
    assert market.bid_by == bidder
