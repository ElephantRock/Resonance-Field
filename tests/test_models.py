from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from resonance.substrate.models import Trace


def make_trace(**overrides: object) -> Trace:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    values: dict[str, object] = {
        "kind": "HYPOTHESIS",
        "content": "A test trace",
        "created_at": created_at,
        "updated_at": created_at,
        "initial_energy": 1.0,
        "half_life_seconds": 3600.0,
    }
    values.update(overrides)
    return Trace(**values)  # type: ignore[arg-type]


def test_trace_uses_initial_energy_as_decay_anchor() -> None:
    trace = make_trace()
    assert trace.energy_anchor == 1.0
    assert trace.energy_updated_at == trace.created_at
    assert trace.energy_at(trace.created_at + timedelta(hours=1)) == pytest.approx(0.5)


def test_trace_ids_are_unique() -> None:
    assert make_trace().trace_id != make_trace().trace_id


def test_embedding_dimension_is_fixed_for_v01() -> None:
    with pytest.raises(ValueError, match="1536"):
        make_trace(embedding=(1.0, 2.0, 3.0))


def test_trace_rejects_naive_timestamps() -> None:
    naive = datetime(2026, 1, 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        make_trace(created_at=naive, updated_at=naive)
