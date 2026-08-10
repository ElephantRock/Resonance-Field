from __future__ import annotations

from uuid import UUID

import pytest

from resonance.experiments.decay_metrics import (
    jaccard_turnover,
    mean_rank_displacement,
    summarize_decay_observations,
)

A = UUID("00000000-0000-0000-0000-000000000001")
B = UUID("00000000-0000-0000-0000-000000000002")
C = UUID("00000000-0000-0000-0000-000000000003")
D = UUID("00000000-0000-0000-0000-000000000004")


def _row(
    cycle: int,
    phase: str,
    rank: int,
    trace_id: UUID,
    age: float,
) -> dict[str, object]:
    return {
        "cycle": cycle,
        "phase": phase,
        "neighborhood": "alpha",
        "rank": rank,
        "trace_id": trace_id,
        "trace_age_seconds": age,
    }


def test_rank_and_set_turnover_metrics() -> None:
    assert jaccard_turnover((A, B, C), (B, C, D)) == pytest.approx(0.5)
    assert mean_rank_displacement((A, B, C), (B, A, C)) == pytest.approx(2 / 3)


def test_decay_summary_detects_top_turnover_and_confirmed_resurrection() -> None:
    rows = [
        _row(0, "pre", 1, A, 100.0),
        _row(0, "pre", 2, B, 300.0),
        _row(0, "post", 1, B, 300.0),
        _row(0, "post", 2, A, 100.0),
        _row(1, "pre", 1, B, 330.0),
        _row(1, "pre", 2, C, 30.0),
        _row(1, "post", 1, C, 30.0),
        _row(1, "post", 2, B, 330.0),
    ]
    metrics = summarize_decay_observations(
        rows,
        old_age_seconds=240.0,
        resurrection_rows=({"confirmed": True}, {"confirmed": False}),
    )
    assert metrics["top_turnover_rate"] == pytest.approx(1.0)
    assert metrics["same_cycle_top_change_rate"] == pytest.approx(1.0)
    assert metrics["old_trace_retrieval_share"] == pytest.approx(0.5)
    assert metrics["unique_top_traces"] == 2
    assert metrics["confirmed_resurrections"] == 1
    assert metrics["resurrection_confirmation_rate"] == pytest.approx(0.5)
