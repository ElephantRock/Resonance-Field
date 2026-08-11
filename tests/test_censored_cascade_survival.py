from __future__ import annotations

import json

from resonance.experiments.censored_cascade_survival_audit import (
    _auc_positive_higher,
    _first_full_regime_sync,
    cox_univariate,
)


def test_cox_direction_for_slower_recovery_at_high_predictor() -> None:
    durations = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    events = [1, 1, 1, 1, 0, 0]
    predictor = [-2.0, -1.0, -0.5, 0.5, 1.0, 2.0]
    model = cox_univariate(durations, events, predictor)
    assert model["converged"] is True
    assert float(model["beta"]) < 0.0
    assert float(model["hazard_ratio"]) < 1.0


def test_auc_positive_higher() -> None:
    assert _auc_positive_higher([3.0, 4.0], [1.0, 2.0]) == 1.0
    assert _auc_positive_higher([1.0], [1.0]) == 0.5


def test_full_regime_sync_from_cumulative_winner_damage() -> None:
    rows = []
    damage = 0
    for cycle in range(8):
        if cycle in {2, 3}:
            damage += 1
        rows.append(
            {
                "cycle": str(cycle),
                "micro_components": json.dumps(
                    {"winner_damage": damage / (cycle + 1)}
                ),
            }
        )
    start, observed = _first_full_regime_sync(
        rows, activation=2, cycles=8, shift_period=4
    )
    assert observed is True
    assert start == 4
