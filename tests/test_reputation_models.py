from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from resonance.experiments.reputation_models import ReputationExperimentConfig
from resonance.reputation import ReputationState

AGENT = UUID("00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 3, 1, tzinfo=UTC)


def _experiment_config() -> ReputationExperimentConfig:
    return ReputationExperimentConfig(
        name="test-reputation",
        agents=4,
        cycles=12,
        cycle_seconds=10,
        shift_cycle=6,
        snapshot_every=3,
        initial_credits=100,
        domains=("alpha", "beta"),
        candidate_count=2,
        task_budget=4,
        bid_deadline_seconds=5,
        fast_half_life_seconds=30.0,
        slow_half_life_seconds=120.0,
        evidence_initial_energy=0.9,
        reputation_weight=0.4,
        base_success_probability=0.4,
        practice_gain=0.1,
        maximum_success_probability=0.9,
        early_post_shift_cycles=3,
        late_post_shift_cycles=3,
    )


def test_reputation_score_is_beta_posterior_mean() -> None:
    state = ReputationState(AGENT, "task_success", "alpha", 4.0, 2.0, NOW)
    assert state.score == pytest.approx(2 / 3)
    assert state.evidence_mass == pytest.approx(4.0)


def test_reputation_requires_positive_beta_parameters() -> None:
    with pytest.raises(ValueError):
        ReputationState(AGENT, "task_success", "alpha", 0.0, 1.0, NOW)


def test_only_treatment_arms_enable_reputation_scoring() -> None:
    config = _experiment_config()
    assert config.reputation_enabled("slow_reputation")
    assert config.reputation_enabled("fast_reputation")
    assert not config.reputation_enabled("slow_no_reputation")
    assert not config.reputation_enabled("fast_no_reputation")
