from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from resonance.substrate.models import Trace
from resonance.substrate.postgres import PostgresTraceRepository
from resonance.substrate.retrieval import RetrievalWeights

pytestmark = pytest.mark.integration


def _apply_migration(connection: psycopg.Connection[dict[str, object]]) -> None:
    migration = Path("migrations/001_initial.sql").read_text()
    for statement in migration.split(";"):
        if statement.strip():
            connection.execute(statement)


@pytest.fixture
def repository() -> PostgresTraceRepository:
    dsn = os.getenv("RESONANCE_TEST_DSN")
    if not dsn:
        pytest.skip("RESONANCE_TEST_DSN is not configured")

    connection = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
    _apply_migration(connection)
    connection.execute("TRUNCATE trace_reinforcements, trace_relations, traces CASCADE")
    repository = PostgresTraceRepository(connection)
    try:
        yield repository
    finally:
        connection.close()


def _embedding() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 1535


def _trace(
    *,
    content: str,
    energy: float,
    half_life_seconds: float,
    created_at: datetime,
) -> Trace:
    return Trace(
        kind="HYPOTHESIS",
        content=content,
        embedding=_embedding(),
        created_at=created_at,
        updated_at=created_at,
        initial_energy=energy,
        half_life_seconds=half_life_seconds,
    )


def test_decay_changes_retrieval_ordering(repository: PostgresTraceRepository) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    fast_decay = _trace(
        content="Initially salient, rapidly cooling",
        energy=1.0,
        half_life_seconds=3600.0,
        created_at=start,
    )
    slow_decay = _trace(
        content="Lower initial energy, longer memory",
        energy=0.4,
        half_life_seconds=24 * 3600.0,
        created_at=start,
    )
    repository.add(fast_decay)
    repository.add(slow_decay)

    energy_only = RetrievalWeights(
        semantic=0.0,
        energy=1.0,
        quality=0.0,
        context=0.0,
        adoption=0.0,
        exploration=0.0,
        repetition_penalty=0.0,
    )

    initial = repository.search(_embedding(), at=start, limit=2, weights=energy_only)
    later = repository.search(
        _embedding(),
        at=start + timedelta(hours=4),
        limit=2,
        weights=energy_only,
    )

    assert [item.trace.trace_id for item in initial] == [
        fast_decay.trace_id,
        slow_decay.trace_id,
    ]
    assert [item.trace.trace_id for item in later] == [
        slow_decay.trace_id,
        fast_decay.trace_id,
    ]
    assert later[0].energy > later[1].energy


def test_lineage_relations_round_trip(repository: PostgresTraceRepository) -> None:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    parent = _trace(
        content="Parent idea",
        energy=0.8,
        half_life_seconds=3600.0,
        created_at=created_at,
    )
    child = _trace(
        content="Offspring idea",
        energy=0.8,
        half_life_seconds=3600.0,
        created_at=created_at,
    )
    repository.add(parent)
    repository.add(child)
    repository.add_relation(parent.trace_id, child.trace_id, "crossover")

    assert [trace.trace_id for trace in repository.parents(child.trace_id)] == [parent.trace_id]
    assert [trace.trace_id for trace in repository.children(parent.trace_id)] == [child.trace_id]


def test_reinforcement_resets_decay_anchor(repository: PostgresTraceRepository) -> None:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    trace = _trace(
        content="Reinforced idea",
        energy=1.0,
        half_life_seconds=3600.0,
        created_at=created_at,
    )
    repository.add(trace)

    reinforced_at = created_at + timedelta(hours=1)
    reinforced = repository.reinforce(
        trace.trace_id,
        at=reinforced_at,
        reinforcement=1.0,
    )

    assert reinforced.energy_anchor == pytest.approx(0.6)
    assert reinforced.energy_updated_at == reinforced_at
    assert repository.get(trace.trace_id) == reinforced
