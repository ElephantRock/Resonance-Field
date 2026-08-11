from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from resonance.experiments.matching_campaign import objective_score
from resonance.experiments.matching_checkpoint import _hard_gate
from resonance.experiments.matching_config import (
    MatchingObjectiveSpec,
    load_matching_config,
    with_blend,
)
from resonance.market.models import MarketBid, MarketTask, bid_score

_CONFIG = Path("configs/experiments/matching-objective-093-098.json")


def _task(cycle: int = 0) -> MarketTask:
    start = datetime(2026, 8, 11, tzinfo=UTC)
    return MarketTask(
        task_id=uuid4(),
        requester_agent_id=uuid4(),
        escrow_account_id=uuid4(),
        description="matching objective test",
        budget=100,
        created_at=start,
        deadline=start + timedelta(seconds=20),
        success_condition={"campaign_cycle": cycle},
    )


def _bid(task: MarketTask, *, confidence: float, price: int, speed: int) -> MarketBid:
    return MarketBid(
        bid_id=uuid4(),
        task_id=task.task_id,
        bidder_agent_id=uuid4(),
        price=price,
        confidence=confidence,
        estimated_completion_seconds=speed,
        strategy_summary="sealed test bid",
        submitted_at=task.created_at + timedelta(seconds=1),
    )


def test_baseline_objective_is_exact_production_score() -> None:
    task = _task()
    bid = _bid(task, confidence=0.8, price=55, speed=8)
    assert objective_score(task, bid, MatchingObjectiveSpec()) == bid_score(task, bid)


def test_confidence_light_objective_can_change_winner_on_same_bids() -> None:
    task = _task()
    confidence_bid = _bid(task, confidence=0.95, price=90, speed=18)
    efficient_bid = _bid(task, confidence=0.55, price=30, speed=4)
    spec = MatchingObjectiveSpec(
        mode="weighted",
        confidence_weight=0.15,
        price_weight=0.50,
        speed_weight=0.35,
    )
    assert bid_score(task, confidence_bid) > bid_score(task, efficient_bid)
    assert objective_score(task, efficient_bid, spec) > objective_score(task, confidence_bid, spec)


def test_restoration_returns_exactly_to_production_objective() -> None:
    task = _task(cycle=20)
    bid = _bid(task, confidence=0.7, price=45, speed=6)
    spec = MatchingObjectiveSpec(
        mode="weighted",
        confidence_weight=0.15,
        price_weight=0.50,
        speed_weight=0.35,
        restore_after_cycle=18,
    )
    assert objective_score(task, bid, spec) == bid_score(task, bid)


def test_blend_changes_strength_without_changing_objective_family() -> None:
    spec = MatchingObjectiveSpec(
        mode="capped_confidence",
        confidence_cap=0.65,
    )
    half = with_blend(spec, 0.5)
    assert half.mode == spec.mode
    assert half.confidence_cap == spec.confidence_cap
    assert half.blend == 0.5


def _metrics() -> dict[str, float]:
    return {
        "success_rate": 0.50,
        "early_incumbent_share": 0.10,
        "identity_early_incumbent_share": 0.10,
        "mean_winner_hhi": 0.18,
        "late_public_knowledge_coverage": 0.80,
        "public_knowledge_coverage": 0.80,
        "late_cultural_lineage_hhi": 0.40,
        "cultural_lineage_hhi": 0.40,
        "mean_winning_price_fraction": 0.60,
        "credit_gini": 0.10,
        "objective_override_rate": 0.0,
        "same_bid_logical_improvement": 0.0,
        "mean_selected_bid_confidence": 0.70,
        "selected_max_confidence_share": 0.80,
        "exit_count": 0.0,
    }


def _arm(metrics: dict[str, float]) -> dict[str, object]:
    return {
        "metrics": metrics,
        "invariants": {
            "ledger_conserved": True,
            "objective_replay_exact": True,
            "candidate_set_baseline_exact": True,
            "matching_observation_complete": True,
            "identity_turnover_absent": True,
            "matching_reputation_neutral": True,
        },
    }


def test_hard_gate_requires_logical_and_exact_bid_causal_effect() -> None:
    config, _ = load_matching_config(_CONFIG)
    control_metrics = _metrics()
    candidate_metrics = _metrics()
    candidate_metrics.update(
        {
            "success_rate": 0.49,
            "early_incumbent_share": 0.07,
            "identity_early_incumbent_share": 0.07,
            "late_public_knowledge_coverage": 0.79,
            "objective_override_rate": 0.15,
            "same_bid_logical_improvement": 0.02,
            "mean_selected_bid_confidence": 0.60,
        }
    )
    hard, feasible, effects = _hard_gate(
        _arm(candidate_metrics),
        _arm(control_metrics),
        config=config,
    )
    assert feasible
    assert hard
    assert effects["logical_incumbent_reduction"] >= 0.02
    assert effects["objective_override_rate"] >= 0.08

    candidate_metrics["same_bid_logical_improvement"] = 0.0
    hard, _, _ = _hard_gate(
        _arm(candidate_metrics),
        _arm(control_metrics),
        config=config,
    )
    assert not hard
