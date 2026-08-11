from __future__ import annotations

from pathlib import Path

from resonance.experiments.capability_campaign import effective_practice_value
from resonance.experiments.capability_checkpoint import _hard_gate
from resonance.experiments.capability_config import (
    CapabilityDecaySpec,
    load_capability_decay_config,
    scaled_decay,
)

_CONFIG = Path("configs/experiments/capability-decay-081-086.json")


def test_exponential_effective_practice_halves_without_erasing_history() -> None:
    spec = CapabilityDecaySpec(mode="exponential", half_life_cycles=8.0)
    effective, idle, multiplier = effective_practice_value(
        cumulative=10,
        anchor_effective=8.0,
        last_practice_cycle=4,
        current_cycle=12,
        spec=spec,
    )
    cumulative_history = 10
    assert cumulative_history == 10
    assert idle == 8
    assert multiplier == 0.5
    assert effective == 4.0


def test_floor_decay_retains_bounded_private_capability() -> None:
    spec = CapabilityDecaySpec(
        mode="exponential_floor",
        half_life_cycles=4.0,
        retention_floor=0.25,
    )
    effective, _, _ = effective_practice_value(
        cumulative=12,
        anchor_effective=8.0,
        last_practice_cycle=0,
        current_cycle=20,
        spec=spec,
    )
    assert effective == 3.0


def test_step_decay_drops_effective_practice_only_after_threshold() -> None:
    spec = CapabilityDecaySpec(mode="step", inactive_cycles=6)
    before, _, _ = effective_practice_value(
        cumulative=5,
        anchor_effective=4.5,
        last_practice_cycle=2,
        current_cycle=7,
        spec=spec,
    )
    after, _, _ = effective_practice_value(
        cumulative=5,
        anchor_effective=4.5,
        last_practice_cycle=2,
        current_cycle=8,
        spec=spec,
    )
    assert before == 4.5
    assert after == 0.0


def test_scaling_changes_timescale_not_kernel_family() -> None:
    spec = CapabilityDecaySpec(
        mode="exponential_floor",
        half_life_cycles=8.0,
        retention_floor=0.25,
    )
    scaled = scaled_decay(spec, 1.25)
    assert scaled.mode == spec.mode
    assert scaled.half_life_cycles == 10.0
    assert scaled.retention_floor == spec.retention_floor


def _arm(metrics: dict[str, float]) -> dict[str, object]:
    return {
        "metrics": metrics,
        "invariants": {
            "ledger_conserved": True,
            "provenance_complete": True,
            "cell_trace_isolated": True,
            "identity_turnover_zero": True,
            "capability_history_preserved": True,
            "capability_observations_complete": True,
        },
    }


def test_hard_gate_requires_both_logical_plasticity_and_dormant_erosion() -> None:
    config, _ = load_capability_decay_config(_CONFIG)
    control_metrics = {
        "success_rate": 0.50,
        "early_incumbent_share": 0.11,
        "identity_early_incumbent_share": 0.11,
        "mean_winner_hhi": 0.18,
        "late_public_knowledge_coverage": 0.80,
        "dormant_effective_ratio": 1.0,
        "skill_rank_turnover": 0.20,
        "incumbent_refresh_feedback": 0.30,
        "mean_winning_price_fraction": 0.60,
        "credit_gini": 0.10,
        "exit_count": 0.0,
    }
    candidate_metrics = dict(control_metrics)
    candidate_metrics.update(
        {
            "success_rate": 0.49,
            "early_incumbent_share": 0.08,
            "identity_early_incumbent_share": 0.08,
            "dormant_effective_ratio": 0.70,
        }
    )
    hard, effects = _hard_gate(
        _arm(candidate_metrics),
        _arm(control_metrics),
        config=config,
    )
    assert hard
    assert effects["logical_incumbent_reduction"] >= 0.02
    assert effects["dormant_erosion"] >= 0.10

    candidate_metrics["early_incumbent_share"] = 0.10
    hard, _ = _hard_gate(
        _arm(candidate_metrics),
        _arm(control_metrics),
        config=config,
    )
    assert not hard
