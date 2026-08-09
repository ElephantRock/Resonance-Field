from __future__ import annotations

import pytest

from resonance.substrate import decayed_energy, reinforce_energy


def test_energy_halves_after_one_half_life() -> None:
    assert decayed_energy(1.0, 60.0, 60.0) == pytest.approx(0.5)


def test_energy_quarters_after_two_half_lives() -> None:
    assert decayed_energy(1.0, 120.0, 60.0) == pytest.approx(0.25)


def test_decay_rejects_invalid_half_life() -> None:
    with pytest.raises(ValueError):
        decayed_energy(1.0, 1.0, 0.0)


def test_reinforcement_is_bounded() -> None:
    assert reinforce_energy(
        0.95,
        reinforcement=1.0,
        adoption=1.0,
        verified_utility=1.0,
    ) == pytest.approx(1.0)
