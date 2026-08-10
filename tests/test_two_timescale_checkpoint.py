from __future__ import annotations

import json
from pathlib import Path

import pytest

from resonance.experiments import two_timescale_checkpoint as checkpoint
from resonance.experiments.integration_campaign import (
    ArmSpec,
    ReputationPolicy,
    _evaluate_arms,
)
from resonance.experiments.two_timescale_metrics import (
    fit_two_timescale_rule,
    forgetting_timescale_from_observations,
    formation_timescale_from_observations,
    model_score,
    model_sign,
)


def _mapping() -> dict[str, object]:
    return {
        "name": "two-timescale-test",
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
        "two_timescale": {
            "stable_cycles": 36,
            "measurement_shift_period": 18,
            "formation_target_fraction": 0.20,
            "formation_window": 4,
            "forgetting_window": 4,
            "incumbent_reference_window": 9,
            "forgetting_target_fraction": 0.50,
            "persistence_windows": 2,
            "effect_epsilon": 0.005,
            "slow_practice_gain": 0.07,
            "fast_practice_gain": 0.14,
            "interpolation_practice_gain": 0.12,
            "holdout_practice_gain": 0.085,
            "model_min_shift_period": 6,
            "model_max_shift_period": 24,
            "challenge_multiplier": 0.85,
            "holdout_multiplier": 1.15,
            "model_neutral_band": 0.05,
            "minimum_model_accuracy": 0.66,
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


def _summary(label: str, policy: ReputationPolicy, env, *, success: float, incumbent: float = 0.05):
    return {
        "label": label,
        "policy": policy.as_dict(),
        "environment": env.as_dict(),
        "metrics": {
            "success_rate": success,
            "agent_domain_mutual_information": 0.25 if policy.mode == "reputation" else 0.15,
            "mean_specialization": 0.28 if policy.mode == "reputation" else 0.18,
            "mean_winner_hhi": 0.14,
            "early_incumbent_share": incumbent,
            "winner_replacement_rate": 0.88,
            "reputation_brier_score": 0.24,
            "mean_winning_price_fraction": 0.52,
            "credit_gini": 0.01,
        },
        "invariants": _invariants(),
        "run_ids": [f"run-{label}"],
    }


def _install_fakes(monkeypatch, config: checkpoint.TwoTimescaleConfig) -> None:
    formation = {0.07: 24.0, 0.10: 16.0, 0.14: 9.0}
    forgetting = {0.07: 15.0, 0.10: 11.0, 0.14: 7.0}

    def fake_run_experiment(*args, **kwargs):
        del args
        summaries = []
        for arm in kwargs["arms"]:
            gain = round(arm.environment.practice_gain, 3)
            shift = arm.environment.shift_period
            if arm.policy.mode == "none":
                success = 0.50
                incumbent = 0.04
            else:
                tau_f = formation.get(gain, 13.0)
                tau_d = forgetting.get(gain, 9.0)
                score = min(shift / tau_f / 1.7, shift / tau_d / 3.0)
                success = 0.50 + 0.03 * min(1.0, score)
                incumbent = 0.04 if score >= 1.0 else 0.12
            summaries.append(
                _summary(
                    arm.label,
                    arm.policy,
                    arm.environment,
                    success=success,
                    incumbent=incumbent,
                )
            )
        return _evaluate_arms(summaries, config=config.integration)

    def fake_paired(*args, **kwargs):
        del args
        arms, _, _ = fake_run_experiment(
            number=kwargs["number"],
            arms=[
                ArmSpec("no_reputation", ReputationPolicy(), kwargs["env"]),
                ArmSpec(
                    kwargs.get("reference_label", "reference_reputation"),
                    kwargs["policy"],
                    kwargs["env"],
                ),
            ],
        )
        control = next(item for item in arms if item["label"] == "no_reputation")
        reference = next(item for item in arms if item["label"] != "no_reputation")
        effect = checkpoint._effect(reference, control)
        sign = checkpoint._sign(
            effect,
            feasible=bool(reference["feasible"]),
            epsilon=config.effect_epsilon,
        )
        return arms, reference, control, effect, sign

    def fake_measure_formation(*args, **kwargs):
        del args
        gain = round(kwargs["practice_gain"], 3)
        env = checkpoint.stable_environment(
            config.integration.environment,
            cycles=config.stable_cycles,
            practice_gain=gain,
        )
        arms, reference, control, effect, sign = fake_paired(
            number=kwargs["number"],
            env=env,
            policy=checkpoint.reference_policy(),
        )
        tau = formation[gain]
        return arms, reference, control, tau, tau + 2.0, effect, sign

    def fake_measure_forgetting(*args, **kwargs):
        del args
        gain = round(kwargs["practice_gain"], 3)
        env = checkpoint.shift_environment(
            config.integration.environment,
            shift_period=config.measurement_shift_period,
            practice_gain=gain,
        )
        arms, reference, control, effect, sign = fake_paired(
            number=kwargs["number"],
            env=env,
            policy=checkpoint.reference_policy(),
        )
        values = {
            "tau_d": forgetting[gain],
            "pre_incumbent_share": 0.42,
            "late_incumbent_share": 0.10,
        }
        control_values = {
            "tau_d": max(4.0, forgetting[gain] - 3.0),
            "pre_incumbent_share": 0.30,
            "late_incumbent_share": 0.08,
        }
        return arms, reference, control, values, control_values, effect, sign

    monkeypatch.setattr(checkpoint, "_run_experiment", fake_run_experiment)
    monkeypatch.setattr(checkpoint, "_paired_experiment", fake_paired)
    monkeypatch.setattr(checkpoint, "_measure_formation", fake_measure_formation)
    monkeypatch.setattr(checkpoint, "_measure_forgetting", fake_measure_forgetting)
    monkeypatch.setattr(checkpoint, "write_step_artifacts", _fake_write_artifacts)


def _fake_write_artifacts(connection, *, output_dir, record, checkpoint, **kwargs) -> None:
    del connection, kwargs
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "checkpoint.json").write_text(json.dumps(dict(checkpoint)))
    (output / "notebook.md").write_text(
        f"<!-- two-timescale-053-062:experiment-{int(record['number']):03d} -->\n"
    )
    if int(record["number"]) == 62:
        (output / "campaign-summary.md").write_text("complete\n")


def test_formation_timescale_is_sensitive_to_practice_gain() -> None:
    observations = [(cycle, "a", "skill", 0) for cycle in range(24)]
    slow = formation_timescale_from_observations(
        observations,
        base_success_probability=0.38,
        practice_gain=0.07,
        maximum_success_probability=0.90,
        target_fraction=0.20,
        window=4,
        persistence=2,
    )
    fast = formation_timescale_from_observations(
        observations,
        base_success_probability=0.38,
        practice_gain=0.14,
        maximum_success_probability=0.90,
        target_fraction=0.20,
        window=4,
        persistence=2,
    )
    assert fast < slow


def test_forgetting_timescale_detects_incumbent_release() -> None:
    pre = [
        (cycle, "a" if cycle % 2 == 0 else "b", "x", cycle % 2)
        for cycle in range(12)
    ]
    released_post = [
        (
            12 + cycle,
            "a" if cycle % 2 == 0 else "b",
            "y",
            4 if cycle >= 3 else cycle % 2,
        )
        for cycle in range(12)
    ]
    persistent_post = [
        (12 + cycle, "a" if cycle % 2 == 0 else "b", "y", cycle % 2)
        for cycle in range(12)
    ]
    released = forgetting_timescale_from_observations(
        pre + released_post,
        shift_period=12,
        agents=6,
        reference_window=8,
        rolling_window=4,
        target_fraction=0.5,
        persistence=2,
    )[0]
    persistent = forgetting_timescale_from_observations(
        pre + persistent_post,
        shift_period=12,
        agents=6,
        reference_window=8,
        rolling_window=4,
        target_fraction=0.5,
        persistence=2,
    )[0]
    assert released < persistent


def test_two_timescale_rule_fits_separable_points() -> None:
    model = fit_two_timescale_rule(
        [
            {"ratio_f": 1.0, "ratio_d": 2.0, "reference_sign": "negative"},
            {"ratio_f": 2.5, "ratio_d": 4.0, "reference_sign": "positive"},
            {"ratio_f": 3.0, "ratio_d": 1.5, "reference_sign": "negative"},
        ]
    )
    assert model["accuracy"] == 1.0
    score = model_score(
        ratio_f=3.0,
        ratio_d=4.5,
        theta_f=model["theta_f"],
        theta_d=model["theta_d"],
    )
    assert model_sign(score, neutral_band=0.05) == "positive"


def test_checkpointed_campaign_runs_53_through_62(monkeypatch, tmp_path: Path) -> None:
    config = checkpoint.TwoTimescaleConfig.from_mapping(_mapping())
    _install_fakes(monkeypatch, config)
    state = None
    results = []
    for number in range(53, 63):
        output = tmp_path / f"exp-{number}"
        result = checkpoint.run_two_timescale_step(
            object(),  # type: ignore[arg-type]
            config=config,
            config_hash="two-timescale-config",
            code_sha="two-timescale-sha",
            number=number,
            checkpoint=state,
            output_dir=output,
        )
        results.append(result)
        state = json.loads((output / "checkpoint.json").read_text())
        assert state["last_completed"] == number
        assert (output / "notebook.md").read_text().startswith(
            f"<!-- two-timescale-053-062:experiment-{number:03d} -->"
        )
    assert [item["completed"] for item in results] == list(range(53, 63))
    assert state["next_experiment"] is None
    assert len(state["measurements"]) == 3
    assert state["model"] is not None
    assert state["candidate_policy"] is not None
    assert isinstance(state["validated"], bool)
    assert (tmp_path / "exp-62" / "campaign-summary.md").exists()


def test_checkpoint_rejects_skipped_experiment(monkeypatch, tmp_path: Path) -> None:
    config = checkpoint.TwoTimescaleConfig.from_mapping(_mapping())
    _install_fakes(monkeypatch, config)
    result = checkpoint.run_two_timescale_step(
        object(),  # type: ignore[arg-type]
        config=config,
        config_hash="two-timescale-config",
        code_sha="two-timescale-sha",
        number=53,
        checkpoint=None,
        output_dir=tmp_path / "exp-53",
    )
    with pytest.raises(ValueError, match="immediately precede"):
        checkpoint.run_two_timescale_step(
            object(),  # type: ignore[arg-type]
            config=config,
            config_hash="two-timescale-config",
            code_sha="two-timescale-sha",
            number=55,
            checkpoint=result["checkpoint"],
            output_dir=tmp_path / "exp-55",
        )
