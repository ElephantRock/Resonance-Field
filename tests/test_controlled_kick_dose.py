from __future__ import annotations

import json
from pathlib import Path

from resonance.experiments.controlled_kick_dose_config import KickDoseConfig


def _config_mapping() -> dict[str, object]:
    path = Path("configs/experiments/controlled-kick-dose-135-137.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_frozen_controlled_kick_config_loads() -> None:
    config = KickDoseConfig.from_mapping(_config_mapping())
    assert config.doses == (1, 2, 4)
    assert config.cycles == 234
    assert config.landmark_cycle == 54
    assert config.mediator_cycles == (54, 71)
    assert config.gap_cycles == (40, 53)
    assert config.k4_zero_within_arm_timing_variance is True


def test_instrumentation_schedules_match_dose_and_burst() -> None:
    config = KickDoseConfig.from_mapping(_config_mapping())
    for cell in config.instrumentation:
        assert len(cell.kick_cycles) == cell.dose
        assert set(cell.kick_cycles) <= set(config.burst_cycles)


def test_inferential_timing_sequences_balance_mean_kick_position() -> None:
    config = KickDoseConfig.from_mapping(_config_mapping())
    means = {}
    for dose, sequence in config.timing_sequences.items():
        all_positions = [cycle for schedule in sequence for cycle in schedule]
        means[dose] = sum(all_positions) / len(all_positions)
    assert means == {1: 37.5, 2: 37.5, 4: 37.5}
    assert len(config.timing_sequences[4]) == 1
