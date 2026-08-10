from __future__ import annotations

import math
from uuid import uuid4

import pytest

from resonance.agents.actions import ActionType
from resonance.experiments.metrics import (
    agent_action_mutual_information,
    gini,
    normalized_specialization,
    summarize_behavior,
)


def test_specialization_is_one_for_single_action() -> None:
    assert normalized_specialization({ActionType.WRITE_TRACE.value: 20}) == pytest.approx(1.0)


def test_specialization_is_zero_for_uniform_full_action_space() -> None:
    counts = {action.value: 1 for action in ActionType}
    assert normalized_specialization(counts) == pytest.approx(0.0, abs=1e-12)


def test_mutual_information_detects_agent_action_separation() -> None:
    agent_a = uuid4()
    agent_b = uuid4()
    rows = [(agent_a, ActionType.WRITE_TRACE.value)] * 10 + [
        (agent_b, ActionType.BID_TASK.value)
    ] * 10
    assert agent_action_mutual_information(rows) == pytest.approx(math.log(2.0))


def test_gini_handles_equal_and_unequal_balances() -> None:
    assert gini([10, 10, 10]) == pytest.approx(0.0)
    assert gini([0, 0, 30]) == pytest.approx(2 / 3)


def test_behavior_summary_keeps_zero_spend_agents_in_compute_distribution() -> None:
    agent_a = uuid4()
    agent_b = uuid4()
    summary = summarize_behavior(
        [(agent_a, ActionType.WRITE_TRACE.value, 3)],
        {agent_a: 7, agent_b: 10},
    )
    assert summary["agent_count"] == 2
    assert summary["total_compute_spent"] == 3
    assert summary["compute_gini"] == pytest.approx(0.5)
