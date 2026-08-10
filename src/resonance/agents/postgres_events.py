"""PostgreSQL persistence for append-only agent decision provenance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .actions import ActionType, OutcomeStatus
from .events import DecisionEvent
from .gateway import PolicyResult

_EVENT_COLUMNS = """
event_id, agent_id, occurred_at, trigger, proposed_action, policy_result,
policy_reason, outcome_status, confidence, request_id, correlation_id,
retrieved_trace_ids, output_trace_ids, action_payload, outcome_data, error
"""


def _event_from_row(row: Mapping[str, Any]) -> DecisionEvent:
    return DecisionEvent(
        event_id=row["event_id"],
        agent_id=row["agent_id"],
        occurred_at=row["occurred_at"],
        trigger=row["trigger"],
        proposed_action=ActionType(row["proposed_action"]),
        policy_result=PolicyResult(row["policy_result"]),
        policy_reason=row["policy_reason"],
        outcome_status=OutcomeStatus(row["outcome_status"]),
        confidence=row["confidence"],
        request_id=row["request_id"],
        correlation_id=row["correlation_id"],
        retrieved_trace_ids=tuple(row["retrieved_trace_ids"] or ()),
        output_trace_ids=tuple(row["output_trace_ids"] or ()),
        action_payload=row["action_payload"] or {},
        outcome_data=row["outcome_data"] or {},
        error=row["error"],
    )


class PostgresDecisionEventStore:
    """Append-only event store used by the agent runtime."""

    def __init__(self, connection: Connection[Any]) -> None:
        if not connection.autocommit:
            raise ValueError("PostgresDecisionEventStore requires an autocommit connection")
        connection.row_factory = dict_row
        self._connection = connection

    def transaction(self) -> AbstractContextManager[None]:
        """Open the outer unit of work for side effects plus provenance."""
        return self._connection.transaction()

    def append(self, event: DecisionEvent) -> None:
        self._connection.execute(
            """
            INSERT INTO decision_events (
                event_id, agent_id, occurred_at, trigger, proposed_action,
                policy_result, policy_reason, outcome_status, confidence,
                request_id, correlation_id, retrieved_trace_ids,
                output_trace_ids, action_payload, outcome_data, error
            ) VALUES (
                %(event_id)s, %(agent_id)s, %(occurred_at)s, %(trigger)s,
                %(proposed_action)s, %(policy_result)s, %(policy_reason)s,
                %(outcome_status)s, %(confidence)s, %(request_id)s,
                %(correlation_id)s, %(retrieved_trace_ids)s,
                %(output_trace_ids)s, %(action_payload)s, %(outcome_data)s,
                %(error)s
            )
            """,
            {
                "event_id": event.event_id,
                "agent_id": event.agent_id,
                "occurred_at": event.occurred_at,
                "trigger": event.trigger,
                "proposed_action": event.proposed_action.value,
                "policy_result": event.policy_result.value,
                "policy_reason": event.policy_reason,
                "outcome_status": event.outcome_status.value,
                "confidence": event.confidence,
                "request_id": event.request_id,
                "correlation_id": event.correlation_id,
                "retrieved_trace_ids": list(event.retrieved_trace_ids),
                "output_trace_ids": list(event.output_trace_ids),
                "action_payload": Jsonb(dict(event.action_payload)),
                "outcome_data": Jsonb(dict(event.outcome_data)),
                "error": event.error,
            },
        )

    def get(self, event_id: UUID) -> DecisionEvent | None:
        row = self._connection.execute(
            f"SELECT {_EVENT_COLUMNS} FROM decision_events WHERE event_id = %s",
            (event_id,),
        ).fetchone()
        return None if row is None else _event_from_row(row)

    def list_for_agent(self, agent_id: UUID, *, limit: int = 100) -> Sequence[DecisionEvent]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        rows = self._connection.execute(
            f"""
            SELECT {_EVENT_COLUMNS}
            FROM decision_events
            WHERE agent_id = %s
            ORDER BY occurred_at DESC, event_id DESC
            LIMIT %s
            """,
            (agent_id, limit),
        ).fetchall()
        return tuple(_event_from_row(row) for row in rows)
