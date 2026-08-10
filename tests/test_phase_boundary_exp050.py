from __future__ import annotations

from pathlib import Path

from resonance.experiments import phase_boundary_checkpoint as checkpoint
from resonance.experiments.phase_boundary_campaign import PhaseBoundaryConfig


def _config() -> PhaseBoundaryConfig:
    return PhaseBoundaryConfig.from_mapping(
        {
            "name": "phase-exp050-regression",
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


def test_exp050_fallback_uses_evaluated_control(monkeypatch, tmp_path: Path) -> None:
    config = _config()

    def fake_run_experiment(*args, **kwargs):
        del args
        evaluated = []
        for arm in kwargs["arms"]:
            is_control = arm.label == "no_reputation"
            evaluated.append(
                {
                    "label": arm.label,
                    "policy": arm.policy.as_dict(),
                    "environment": arm.environment.as_dict(),
                    "metrics": _metrics(0.50 if is_control else 0.52),
                    "invariants": _invariants(),
                    "run_ids": [f"run-{arm.label}"],
                    "feasible": is_control,
                    "utility": 0.50 if is_control else 0.60,
                }
            )
        raw_control = dict(next(item for item in evaluated if item["label"] == "no_reputation"))
        raw_control.pop("feasible")
        raw_control.pop("utility")
        selected = next(item for item in evaluated if item["label"] == "full_reputation")
        return evaluated, selected, raw_control

    monkeypatch.setattr(checkpoint, "_run_experiment", fake_run_experiment)
    monkeypatch.setattr(checkpoint, "export_integration_campaign_artifacts", lambda *args, **kwargs: None)

    state = checkpoint._initial_checkpoint(
        config=config,
        config_hash="exp050-config",
        code_sha="exp050-sha",
    )
    state.update(
        {
            "last_completed": 49,
            "next_experiment": 50,
            "learning_timescale_cycles": 18.0,
            "boundary_ratio": 2.5,
        }
    )

    result = checkpoint.run_phase_boundary_step(
        object(),  # type: ignore[arg-type]
        config=config,
        config_hash="exp050-config",
        code_sha="exp050-sha",
        number=50,
        checkpoint=state,
        output_dir=tmp_path,
    )

    experiment = result["experiment"]
    assert experiment["selected_label"] == "no_reputation"
    assert result["checkpoint"]["chosen_policy"]["mode"] == "none"
    assert result["checkpoint"]["next_experiment"] == 51
    assert "Experiment 050 — completed" in (tmp_path / "notebook.md").read_text()
