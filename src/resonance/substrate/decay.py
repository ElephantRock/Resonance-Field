"""Trace energy decay and reinforcement functions."""

from __future__ import annotations

import math


def decayed_energy(
    initial_energy: float,
    elapsed_seconds: float,
    half_life_seconds: float,
) -> float:
    """Return exponentially decayed trace energy.

    E(t) = E0 * 2 ** (-elapsed / half_life)
    """
    if initial_energy < 0:
        raise ValueError("initial_energy must be non-negative")
    if elapsed_seconds < 0:
        raise ValueError("elapsed_seconds must be non-negative")
    if half_life_seconds <= 0:
        raise ValueError("half_life_seconds must be positive")

    return initial_energy * math.pow(2.0, -elapsed_seconds / half_life_seconds)


def reinforce_energy(
    current_energy: float,
    *,
    reinforcement: float = 0.0,
    adoption: float = 0.0,
    verified_utility: float = 0.0,
    reinforcement_weight: float = 0.10,
    adoption_weight: float = 0.20,
    utility_weight: float = 0.30,
    max_energy: float = 1.0,
) -> float:
    """Apply bounded meaningful reinforcement to trace energy.

    Reads are deliberately absent from this function. A read alone must not make
    a trace persistent; reinforcement should represent downstream evidence.
    """
    values = (current_energy, reinforcement, adoption, verified_utility)
    if any(value < 0 for value in values):
        raise ValueError("energy and reinforcement inputs must be non-negative")
    if max_energy <= 0:
        raise ValueError("max_energy must be positive")

    updated = (
        current_energy
        + reinforcement_weight * reinforcement
        + adoption_weight * adoption
        + utility_weight * verified_utility
    )
    return min(max_energy, updated)
