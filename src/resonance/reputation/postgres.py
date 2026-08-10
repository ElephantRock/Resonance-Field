"""PostgreSQL implementation of persistent Beta reputation evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import dict_row

from .models import ReputationState


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


class PostgresReputationRepository:
    def __init__(self, connection: Connection[Any]) -> None:
        if not connection.autocommit:
            raise ValueError("PostgresReputationRepository requires an autocommit connection")
        connection.row_factory = dict_row
        self._connection = connection

    def get(
        self,
        agent_id: UUID,
        *,
        dimension: str,
        context_key: str,
        at: datetime,
    ) -> ReputationState:
        _aware("at", at)
        if not dimension.strip() or not context_key.strip():
            raise ValueError("dimension and context_key must not be empty")
        row = self._connection.execute(
            """
            SELECT agent_id, dimension, context_key, alpha, beta, updated_at
            FROM reputation_states
            WHERE agent_id = %s AND dimension = %s AND context_key = %s
            """,
            (agent_id, dimension, context_key),
        ).fetchone()
        if row is None:
            return ReputationState(agent_id, dimension, context_key, 1.0, 1.0, at)
        return ReputationState(
            row["agent_id"], row["dimension"], row["context_key"],
            float(row["alpha"]), float(row["beta"]), row["updated_at"]
        )

    def record_evidence(
        self,
        agent_id: UUID,
        *,
        dimension: str,
        context_key: str,
        positive: bool,
        source_type: str,
        source_id: UUID,
        at: datetime,
        weight: float = 1.0,
    ) -> ReputationState:
        _aware("at", at)
        if not dimension.strip() or not context_key.strip() or not source_type.strip():
            raise ValueError("reputation evidence labels must not be empty")
        if weight <= 0:
            raise ValueError("weight must be positive")
        with self._connection.transaction():
            existing = self._connection.execute(
                """
                SELECT alpha_after, beta_after
                FROM reputation_evidence
                WHERE agent_id = %s AND dimension = %s AND context_key = %s
                  AND source_type = %s AND source_id = %s
                """,
                (agent_id, dimension, context_key, source_type, source_id),
            ).fetchone()
            if existing is not None:
                return ReputationState(
                    agent_id, dimension, context_key,
                    float(existing["alpha_after"]), float(existing["beta_after"]), at
                )

            row = self._connection.execute(
                """
                SELECT alpha, beta, updated_at
                FROM reputation_states
                WHERE agent_id = %s AND dimension = %s AND context_key = %s
                FOR UPDATE
                """,
                (agent_id, dimension, context_key),
            ).fetchone()
            alpha_before = 1.0 if row is None else float(row["alpha"])
            beta_before = 1.0 if row is None else float(row["beta"])
            alpha_after = alpha_before + (weight if positive else 0.0)
            beta_after = beta_before + (0.0 if positive else weight)

            self._connection.execute(
                """
                INSERT INTO reputation_states (
                    agent_id, dimension, context_key, alpha, beta, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (agent_id, dimension, context_key) DO UPDATE
                SET alpha = EXCLUDED.alpha, beta = EXCLUDED.beta, updated_at = EXCLUDED.updated_at
                """,
                (agent_id, dimension, context_key, alpha_after, beta_after, at),
            )
            self._connection.execute(
                """
                INSERT INTO reputation_evidence (
                    evidence_id, agent_id, dimension, context_key, positive, weight,
                    alpha_before, beta_before, alpha_after, beta_after,
                    source_type, source_id, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid4(), agent_id, dimension, context_key, positive, weight,
                    alpha_before, beta_before, alpha_after, beta_after,
                    source_type, source_id, at,
                ),
            )
        return ReputationState(
            agent_id, dimension, context_key, alpha_after, beta_after, at
        )
