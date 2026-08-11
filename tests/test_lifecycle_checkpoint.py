from __future__ import annotations

from dataclasses import replace

import pytest

from resonance.experiments.integration_campaign import (
    IntegrationCampaignConfig,
    IntegrationEnvironment,
    ReputationPolicy,
)
from resonance.experiments.lifecycle_campaign import (
    LifecycleSpec,
    evaluate_lifecycle_arms,
    lifecycle_effects,
    should_exit,
)
from resonance.experiments.lifecycle_checkpoint import _initial_checkpoint, _validate_checkpoint
from resonance.experiments.lifecycle_config import LifecycleConfig


def _integration() -> IntegrationCampaignConfig:
    env = IntegrationEnvironment(
        agents=12,
        domains=("a", "b", "c"),
        cycles=72,
        cycle_seconds=30,
        shift_period=18,
        candidate_count=7,
        task_budget=12,
        bid_deadline_seconds=20,
        trace_half_life_cycles=8.0,
        initial_credits=1200,
        base_success_probability=0.38,
        practice_gain=0.14,
        maximum_success_probability=0.90,
        confidence_base=0.35,
        confidence_evidence_weight=0.35,
        confidence_noise_weight=0.20,
        price_floor=0.45,
        price_span=0.35,
        completion_min_seconds=5,
        completion_span_seconds=12,
    )
    return IntegrationCampaignConfig(
        name="test-lifecycle",
        environment=env,
        seeds=(101, 202),
        holdout_seeds=(707,),
        holdout_cycles=84,
        holdout_shift_period=15,
        holdout_candidate_count=7,
        success_tolerance=0.015,
        incumbent_tolerance=0.05,
        economic_tolerance=0.08,
    )


def _config() -> LifecycleConfig:
    return LifecycleConfig(
        integration=_integration(),
        reference_practice_gain=0.14,
        fixed_lifetime_cycles=24,
        lifetime_candidates=(12, 18, 24, 36),
        stochastic_min_age=6,
        advisor_weight=0.08,
        public_trace_confidence_weight=0.10,
        knowledge_signal_threshold=0.20,
        retrieval_top_k=6,
        diversified_lineages=3,
        knowledge_tolerance=0.10,
        minimum_incumbent_improvement=0.02,
        minimum_hhi_improvement=0.02,
        rapid_shift_period=12,
        synthesis_cycles=96,
        replication_seeds=(404, 505),
        holdout_lifetime_cycles=29,
        holdout_shift_period=15,
    )


def _arm(label: str, *, success: float, incumbent: float, hhi: float, knowledge: float):
    return {
        "label": label,
        "policy": ReputationPolicy().as_dict(),
        "lifecycle": LifecycleSpec().as_dict(),
        "environment": _integration().environment.as_dict(),
        "metrics": {
            "success_rate": success,
            "agent_domain_mutual_information": 0.2,
            "mean_specialization": 0.2,
            "mean_winner_hhi": hhi,
            "early_incumbent_share": incumbent,
            "winner_replacement_rate": 0.7,
            "identity_early_incumbent_share": incumbent,
            "identity_replacement_rate": 0.8,
            "reputation_brier_score": 0.25,
            "mean_winning_price_fraction": 0.5,
            "credit_gini": 0.01,
            "exit_count": 0.0,
            "turnover_rate": 0.0,
            "mean_active_age": 10.0,
            "public_knowledge_coverage": knowledge,
            "mean_public_trace_signal": 0.5,
            "cultural_lineage_hhi": 0.2,
            "retired_trace_retrieval_share": 0.0,
            "max_generation": 0.0,
        },
        "invariants": {
            "ledger_conserved": True,
            "balanced_ledger": True,
            "zero_completed_escrow": True,
            "score_provenance_complete": True,
            "reputation_evidence_idempotent": True,
            "sealed_bids_immutable": True,
            "score_provenance_immutable": True,
            "reputation_nonspendable": True,
        },
        "run_ids": [],
    }


def test_fixed_exit_occurs_at_exact_lifetime() -> None:
    spec = LifecycleSpec(mode="fixed", lifetime_cycles=24)
    assert not should_exit(spec, seed=1, cycle=23, slot=0, born_cycle=0)
    assert should_exit(spec, seed=1, cycle=24, slot=0, born_cycle=0)


def test_stochastic_exit_respects_minimum_age() -> None:
    spec = LifecycleSpec(mode="stochastic", lifetime_cycles=12, stochastic_min_age=6)
    assert all(
        not should_exit(spec, seed=101, cycle=cycle, slot=0, born_cycle=0)
        for cycle in range(1, 6)
    )


def test_retirement_and_death_share_competitive_exit_schedule() -> None:
    death = LifecycleSpec(mode="death", lifetime_cycles=18)
    retirement = LifecycleSpec(mode="retirement", lifetime_cycles=18)
    for cycle in range(1, 30):
        assert should_exit(death, seed=7, cycle=cycle, slot=2, born_cycle=0) == should_exit(
            retirement,
            seed=7,
            cycle=cycle,
            slot=2,
            born_cycle=0,
        )


def test_lifecycle_selection_can_prefer_plasticity_without_quality_loss() -> None:
    control = _arm("immortal_control", success=0.50, incumbent=0.20, hhi=0.25, knowledge=0.90)
    finite = _arm("finite", success=0.50, incumbent=0.08, hhi=0.16, knowledge=0.88)
    evaluated, selected, baseline = evaluate_lifecycle_arms(
        [control, finite],
        config=_integration(),
        knowledge_tolerance=0.10,
    )
    assert selected["label"] == "finite"
    effects = lifecycle_effects(selected, baseline)
    assert effects["identity_incumbent_reduction"] == pytest.approx(0.12)
    assert effects["hhi_reduction"] == pytest.approx(0.09)
    assert all(bool(arm["feasible"]) for arm in evaluated)


def test_knowledge_loss_can_make_turnover_infeasible() -> None:
    control = _arm("immortal_control", success=0.50, incumbent=0.20, hhi=0.25, knowledge=0.90)
    destructive = _arm("finite", success=0.51, incumbent=0.05, hhi=0.12, knowledge=0.60)
    evaluated, _, _ = evaluate_lifecycle_arms(
        [control, destructive],
        config=_integration(),
        knowledge_tolerance=0.10,
    )
    candidate = next(arm for arm in evaluated if arm["label"] == "finite")
    assert candidate["feasible"] is False


def test_checkpoint_must_advance_exactly_one_experiment() -> None:
    config = _config()
    state = _initial_checkpoint(config=config, config_hash="hash", code_sha="sha")
    _validate_checkpoint(
        state,
        number=63,
        config=config,
        config_hash="hash",
        code_sha="sha",
    )
    with pytest.raises(ValueError, match="immediately precede"):
        _validate_checkpoint(
            state,
            number=64,
            config=config,
            config_hash="hash",
            code_sha="sha",
        )


def test_config_preserves_high_practice_reference() -> None:
    config = _config()
    assert config.reference_practice_gain == pytest.approx(0.14)
    assert replace(
        config.integration.environment,
        practice_gain=config.reference_practice_gain,
    ).practice_gain == pytest.approx(0.14)
