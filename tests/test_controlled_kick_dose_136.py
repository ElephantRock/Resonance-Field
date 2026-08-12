from __future__ import annotations

import math
from pathlib import Path

from resonance.experiments.controlled_kick_dose_136 import (
    cox_ph,
    kaplan_meier,
    ols_linear,
    schedule_for_seed,
)
from resonance.experiments.controlled_kick_dose_config import load_controlled_kick_dose_config

_CONFIG = Path("configs/experiments/controlled-kick-dose-135-137.json")


def test_discovery_timing_schedule_is_frozen_and_balanced() -> None:
    config, _ = load_controlled_kick_dose_config(_CONFIG)
    assignments = {
        seed: schedule_for_seed(config, seed=seed, cohort_seeds=config.discovery_seeds)
        for seed in config.discovery_seeds
    }
    assert sum(dose == 1 for dose, _ in assignments.values()) == 12
    assert sum(dose == 2 for dose, _ in assignments.values()) == 12
    assert sum(dose == 4 for dose, _ in assignments.values()) == 12
    for dose in config.doses:
        schedules = [
            schedule for value_dose, schedule in assignments.values() if value_dose == dose
        ]
        mean_positions = [sum(schedule) / len(schedule) for schedule in schedules]
        assert math.isclose(sum(mean_positions) / len(mean_positions), 37.5)
    k1_cycles = [cycle for dose, schedule in assignments.values() if dose == 1 for cycle in schedule]
    assert {cycle: k1_cycles.count(cycle) for cycle in range(36, 40)} == {
        36: 3,
        37: 3,
        38: 3,
        39: 3,
    }
    k2_cycles = [cycle for dose, schedule in assignments.values() if dose == 2 for cycle in schedule]
    assert {cycle: k2_cycles.count(cycle) for cycle in range(36, 40)} == {
        36: 6,
        37: 6,
        38: 6,
        39: 6,
    }
    assert {
        schedule for dose, schedule in assignments.values() if dose == 4
    } == {(36, 37, 38, 39)}


def test_cox_ph_reports_per_unit_log_dose_and_ci() -> None:
    dose = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0]
    duration = [2, 8, 5, 3, 9, 6, 4, 10, 7]
    event = [1, 1, 1, 1, 1, 1, 1, 1, 0]
    fit = cox_ph(duration, event, [[value] for value in dose], names=("log2_dose",))
    assert fit["stable"] is True
    coefficient = fit["coefficients"]["log2_dose"]
    assert coefficient["beta"] < 0
    assert math.isclose(coefficient["hazard_ratio"], math.exp(coefficient["beta"]))
    assert coefficient["ci95_lower"] < coefficient["hazard_ratio"] < coefficient["ci95_upper"]


def test_ols_uses_student_t_slope_test() -> None:
    fit = ols_linear(
        [0, 1, 2, 0, 1, 2],
        [0.1, 1.0, 2.2, 0.0, 1.2, 1.9],
    )
    assert fit["stable"] is True
    assert math.isclose(float(fit["slope"]), 1.0)
    assert 0.0 < float(fit["p_two_sided"]) < 0.001


def test_km_rmst_immediate_recovery_is_one_cycle() -> None:
    _, rmst = kaplan_meier([1, 1], [1, 1], horizon=180)
    assert math.isclose(rmst, 1.0)
