from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence
from uuid import UUID, uuid4

from resonance.agents import (
    ActionRequest,
    ActionType,
    AgentObservation,
    AgentRuntime,
    DefaultPolicyGateway,
    InMemoryDecisionEventStore,
    OutcomeStatus,
    PolicyResult,
)
from resonance.agents.runtime import DecisionContext
from resonance.substrate.models import RetrievedTrace, Trace
from resonance.substrate.retrieval import RetrievalWeights


def _embedding() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 1535


class FakeTraceRepository:
    def __init__(self) -> None:
        self.search_called = False
        self.added: list[Trace] = []
        self.traces: dict[UUID, Trace] = {}
        self.retrieved: list[RetrievedTrace] = []

    def add(self, trace: Trace) -> None:
        self.added.append(trace)
        self.traces[trace.trace_id] = trace

    def get(self, trace_id: UUID) -> Trace | None:
        return self.traces.get(trace_id)

    def add_relation(
        self,
        parent_trace_id: UUID,
        child_trace_id: UUID,
        relation_type: str,
    ) -> None:
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
        del at, actor_agent_id, kind, reinforcement, adoption, verified_utility
        return self.traces[trace_id]

    def search(
        self,
        query_embedding: Sequence[float],
        *,
        at: datetime,
        limit: int = 10,
        weights: RetrievalWeights | None = None,
    ) -> Sequence[RetrievedTrace]:
        del query_embedding, at, weights
        self.search_called = True
        return tuple(self.retrieved[:limit])


class FixedPolicy:
    def __init__(self, repository: FakeTraceRepository, request: ActionRequest) -> None:
        self.repository = repository
        self.request = request
        self.context: DecisionContext | None = None

    def choose(self, agent_id: UUID, context: DecisionContext) -> ActionRequest:
        del agent_id
        assert self.repository.search_called
        self.context = context
        return self.request


def _observation() -> AgentObservation:
    return AgentObservation(
        trigger="test trigger",
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        query_embedding=_embedding(),
    )


def test_runtime_queries_before_policy_and_writes_trace() -> None:
    repository = FakeTraceRepository()
    events = InMemoryDecisionEventStore()
    request = ActionRequest(
        ActionType.WRITE_TRACE,
        {"kind": "HYPOTHESIS", "content": "A new substrate hypothesis"},
        confidence=0.72,
    )
    policy = FixedPolicy(repository, request)
    runtime = AgentRuntime(
        traces=repository,
        events=events,
        gateway=DefaultPolicyGateway(),
        policy=policy,
    )
    agent_id = uuid4()

    result = runtime.step(agent_id, _observation())

    assert result.outcome.status == OutcomeStatus.SUCCEEDED
    assert len(repository.added) == 1
    written = repository.added[0]
    assert written.author_agent_id == agent_id
    assert written.content == "A new substrate hypothesis"
    assert written.embedding == _embedding()
    assert result.event.output_trace_ids == (written.trace_id,)
    assert events.get(result.event.event_id) == result.event
    assert policy.context is not None


def test_rejected_action_is_traced_without_side_effects() -> None:
    repository = FakeTraceRepository()
    events = InMemoryDecisionEventStore()
    request = ActionRequest(
        ActionType.REQUEST_TOOL,
        {"tool": "external-search", "api_token": "should-not-be-stored"},
        confidence=0.9,
    )
    runtime = AgentRuntime(
        traces=repository,
        events=events,
        gateway=DefaultPolicyGateway(),
        policy=FixedPolicy(repository, request),
    )

    result = runtime.step(uuid4(), _observation())

    assert result.policy.result == PolicyResult.REJECT
    assert result.outcome.status == OutcomeStatus.REJECTED
    assert repository.added == []
    assert result.event.action_payload["api_token"] == "[REDACTED]"
    assert events.get(result.event.event_id) == result.event


def test_execution_failure_is_recorded_as_event() -> None:
    repository = FakeTraceRepository()
    events = InMemoryDecisionEventStore()
    request = ActionRequest(ActionType.WRITE_TRACE, {"kind": "HYPOTHESIS"})
    runtime = AgentRuntime(
        traces=repository,
        events=events,
        gateway=DefaultPolicyGateway(),
        policy=FixedPolicy(repository, request),
    )

    result = runtime.step(uuid4(), _observation())

    assert result.policy.result == PolicyResult.ALLOW
    assert result.outcome.status == OutcomeStatus.FAILED
    assert result.event.error is not None
    assert "content must be a non-empty string" in result.event.error
    assert events.get(result.event.event_id) == result.event


def test_action_vocabulary_matches_v01_specification() -> None:
    assert {action.value for action in ActionType} == {
        "OBSERVE",
        "QUERY_SUBSTRATE",
        "READ_TRACE",
        "WRITE_TRACE",
        "REINFORCE_TRACE",
        "CHALLENGE_TRACE",
        "CROSSOVER",
        "POST_TASK",
        "BID_TASK",
        "DELEGATE",
        "REQUEST_TOOL",
        "REQUEST_FORK",
        "VOTE",
        "ABSTAIN",
        "SLEEP",
    }
