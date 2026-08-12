from __future__ import annotations

import math
from pathlib import Path

from resonance.experiments.controlled_kick_dose_136 import schedule_for_seed
from resonance.experiments.controlled_kick_dose_config import load_controlled_kick_dose_config

_CONFIG = Path("configs/experiments/controlled-kick-dose-135-137.json")


def test_replication_cohort_is_frozen_disjoint_and_balanced() -> None:
    config, _ = load_controlled_kick_dose_config(_CONFIG)
    assert config.replication_seeds == tuple(range(3001, 3037))
    assert set(config.replication_seeds).isdisjoint(config.discovery_seeds)

    assignments = {
        seed: schedule_for_seed(config, seed=seed, cohort_seeds=config.replication_seeds)
        for seed in config.replication_seeds
    }
    assert sum(dose == 1 for dose, _ in assignments.values()) == 12
    assert sum(dose == 2 for dose, _ in assignments.values()) == 12
    assert sum(dose == 4 for dose, _ in assignments.values()) == 12

    for dose in config.doses:
        schedules = [
            schedule for assigned_dose, schedule in assignments.values() if assigned_dose == dose
        ]
        mean_positions = [sum(schedule) / len(schedule) for schedule in schedules]
        assert math.isclose(sum(mean_positions) / len(mean_positions), 37.5)

    k1_cycles = [
        cycle
        for dose, schedule in assignments.values()
        if dose == 1
        for cycle in schedule
    ]
    assert {cycle: k1_cycles.count(cycle) for cycle in range(36, 40)} == {
        36: 3,
        37: 3,
        38: 3,
        39: 3,
    }

    k2_cycles = [
        cycle
        for dose, schedule in assignments.values()
        if dose == 2
        for cycle in schedule
    ]
    assert {cycle: k2_cycles.count(cycle) for cycle in range(36, 40)} == {
        36: 6,
        37: 6,
        38: 6,
        39: 6,
    }
    assert {
        schedule for dose, schedule in assignments.values() if dose == 4
    } == {(36, 37, 38, 39)}


def test_replication_schedule_matches_frozen_modulo_three_rule() -> None:
    config, _ = load_controlled_kick_dose_config(_CONFIG)
    first_nine = {
        seed: schedule_for_seed(config, seed=seed, cohort_seeds=config.replication_seeds)[0]
        for seed in config.replication_seeds[:9]
    }
    assert tuple(first_nine.values()) == (1, 2, 4, 1, 2, 4, 1, 2, 4)
