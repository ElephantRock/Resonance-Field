from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from resonance.experiments.epistemic_substrate_analysis import (
    analyze_confirmatory,
    holm_adjust,
    paired_bootstrap_ci,
    paired_sign_flip_p_value,
)
from resonance.experiments.epistemic_substrate_campaign import ArmMetrics
from resonance.experiments.epistemic_substrate_config import load_epistemic_substrate_config

CONFIG_PATH = Path("configs/experiments/epistemic-substrate-138-141.json")


def _metric(arm: str, value: float) -> ArmMetrics:
    return ArmMetrics(
        arm=arm,
        transfer_accuracy=value,
        collective_emergence_ratio=value,
        evidence_coverage=1.0,
        contradiction_resolution_f1=1.0,
        bridge_recall=1.0,
        provenance_completeness=float(arm != "pile"),
        knowledge_survival_rate=1.0,
        duplicate_work_rate=0.0,
        false_synthesis_rate=0.0,
        retrieval_items_consumed=1.0,
    )


def test_holm_adjustment_is_monotone() -> None:
    adjusted = holm_adjust((0.01, 0.04, 0.03))
    assert adjusted == pytest.approx((0.03, 0.06, 0.06))


def test_bootstrap_constant_difference_has_point_interval() -> None:
    interval = paired_bootstrap_ci(
        (0.2,) * 16,
        resamples=1000,
        confidence=0.95,
        seed=7,
    )
    assert interval == pytest.approx((0.2, 0.2))


def test_sign_flip_is_deterministic() -> None:
    differences = (0.2,) * 16
    first = paired_sign_flip_p_value(differences, resamples=5000, seed=11)
    second = paired_sign_flip_p_value(differences, resamples=5000, seed=11)
    assert first == second
    assert first < 0.01


def test_confirmatory_analysis_success_rule_on_synthetic_cohort() -> None:
    config, _digest = load_epistemic_substrate_config(CONFIG_PATH)
    synthetic_seeds = tuple(range(1, 17))
    synthetic_config = replace(
        config,
        confirmatory_seeds=synthetic_seeds,
        bootstrap_resamples=1000,
        randomization_resamples=10000,
    )
    worlds = {
        seed: (
            _metric("pile", 0.10),
            _metric("shared_memory", 0.20),
            _metric("provenance_graph", 0.30),
            _metric("resonance_field", 0.50),
        )
        for seed in synthetic_seeds
    }

    analysis = analyze_confirmatory(worlds, synthetic_config)

    assert len(analysis.contrasts) == 8
    assert analysis.campaign_success is True
    total_effects = [
        result
        for result in analysis.contrasts
        if result.treatment == "resonance_field" and result.control == "pile"
    ]
    assert len(total_effects) == 2
    assert all(result.effect == pytest.approx(0.40) for result in total_effects)
    assert all(result.adjusted_p_value < synthetic_config.alpha for result in total_effects)
    assert all(result.ci_lower > 0.0 for result in total_effects)
