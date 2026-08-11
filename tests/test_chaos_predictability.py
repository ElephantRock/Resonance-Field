from __future__ import annotations

from pathlib import Path

from resonance.experiments.chaos_predictability_campaign import (
    basin_occupancy,
    forecast_horizon,
    scaling_evaluation,
    select_family,
)
from resonance.experiments.chaos_predictability_config import load_chaos_predictability_config


CONFIG = Path("configs/experiments/chaos-predictability-123-128.json")


def _protocol():
    return load_chaos_predictability_config(CONFIG)[0]


def _pair(family: str, epsilon: float, horizon: int, *, basin: str = "other_nontrivial"):
    return {
        "family": family,
        "epsilon": epsilon,
        "feedback_strength": 0.5,
        "horizons": {"micro": horizon, "meso": horizon, "macro": horizon},
        "saturation": {
            "micro": {"bounded": True, "mean_final_regime": 0.25},
            "meso": {"bounded": True, "mean_final_regime": 0.20},
            "macro": {"bounded": True, "mean_final_regime": 0.15},
        },
        "nontrivial": True,
        "basin_disagreement": basin != "other_nontrivial",
        "perturbed_basin": basin,
    }


def test_config_is_frozen() -> None:
    protocol = _protocol()
    assert protocol.epsilons == (1e-6, 1e-4, 1e-2, 1e-1, 1.0)
    assert protocol.standard.cycles == 126
    assert protocol.holdout.shift_period == 15
    assert protocol.feedback_strength == 0.5


def test_forecast_horizon_uses_persistent_crossing() -> None:
    series = [
        {"cycle": 0, "micro_distance": 0.0},
        {"cycle": 1, "micro_distance": 0.11},
        {"cycle": 2, "micro_distance": 0.01},
        {"cycle": 3, "micro_distance": 0.12},
        {"cycle": 4, "micro_distance": 0.13},
        {"cycle": 5, "micro_distance": 0.14},
    ]
    assert forecast_horizon(
        series,
        key="micro_distance",
        threshold=0.10,
        hits=3,
        window=5,
        cycles=6,
    ) == 1


def test_scaling_evaluation_can_classify_organizational_chaos() -> None:
    protocol = _protocol()
    pairs = []
    horizons = [110, 90, 70, 50, 30]
    for family in ("bid_confidence", "trace_energy"):
        for epsilon, horizon in zip(protocol.epsilons, horizons, strict=True):
            for _ in range(4):
                pairs.append(_pair(family, epsilon, horizon, basin="lock_in"))
    evaluation = scaling_evaluation(pairs, protocol=protocol, cycles=protocol.standard.cycles)
    assert evaluation["bid_confidence"]["classification"] == "organizationally_chaotic"
    assert evaluation["trace_energy"]["scales"]["micro"]["scaling_gate"] is True


def test_family_selection_tie_breaks_to_bid_confidence() -> None:
    protocol = _protocol()
    pairs = []
    for family in ("bid_confidence", "trace_energy"):
        for epsilon in protocol.epsilons:
            pairs.append(_pair(family, epsilon, 100))
    evaluation = scaling_evaluation(pairs, protocol=protocol, cycles=protocol.standard.cycles)
    assert select_family(evaluation, pairs, cycles=protocol.standard.cycles) == "bid_confidence"


def test_basin_occupancy_is_grouped_by_epsilon() -> None:
    pairs = [
        _pair("bid_confidence", 1e-6, 20, basin="lock_in"),
        _pair("bid_confidence", 1e-6, 20, basin="plastic_high_quality"),
    ]
    occupancy = basin_occupancy(pairs)
    assert occupancy["1e-06"]["lock_in"] == 0.5
    assert occupancy["1e-06"]["plastic_high_quality"] == 0.5
