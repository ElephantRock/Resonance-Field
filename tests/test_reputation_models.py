from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from resonance.reputation import ReputationState

AGENT = UUID("00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 3, 1, tzinfo=UTC)


def test_reputation_score_is_beta_posterior_mean() -> None:
    state = ReputationState(AGENT, "task_success", "alpha", 4.0, 2.0, NOW)
    assert state.score == pytest.approx(2 / 3)
    assert state.evidence_mass == pytest.approx(4.0)


def test_reputation_requires_positive_beta_parameters() -> None:
    with pytest.raises(ValueError):
        ReputationState(AGENT, "task_success", "alpha", 0.0, 1.0, NOW)
