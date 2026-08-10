from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from resonance.experiments.adaptive_campaign import (
    CampaignConfig,
    CampaignPolicy,
    baseline_bid_score,
    is_feasible,
    run_campaign,
)
from resonance.market.models import MarketBid, MarketTask, bid_score


TASK_ID = UUID("00000000-0000-0000-0000-000000000001")
AGENT_ID = UUID("00000000-0000-0000-0000-000000000002")
ESCROW_ID = UUID("00000000-0000-0000-0000-000000000003")
BID_ID = UUID("00000000-0000-0000-0000-000000000004")
NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _tiny_config() -> CampaignConfig:
    return CampaignConfig(
        name="adaptive-test",
        agents=8,
        domain_count=3,
        cycles=72,
        shift_period=24,
        trace_half_lives=(2.0, 8.0),
        candidate_count=4,
        task_budget=10,
        bid_deadline_seconds=20,
        base_success_probability=0.35,
        maximum_success_probability=0.85,
        practice_scale=5.0,
        seeds=(11, 22),
        holdout_seeds=(33, 44),
        holdout_cycles=96,
        holdout_shift_period=24,
        holdout_trace_half_lives=(2.0, 6.0),
        holdout_candidate_count=4,
        success_tolerance=0.02,
        incumbent_tolerance=0.08,
    )


def test_campaign_bid_score_matches_production_market_score() -> None:
    task = MarketTask(
        task_id=TASK_ID,
        requester_agent_id=AGENT_ID,
        escrow_account_id=ESCROW_ID,
        description="test",
        budget=10,
        deadline=NOW + timedelta(seconds=20),
        created_at=NOW,
    )
    bid = MarketBid(
        bid_id=BID_ID,
        task_id=TASK_ID,
        bidder_agent_id=AGENT_ID,
        price=6,
        confidence=0.7,
        estimated_completion_seconds=8,
        strategy_summary="test",
        submitted_at=NOW + timedelta(seconds=1),
    )
    expected = bid_score(task, bid)
    actual = baseline_bid_score(
        confidence=0.7,
        price=6,
        budget=10,
        completion_seconds=8,
        available_seconds=20,
    )
    assert actual == pytest.approx(expected)


def test_quality_and_plasticity_are_hard_feasibility_constraints() -> None:
    config = _tiny_config()
    control = {"success_rate": 0.50, "early_incumbent_share": 0.10}
    assert is_feasible(
        {"success_rate": 0.49, "early_incumbent_share": 0.18},
        control,
        config,
    )
    assert not is_feasible(
        {"success_rate": 0.47, "early_incumbent_share": 0.10},
        control,
        config,
    )
    assert not is_feasible(
        {"success_rate": 0.50, "early_incumbent_share": 0.20},
        control,
        config,
    )


def test_campaign_runs_exactly_ten_sequential_experiments(tmp_path) -> None:
    summary = run_campaign(
        _tiny_config(),
        code_sha="test-sha",
        output_dir=tmp_path,
    )
    experiments = summary["experiments"]
    assert [item["number"] for item in experiments] == list(range(4, 14))
    assert experiments[0]["focus"] == "freshness_screen"
    assert all(item["next_experiment_focus"] for item in experiments[:-1])
    assert experiments[-1]["next_experiment_focus"] is None
    assert isinstance(experiments[-1]["validated"], bool)

    for item in experiments:
        labels = {arm["label"] for arm in item["arms"]}
        assert item["selected_label"] in labels

    assert (tmp_path / "campaign.json").exists()
    assert (tmp_path / "experiment-004.json").exists()
    assert (tmp_path / "experiment-013.json").exists()
    assert (tmp_path / "experiment-arms.csv").exists()
    assert (tmp_path / "cells.csv").exists()


def test_no_reputation_policy_has_no_reputation_weight() -> None:
    policy = CampaignPolicy()
    assert policy.mode == "none"
    assert policy.weight == 0.0
    assert policy.label == "no_reputation"
