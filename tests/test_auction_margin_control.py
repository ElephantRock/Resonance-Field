from __future__ import annotations

from resonance.experiments.auction_margin_campaign import _radius, evaluate_cohort
from resonance.experiments.auction_margin_checkpoint import _local_gate
from resonance.experiments.auction_margin_config import load_auction_margin_config


def test_frozen_auction_margin_config() -> None:
    config, config_hash = load_auction_margin_config(
        "configs/experiments/auction-margin-129-134.json"
    )
    assert len(config_hash) == 64
    assert config.feedback_strength == 0.5
    assert config.near_radius == 0.01
    assert config.buffered_radius == 1.0
    assert config.probe_epsilon == 0.1
    assert config.standard.activation_cycle == 36
    assert config.timing_transfer.activation_cycle == 54
    assert config.holdout.activation_cycle == 30
    assert len(config.discovery_seeds) == 12


def test_audit_consistent_radius_coordinate() -> None:
    winning = 0.80
    losing = 0.71
    confidence = 0.50
    assert abs(_radius(winning, losing, confidence) - 0.4) < 1e-12


def test_local_gate_requires_exact_near_cross_buffered_no_cross() -> None:
    records = [
        {
            "near_crossed": True,
            "buffered_crossed": False,
            "first_changed_winner_cycle": 36,
            "preactivation_equal": True,
            "all_invariants": True,
        }
        for _ in range(4)
    ]
    result = _local_gate(records, activation_cycle=36)
    assert result["validated"] is True
    records[0]["buffered_crossed"] = True
    assert _local_gate(records, activation_cycle=36)["validated"] is False


def test_propagation_evaluation_uses_frozen_gates() -> None:
    config, _ = load_auction_margin_config("configs/experiments/auction-margin-129-134.json")
    pairs = [
        {
            "persistent_macro_crossed": index < 4,
            "basin_disagreement": index < 3,
            "bounded_all_scales": index < 8,
            "success_loss": 0.01,
            "knowledge_loss": 0.05,
            "all_invariants": True,
        }
        for index in range(10)
    ]
    evaluation = evaluate_cohort(pairs, config=config)
    assert evaluation["macro_crossing_share"] == 0.4
    assert evaluation["basin_disagreement_share"] == 0.3
    assert evaluation["bounded_share"] == 0.8
    assert evaluation["organizational_propagation"] is True

    pairs[0]["success_loss"] = 0.2
    evaluation = evaluate_cohort(pairs, config=config)
    assert evaluation["mean_success_loss"] > config.maximum_success_loss
    assert evaluation["organizational_propagation"] is False
