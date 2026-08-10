from __future__ import annotations

import json
from pathlib import Path

import pytest

from resonance.experiments import phase_boundary_checkpoint as checkpoint
from resonance.experiments.integration_campaign import (
    ArmSpec,
    ReputationPolicy,
    _evaluate_arms,
)
from resonance.experiments.phase_boundary_campaign import PhaseBoundaryConfig


def _mapping() -> dict[str, object]:
    return {
        "name": "phase-checkpoint-test",
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


def _install_fakes(monkeypatch, config: PhaseBoundaryConfig) -> None:
    def fake_run_experiment(*args, **kwargs):
        del args
        summaries = []
        for arm in kwargs["arms"]:
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
        return _evaluate_arms(summaries, config=config.integration)

    def fake_paired(*args, **kwargs):
        del args
        arms, _, control = fake_run_experiment(
            number=kwargs["number"],
            arms=[
                ArmSpec("no_reputation", ReputationPolicy(), kwargs["env"]),
                ArmSpec(kwargs.get("reference_label", "reference_reputation"), kwargs["policy"], kwargs["env"]),
            ],
        )
        reference = next(item for item in arms if item["label"] != "no_reputation")
        effect = checkpoint._effect(reference, control)
        sign = checkpoint._sign(
            effect,
            feasible=bool(reference["feasible"]),
            epsilon=config.effect_epsilon,
        )
        return arms, reference, control, effect, sign

    def fake_learning_timescale(connection, arm, *, target_fraction):
        del connection, target_fraction
        env = arm["environment"]
        return _tau_for_gain(float(env["practice_gain"]))

    monkeypatch.setattr(checkpoint, "_run_experiment", fake_run_experiment)
    monkeypatch.setattr(checkpoint, "_paired_experiment", fake_paired)
    monkeypatch.setattr(checkpoint, "_learning_timescale", fake_learning_timescale)
    monkeypatch.setattr(checkpoint, "export_integration_campaign_artifacts", lambda *args, **kwargs: None)


def test_checkpointed_campaign_runs_41_through_52(monkeypatch, tmp_path: Path) -> None:
    config = PhaseBoundaryConfig.from_mapping(_mapping())
    _install_fakes(monkeypatch, config)
    state = None
    results = []

    for number in range(41, 53):
        output = tmp_path / f"exp-{number}"
        result = checkpoint.run_phase_boundary_step(
            object(),  # type: ignore[arg-type]
            config=config,
            config_hash="checkpoint-config",
            code_sha="checkpoint-sha",
            number=number,
            checkpoint=state,
            output_dir=output,
        )
        results.append(result)
        state = json.loads((output / "checkpoint.json").read_text())
        assert state["last_completed"] == number
        assert (output / "notebook.md").read_text().startswith(
            f"<!-- phase-boundary-041-052:experiment-{number:03d} -->"
        )

    assert [item["completed"] for item in results] == list(range(41, 53))
    assert state["next_experiment"] is None
    assert state["candidate_policy"] is not None
    assert isinstance(state["validated"], bool)
    assert (tmp_path / "exp-52" / "campaign-summary.md").exists()


def test_checkpoint_rejects_skipped_experiment(monkeypatch, tmp_path: Path) -> None:
    config = PhaseBoundaryConfig.from_mapping(_mapping())
    _install_fakes(monkeypatch, config)
    result = checkpoint.run_phase_boundary_step(
        object(),  # type: ignore[arg-type]
        config=config,
        config_hash="checkpoint-config",
        code_sha="checkpoint-sha",
        number=41,
        checkpoint=None,
        output_dir=tmp_path / "exp-41",
    )

    with pytest.raises(ValueError, match="immediately precede"):
        checkpoint.run_phase_boundary_step(
            object(),  # type: ignore[arg-type]
            config=config,
            config_hash="checkpoint-config",
            code_sha="checkpoint-sha",
            number=43,
            checkpoint=result["checkpoint"],
            output_dir=tmp_path / "exp-43",
        )


def test_checkpoint_rejects_different_commit(monkeypatch, tmp_path: Path) -> None:
    config = PhaseBoundaryConfig.from_mapping(_mapping())
    _install_fakes(monkeypatch, config)
    result = checkpoint.run_phase_boundary_step(
        object(),  # type: ignore[arg-type]
        config=config,
        config_hash="checkpoint-config",
        code_sha="checkpoint-sha",
        number=41,
        checkpoint=None,
        output_dir=tmp_path / "exp-41",
    )

    with pytest.raises(ValueError, match="code SHA"):
        checkpoint.run_phase_boundary_step(
            object(),  # type: ignore[arg-type]
            config=config,
            config_hash="checkpoint-config",
            code_sha="other-sha",
            number=42,
            checkpoint=result["checkpoint"],
            output_dir=tmp_path / "exp-42",
        )
