from __future__ import annotations

from pathlib import Path

from resonance.experiments.trajectory_hysteresis_campaign import (
    match_histories,
    trajectory_observables,
)
from resonance.experiments.trajectory_hysteresis_config import load_trajectory_hysteresis_config

CONFIG = Path("configs/experiments/trajectory-hysteresis-117-122.json")


def _record(history: str, seed: int, offset: float = 0.0) -> dict[str, object]:
    features = {
        "winner_domain_mi": 0.20 + offset,
        "success_domain_hhi": 0.30 + offset,
        "practice_concentration": 0.25 + offset,
        "incumbent_share": 0.45 + offset,
        "activation_regime_alignment": 0.35 + offset,
    }
    return {
        "history_kind": history,
        "seed": seed,
        "features": features,
        "trajectory": {
            "path_length": 0.4 + offset,
            "basin_transitions": 2.0,
            "momentum": 0.1 + offset,
            "trajectory_roughness": 0.2 + offset,
        },
    }


def test_frozen_config_loads() -> None:
    protocol, config_hash = load_trajectory_hysteresis_config(CONFIG)
    assert len(config_hash) == 64
    assert protocol.feedback_strength == 0.5
    assert protocol.history_feedback_strength == 0.25
    assert protocol.anneal_epsilon == 0.10
    assert protocol.standard.activation_cycle == 54
    assert protocol.timing_control.activation_cycle == 63
    assert protocol.holdout.shift_period == 15


def test_tolerance_matching_is_deterministic_and_without_replacement() -> None:
    protocol, _ = load_trajectory_hysteresis_config(CONFIG)
    records = [
        _record("aligned_history", 1, 0.00),
        _record("aligned_history", 2, 0.03),
        _record("counter_history", 10, 0.01),
        _record("counter_history", 11, 0.04),
    ]
    result = match_histories(
        records,
        left_history="aligned_history",
        right_history="counter_history",
        protocol=protocol,
    )
    assert result["matched_count"] == 2
    assert result["support"] == 1.0
    pairs = result["pairs"]
    assert pairs[0]["left_seed"] == 1
    assert pairs[0]["right_seed"] == 10
    assert pairs[1]["left_seed"] == 2
    assert pairs[1]["right_seed"] == 11


def test_trajectory_observables_are_bounded_and_reproducible() -> None:
    domains = ("alpha", "beta", "gamma")
    rows = []
    for cycle in range(54):
        domain = cycle % len(domains)
        regime = cycle // 18
        rows.append(
            {
                "cycle": cycle,
                "domain_index": domain,
                "winner_slot": (domain + regime) % 4,
                "required_skill": domains[(domain + regime) % len(domains)],
                "success": cycle % 4 != 0,
            }
        )
    names = (
        "winner_domain_mi",
        "success_domain_hhi",
        "practice_concentration",
        "incumbent_share",
        "activation_regime_alignment",
    )
    first = trajectory_observables(
        rows,
        activation_cycle=54,
        shift_period=18,
        domains=domains,
        feature_names=names,
    )
    second = trajectory_observables(
        rows,
        activation_cycle=54,
        shift_period=18,
        domains=domains,
        feature_names=names,
    )
    assert first == second
    assert float(first["path_length"]) >= 0.0
    assert float(first["basin_transitions"]) >= 0.0
    assert -1.0 <= float(first["momentum"]) <= 1.0
    assert float(first["trajectory_roughness"]) >= 0.0
