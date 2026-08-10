"""PostgreSQL + pgvector implementation of the substrate repository."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg import Connection

from .decay import reinforce_energy
from .models import RetrievedTrace, Trace
from .retrieval import RetrievalWeights

_TRACE_COLUMNS = """
trace_id, author_agent_id, kind, content, embedding, created_at, updated_at,
initial_energy, energy_anchor, energy_updated_at, half_life_seconds, confidence,
quality_score, adoption_score, context_score, exploration_bonus,
repetition_penalty, status, safety_class, visibility
"""


def register_pgvector(connection: Connection[Any]) -> None:
    """Register pgvector adapters on an already-migrated connection."""
    register_vector(connection)


def _as_vector(value: Sequence[float] | None) -> Vector | None:
    if value is None:
        return None
    if len(value) != 1536:
        raise ValueError("embedding must contain exactly 1536 dimensions")
    return Vector(value)


def _trace_from_row(row: Mapping[str, Any]) -> Trace:
    raw_embedding = row.get("embedding")
    embedding = None
    if raw_embedding is not None:
        embedding = tuple(float(value) for value in raw_embedding)

    return Trace(
        trace_id=row["trace_id"],
        author_agent_id=row["author_agent_id"],
        kind=row["kind"],
        content=row["content"],
        embedding=embedding,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        initial_energy=row["initial_energy"],
        energy_anchor=row["energy_anchor"],
        energy_updated_at=row["energy_updated_at"],
        half_life_seconds=row["half_life_seconds"],
        confidence=row["confidence"],
        quality_score=row["quality_score"],
        adoption_score=row["adoption_score"],
        context_score=row["context_score"],
        exploration_bonus=row["exploration_bonus"],
        repetition_penalty=row["repetition_penalty"],
        status=row["status"],
        safety_class=row["safety_class"],
        visibility=row["visibility"],
    )


class PostgresTraceRepository:
    """Atomic trace persistence and ranking over PostgreSQL/pgvector."""

    def __init__(self, connection: Connection[Any]) -> None:
        if not connection.autocommit:
            raise ValueError("PostgresTraceRepository requires an autocommit connection")
        self._connection = connection
        register_pgvector(connection)

    def add(self, trace: Trace) -> None:
        assert trace.energy_anchor is not None
        assert trace.energy_updated_at is not None
        params = {
            "trace_id": trace.trace_id,
            "author_agent_id": trace.author_agent_id,
            "kind": trace.kind,
            "content": trace.content,
            "embedding": _as_vector(trace.embedding),
            "created_at": trace.created_at,
            "updated_at": trace.updated_at,
            "initial_energy": trace.initial_energy,
            "energy_anchor": trace.energy_anchor,
            "energy_updated_at": trace.energy_updated_at,
            "half_life_seconds": trace.half_life_seconds,
            "confidence": trace.confidence,
            "quality_score": trace.quality_score,
            "adoption_score": trace.adoption_score,
            "context_score": trace.context_score,
            "exploration_bonus": trace.exploration_bonus,
            "repetition_penalty": trace.repetition_penalty,
            "status": trace.status,
            "safety_class": trace.safety_class,
            "visibility": trace.visibility,
        }
        with self._connection.transaction():
            self._connection.execute(
                """
                INSERT INTO traces (
                    trace_id, author_agent_id, kind, content, embedding,
                    created_at, updated_at, initial_energy, energy_anchor,
                    energy_updated_at, half_life_seconds, confidence,
                    quality_score, adoption_score, context_score,
                    exploration_bonus, repetition_penalty, status,
                    safety_class, visibility
                ) VALUES (
                    %(trace_id)s, %(author_agent_id)s, %(kind)s, %(content)s,
                    %(embedding)s, %(created_at)s, %(updated_at)s,
                    %(initial_energy)s, %(energy_anchor)s, %(energy_updated_at)s,
                    %(half_life_seconds)s, %(confidence)s, %(quality_score)s,
                    %(adoption_score)s, %(context_score)s,
                    %(exploration_bonus)s, %(repetition_penalty)s, %(status)s,
                    %(safety_class)s, %(visibility)s
                )
                """,
                params,
            )

    def get(self, trace_id: UUID) -> Trace | None:
        row = self._connection.execute(
            f"SELECT {_TRACE_COLUMNS} FROM traces WHERE trace_id = %s",
            (trace_id,),
        ).fetchone()
        return None if row is None else _trace_from_row(row)

    def add_relation(
        self,
        parent_trace_id: UUID,
        child_trace_id: UUID,
        relation_type: str,
    ) -> None:
        if not relation_type.strip():
            raise ValueError("relation_type must not be empty")
        with self._connection.transaction():
            self._connection.execute(
                """
                INSERT INTO trace_relations (
                    parent_trace_id, child_trace_id, relation_type
                ) VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (parent_trace_id, child_trace_id, relation_type),
            )

    def parents(self, child_trace_id: UUID) -> Sequence[Trace]:
        rows = self._connection.execute(
            f"""
            SELECT {_TRACE_COLUMNS}
            FROM traces t
            JOIN trace_relations r ON r.parent_trace_id = t.trace_id
            WHERE r.child_trace_id = %s
            ORDER BY r.created_at, t.trace_id
            """,
            (child_trace_id,),
        ).fetchall()
        return [_trace_from_row(row) for row in rows]

    def children(self, parent_trace_id: UUID) -> Sequence[Trace]:
        rows = self._connection.execute(
            f"""
            SELECT {_TRACE_COLUMNS}
            FROM traces t
            JOIN trace_relations r ON r.child_trace_id = t.trace_id
            WHERE r.parent_trace_id = %s
            ORDER BY r.created_at, t.trace_id
            """,
            (parent_trace_id,),
        ).fetchall()
        return [_trace_from_row(row) for row in rows]

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
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("at must be timezone-aware")
        if not kind.strip():
            raise ValueError("kind must not be empty")

        with self._connection.transaction():
            row = self._connection.execute(
                f"SELECT {_TRACE_COLUMNS} FROM traces WHERE trace_id = %s FOR UPDATE",
                (trace_id,),
            ).fetchone()
            if row is None:
                raise KeyError(trace_id)

            trace = _trace_from_row(row)
            energy_before = trace.energy_at(at)
            energy_after = reinforce_energy(
                energy_before,
                reinforcement=reinforcement,
                adoption=adoption,
                verified_utility=verified_utility,
            )
            adoption_score = min(1.0, trace.adoption_score + adoption)

            self._connection.execute(
                """
                UPDATE traces
                SET energy_anchor = %s,
                    energy_updated_at = %s,
                    updated_at = %s,
                    adoption_score = %s
                WHERE trace_id = %s
                """,
                (energy_after, at, at, adoption_score, trace_id),
            )
            self._connection.execute(
                """
                INSERT INTO trace_reinforcements (
                    reinforcement_id, trace_id, actor_agent_id, kind, amount,
                    energy_before, energy_after, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid4(),
                    trace_id,
                    actor_agent_id,
                    kind,
                    reinforcement + adoption + verified_utility,
                    energy_before,
                    energy_after,
                    at,
                ),
            )

        return replace(
            trace,
            energy_anchor=energy_after,
            energy_updated_at=at,
            updated_at=at,
            adoption_score=adoption_score,
        )

    def search(
        self,
        query_embedding: Sequence[float],
        *,
        at: datetime,
        limit: int = 10,
        weights: RetrievalWeights | None = None,
    ) -> Sequence[RetrievedTrace]:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("at must be timezone-aware")
        if limit <= 0:
            raise ValueError("limit must be positive")

        w = weights or RetrievalWeights()
        params = {
            "query_embedding": _as_vector(query_embedding),
            "at": at,
            "limit": limit,
            "semantic_weight": w.semantic,
            "energy_weight": w.energy,
            "quality_weight": w.quality,
            "context_weight": w.context,
            "adoption_weight": w.adoption,
            "exploration_weight": w.exploration,
            "repetition_weight": w.repetition_penalty,
        }
        rows = self._connection.execute(
            f"""
            WITH candidates AS (
                SELECT {_TRACE_COLUMNS},
                    1.0 - (embedding <=> %(query_embedding)s) AS semantic_similarity,
                    energy_anchor * power(
                        2.0,
                        -GREATEST(
                            0.0,
                            EXTRACT(EPOCH FROM (%(at)s - energy_updated_at))::double precision
                        ) / half_life_seconds
                    ) AS current_energy
                FROM traces
                WHERE embedding IS NOT NULL AND status = 'active'
            ), ranked AS (
                SELECT *,
                    %(semantic_weight)s * semantic_similarity
                    + %(energy_weight)s * current_energy
                    + %(quality_weight)s * quality_score
                    + %(context_weight)s * context_score
                    + %(adoption_weight)s * adoption_score
                    + %(exploration_weight)s * exploration_bonus
                    - %(repetition_weight)s * repetition_penalty
                    AS retrieval_score
                FROM candidates
            )
            SELECT * FROM ranked
            ORDER BY retrieval_score DESC, created_at DESC, trace_id
            LIMIT %(limit)s
            """,
            params,
        ).fetchall()

        return [
            RetrievedTrace(
                trace=_trace_from_row(row),
                semantic_similarity=float(row["semantic_similarity"]),
                energy=float(row["current_energy"]),
                retrieval_score=float(row["retrieval_score"]),
            )
            for row in rows
        ]
