from __future__ import annotations

from pathlib import Path

from resonance.experiments.delayed_phase_campaign import (
    post_activation_incumbency,
    preactivation_exact,
    state_features,
    validate_classifier,
)
from resonance.experiments.delayed_phase_config import load_delayed_phase_config


CONFIG = Path("configs/experiments/delayed-phase-111-116.json")


def _row(cycle: int, domain: int, winner: int, success: bool = True) -> dict[str, object]:
    return {
        "cycle": cycle,
        "regime": cycle // 2,
        "task_domain": f"d{domain}",
        "domain_index": domain,
        "required_skill": f"d{(domain + cycle // 2) % 2}",
        "winner_slot": winner,
        "success": success,
        "recorded_positive": success,
        "reputation_score": 0.5,
        "winning_price": 7,
        "task_budget": 12,
    }


def _event(cycle: int, domain: int) -> dict[str, object]:
    return {
        "cycle": cycle,
        "baseline_domain_index": domain,
        "generated_domain_index": domain,
        "feedback_strength": 0.0,
        "rolling_success_counts": [cycle, 0],
        "feedback_branch_taken": False,
        "generated_domain_source": "baseline",
    }


def test_config_is_frozen() -> None:
    config, digest = load_delayed_phase_config(CONFIG)
    assert config.feedback_strength == 0.5
    assert config.standard.burn_in_cycles == 36
    assert config.timing_transfer.burn_in_cycles == 54
    assert config.holdout.shift_period == 15
    assert len(config.discovery_seeds) == 12
    assert len(digest) == 64


def test_preactivation_exact_compares_normalized_state() -> None:
    rows = [_row(0, 0, 1), _row(1, 1, 2)]
    events = [_event(0, 0), _event(1, 1)]
    assert preactivation_exact(rows, rows, events, events, activation_cycle=2)
    changed = [dict(rows[0]), dict(rows[1])]
    changed[1]["winner_slot"] = 3
    assert not preactivation_exact(rows, changed, events, events, activation_cycle=2)


def test_state_features_are_bounded() -> None:
    rows = [
        _row(0, 0, 0),
        _row(1, 1, 1),
        _row(2, 0, 0),
        _row(3, 1, 1),
    ]
    features = state_features(
        rows,
        activation_cycle=4,
        shift_period=2,
        domains=("d0", "d1"),
    )
    assert set(features) == {
        "winner_domain_mi",
        "success_domain_hhi",
        "practice_concentration",
        "incumbent_share",
        "activation_regime_alignment",
    }
    assert all(0.0 <= value <= 1.0 for value in features.values())


def test_post_activation_incumbency_uses_four_transitions() -> None:
    rows = []
    for cycle in range(12):
        domain = cycle % 2
        rows.append(_row(cycle, domain, domain))
    mean, values = post_activation_incumbency(
        rows,
        activation_cycle=4,
        shift_period=2,
        cycles=12,
    )
    assert values == [1.0, 1.0, 1.0, 1.0]
    assert mean == 1.0


def test_frozen_classifier_validation() -> None:
    protocol, _ = load_delayed_phase_config(CONFIG)
    records = []
    for value, delta in ((0.1, -0.2), (0.2, -0.1), (0.8, 0.1), (0.9, 0.2)):
        records.append(
            {
                "preactivation_exact": True,
                "state_features_exact": True,
                "all_cell_invariants": True,
                "delta_incumbency": delta,
                "success_effect": 0.0,
                "knowledge_effect": 0.0,
                "features": {
                    "winner_domain_mi": value,
                    "success_domain_hhi": 0.2,
                    "practice_concentration": 0.2,
                    "incumbent_share": 0.2,
                    "activation_regime_alignment": 0.2,
                },
            }
        )
    classifier = {
        "feature": "winner_domain_mi",
        "direction": "positive_if_high",
        "threshold": 0.5,
    }
    result = validate_classifier(records, classifier, protocol)
    assert result["accuracy"] == 1.0
    assert result["balanced_accuracy"] == 1.0
    assert result["directional_separation"] is True
    assert result["validation_gate"] is True
