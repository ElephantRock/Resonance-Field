from __future__ import annotations

from pathlib import Path

import pytest

from resonance.experiments import phase_boundary_campaign as campaign


def _mapping() -> dict[str, object]:
    return {
        "name": "phase-boundary-test",
        "environment": {
            "agents": 6,
            "domains": ["a", "b", "c"],
            "cycles": 36,
            "cycle_seconds": 10,
            "shift_period": 12,
            "candidate_count": 3,
            "task_budget": 10,
            "bid_deadline_seconds": 6,
            "trace_half_life_cycles": 6.0,
            "initial_credits": 500,
            "base_success_probability": 0.38,
            "practice_gain": 0.10,
            "maximum_success_probability": 0.90,
            "confidence_base": 0.35,
            "confidence_evidence_weight": 0.35,
            "confidence_noise_weight": 0.20,
            "price_floor": 0.45,
            "price_span": 0.35,
            "completion_min_seconds": 2,
            "completion_span_seconds": 3,
        },
        "seeds": [11],
        "holdout_seeds": [99],
        "holdout_cycles": 36,
        "holdout_shift_period": 12,
        "holdout_candidate_count": 3,
        "success_tolerance": 0.02,
        "incumbent_tolerance": 0.05,
        "economic_tolerance": 0.08,
        "phase_boundary": {
            "stable_cycles": 36,
            "min_shift_period": 4,
            "max_shift_period": 24,
            "learning_target_fraction": 0.5,
            "effect_epsilon": 0.005,
            "slow_practice_gain": 0.07,
            "fast_practice_gain": 0.14,
            "replication_seeds": [55],
        },
    }


def _invariants() -> dict[str, bool]:
    return {
        "ledger_conserved": True,
        "balanced_ledger": True,
        "zero_completed_escrow": True,
        "score_provenance_complete": True,
        "reputation_evidence_idempotent": True,
        "sealed_bids_immutable": True,
        "score_provenance_immutable": True,
        "reputation_nonspendable": True,
    }


def _tau_for_gain(gain: float) -> float:
    if gain <= 0.075:
        return 20.0
    if gain >= 0.13:
        return 10.0
    return 14.0


def test_campaign_runs_exactly_12_result_driven_experiments(monkeypatch, tmp_path: Path) -> None:
    config = campaign.PhaseBoundaryConfig.from_mapping(_mapping())

    def fake_run_experiment(*args, **kwargs):
        del args
        arms = kwargs["arms"]
        summaries = []
        for arm in arms:
            env = arm.environment
            tau = _tau_for_gain(env.practice_gain)
            ratio = env.shift_period / tau
            if arm.policy.mode == "none":
                success = 0.50
            else:
                strength = arm.policy.weight / 0.45 if arm.policy.weight else 0.0
                success = 0.50 + strength * 0.04 * (ratio - 1.0)
            metrics = {
                "success_rate": success,
                "agent_domain_mutual_information": 0.20 if arm.policy.mode == "reputation" else 0.12,
                "mean_specialization": 0.22 if arm.policy.mode == "reputation" else 0.12,
                "mean_winner_hhi": 0.14,
                "early_incumbent_share": 0.06,
                "winner_replacement_rate": 0.88,
                "reputation_brier_score": 0.24,
                "mean_winning_price_fraction": 0.52,
                "credit_gini": 0.01,
            }
            summaries.append(
                {
                    "label": arm.label,
                    "policy": arm.policy.as_dict(),
                    "environment": env.as_dict(),
                    "metrics": metrics,
                    "invariants": _invariants(),
                    "run_ids": [f"run-{kwargs['number']}-{arm.label}"],
                }
            )
        evaluated, selected, control = campaign._evaluate_arms(
            summaries,
            config=config.integration,
        )
        return evaluated, selected, control

    def fake_learning_timescale(connection, arm, *, target_fraction):
        del connection, target_fraction
        env = arm["environment"]
        return _tau_for_gain(float(env["practice_gain"]))

    monkeypatch.setattr(campaign, "_run_experiment", fake_run_experiment)
    monkeypatch.setattr(campaign, "_learning_timescale", fake_learning_timescale)
    monkeypatch.setattr(campaign, "export_integration_campaign_artifacts", lambda *args, **kwargs: None)

    result = campaign.run_phase_boundary_campaign(
        object(),  # type: ignore[arg-type]
        config=config,
        config_hash="test-config",
        code_sha="test-sha",
        output_dir=tmp_path,
    )

    experiments = result["experiments"]
    assert [item["number"] for item in experiments] == list(range(41, 53))
    assert len(experiments) == 12
    assert experiments[0]["focus"] == "learning_timescale"
    assert [item["focus"] for item in experiments[1:5]] == ["regime_period"] * 4
    assert experiments[9]["focus"] == "adaptive_disengagement"
    assert experiments[10]["focus"] == "independent_replication"
    assert experiments[11]["focus"] == "unseen_holdout"
    assert experiments[-1]["next_experiment_focus"] is None
    assert isinstance(experiments[-1]["validated"], bool)
    assert float(result["boundary_ratio"]) > 0


def test_bracketing_moves_between_opposite_signs() -> None:
    config = campaign.PhaseBoundaryConfig.from_mapping(_mapping())
    observations = [
        {"shift_period": 8, "effect": -0.02, "sign": "negative"},
        {"shift_period": 20, "effect": 0.03, "sign": "positive"},
    ]
    assert campaign._next_bracket_shift(observations, config=config) == 14
    shift, theta, bracketed = campaign._boundary_estimate(observations, tau_learning=14.0)
    assert shift == pytest.approx(14.0)
    assert theta == pytest.approx(1.0)
    assert bracketed is True


def test_timescale_gate_reduces_weight_below_boundary() -> None:
    policy = campaign.reference_policy()
    gated = campaign._gated_policy(policy, ratio=0.5, theta=1.0)
    assert gated.weight == pytest.approx(policy.weight * 0.5)
    assert gated.blend_skill == policy.blend_skill
    assert gated.exposure_penalty == policy.exposure_penalty
