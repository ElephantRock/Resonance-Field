from __future__ import annotations

from pathlib import Path

import pytest

from resonance.experiments import phase_boundary_campaign as campaign


def _config() -> campaign.PhaseBoundaryConfig:
    return campaign.PhaseBoundaryConfig.from_mapping(
        {
            "name": "phase-regression-test",
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
    )


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


def _metrics(success: float) -> dict[str, float]:
    return {
        "success_rate": success,
        "agent_domain_mutual_information": 0.20,
        "mean_specialization": 0.20,
        "mean_winner_hhi": 0.14,
        "early_incumbent_share": 0.06,
        "winner_replacement_rate": 0.88,
        "reputation_brier_score": 0.24,
        "mean_winning_price_fraction": 0.52,
        "credit_gini": 0.01,
    }


def test_migration_allows_experiments_through_052() -> None:
    migration = Path("migrations/009_phase_boundary_experiments.sql").read_text()
    assert "BETWEEN 14 AND 52" in migration


def test_exact_boundary_prediction_is_neutral() -> None:
    assert campaign._predicted_sign(1.0, 1.0) == "neutral"
    assert campaign._predicted_sign(1.06, 1.0) == "positive"
    assert campaign._predicted_sign(0.94, 1.0) == "negative"


def test_learning_timescale_compares_equal_width_windows(monkeypatch) -> None:
    lengths: list[int] = []

    def fixed_mi(rows):
        lengths.append(len(rows))
        return 1.0

    monkeypatch.setattr(campaign, "_mutual_information", fixed_mi)
    observations = [(f"d{index % 6}", index % 12) for index in range(96)]
    tau = campaign._learning_timescale_from_observations(
        observations,
        target_fraction=0.5,
    )

    assert tau == 24.0
    assert set(lengths) == {24}


def test_dynamic_gate_is_recomputed_for_new_ratio() -> None:
    policy = campaign.reference_policy()
    stale = campaign._gated_policy(policy, ratio=0.75, theta=1.0)
    refreshed = campaign._candidate_policy_for_ratio(
        policy,
        stale,
        timescale_gate_selected=True,
        ratio=1.0,
        theta=1.0,
    )
    assert stale.weight == pytest.approx(policy.weight * 0.75)
    assert refreshed.weight == pytest.approx(policy.weight)


def test_control_selected_at_050_remains_control_candidate(monkeypatch, tmp_path: Path) -> None:
    config = _config()
    candidate_modes: list[str] = []

    def fake_run_experiment(*args, **kwargs):
        del args
        number = kwargs["number"]
        summaries = []
        for arm in kwargs["arms"]:
            if number == 51 and arm.label == "candidate_policy":
                candidate_modes.append(arm.policy.mode)
            success = 0.50 if arm.policy.mode == "none" else 0.52
            item = {
                "label": arm.label,
                "policy": arm.policy.as_dict(),
                "environment": arm.environment.as_dict(),
                "metrics": _metrics(success),
                "invariants": _invariants(),
                "run_ids": [f"run-{number}-{arm.label}"],
                "feasible": arm.policy.mode == "none" if number == 50 else True,
                "utility": 0.50 if arm.policy.mode == "none" else 0.55,
            }
            summaries.append(item)
        control = next(item for item in summaries if item["label"] == "no_reputation")
        if number == 50:
            selected = control
        else:
            selected = next(
                (item for item in summaries if item["label"] != "no_reputation"),
                control,
            )
        return summaries, selected, control

    monkeypatch.setattr(campaign, "_run_experiment", fake_run_experiment)
    monkeypatch.setattr(campaign, "_learning_timescale", lambda *args, **kwargs: 12.0)
    monkeypatch.setattr(campaign, "export_integration_campaign_artifacts", lambda *args, **kwargs: None)

    campaign.run_phase_boundary_campaign(
        object(),  # type: ignore[arg-type]
        config=config,
        config_hash="regression-config",
        code_sha="regression-sha",
        output_dir=tmp_path,
    )

    assert candidate_modes == ["none"]
