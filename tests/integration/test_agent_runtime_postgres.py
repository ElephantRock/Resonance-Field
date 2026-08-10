from __future__ import annotations

import os
from datetime import UTC, datetime
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
from resonance.substrate.models import Trace
from resonance.substrate.postgres import PostgresTraceRepository

pytestmark = pytest.mark.integration


def _embedding() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 1535


def _apply_migrations(connection: psycopg.Connection[dict[str, object]]) -> None:
    for path in sorted(Path("migrations").glob("*.sql")):
        migration = path.read_text()
        for statement in migration.split(";"):
            if statement.strip():
                connection.execute(statement)


class WriteAfterRetrievalPolicy:
    def __init__(self, expected_trace_id: UUID) -> None:
        self.expected_trace_id = expected_trace_id

    def choose(self, agent_id: UUID, context: DecisionContext) -> ActionRequest:
        del agent_id
        assert self.expected_trace_id in {item.trace.trace_id for item in context.retrieved}
        return ActionRequest(
            ActionType.WRITE_TRACE,
            {
                "kind": "MORNING_HYPOTHESIS",
                "content": "A derived hypothesis produced after substrate retrieval",
                "initial_energy": 0.6,
                "half_life_seconds": 7200.0,
            },
            confidence=0.81,
        )


def test_runtime_persists_append_only_decision_provenance() -> None:
    dsn = os.getenv("RESONANCE_TEST_DSN")
    if not dsn:
        pytest.skip("RESONANCE_TEST_DSN is not configured")

    connection = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
    try:
        _apply_migrations(connection)
        connection.execute(
            "TRUNCATE decision_events, trace_reinforcements, trace_relations, traces CASCADE"
        )

        traces = PostgresTraceRepository(connection)
        events = PostgresDecisionEventStore(connection)
        at = datetime(2026, 1, 1, tzinfo=UTC)
        seed = Trace(
            kind="HYPOTHESIS",
            content="Seed trace",
            embedding=_embedding(),
            created_at=at,
            updated_at=at,
            initial_energy=0.9,
            half_life_seconds=86400.0,
        )
        traces.add(seed)

        agent_id = uuid4()
        runtime = AgentRuntime(
            traces=traces,
            events=events,
            gateway=DefaultPolicyGateway(),
            policy=WriteAfterRetrievalPolicy(seed.trace_id),
        )
        result = runtime.step(
            agent_id,
            AgentObservation(
                trigger="integration experiment",
                observed_at=at,
                query_embedding=_embedding(),
                retrieval_limit=4,
            ),
        )

        assert result.outcome.status == OutcomeStatus.SUCCEEDED
        assert result.event.retrieved_trace_ids == (seed.trace_id,)
        assert len(result.event.output_trace_ids) == 1
        written = traces.get(result.event.output_trace_ids[0])
        assert written is not None
        assert written.author_agent_id == agent_id
        assert written.kind == "MORNING_HYPOTHESIS"

        persisted = events.get(result.event.event_id)
        assert persisted == result.event
        assert events.list_for_agent(agent_id) == (result.event,)

        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            connection.execute(
                "UPDATE decision_events SET trigger = 'tampered' WHERE event_id = %s",
                (result.event.event_id,),
            )
    finally:
        connection.close()
