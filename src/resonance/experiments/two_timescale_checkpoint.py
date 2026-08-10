"""Checkpoint state machine for Experiments 053 through 062."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from psycopg import Connection

from .integration_campaign import ArmSpec, ReputationPolicy, _record, _run_experiment
from .phase_boundary_campaign import _effect, _sign, reference_policy
from .two_timescale_config import (
    TwoTimescaleConfig,
    clamp_shift,
    load_two_timescale_config,
    shift_environment,
    stable_environment,
)
from .two_timescale_metrics import (
    fit_two_timescale_rule,
    forgetting_metrics,
    formation_timescale,
    gate_scale,
    interpolate_timescales,
    model_score,
    model_sign,
)
from .two_timescale_notebook import write_step_artifacts

_CHECKPOINT_VERSION = 1
_FIRST_EXPERIMENT = 53
_LAST_EXPERIMENT = 62


def _policy_from_mapping(value: Mapping[str, object]) -> ReputationPolicy:
    return ReputationPolicy(**dict(value))  # type: ignore[arg-type]


def _paired_experiment(
    connection: Connection[Any],
    *,
    config: TwoTimescaleConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    env,
    seeds: Sequence[int],
    policy: ReputationPolicy,
    reference_label: str = "reference_reputation",
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object], float, str]:
    evaluated, _, _ = _run_experiment(
        connection,
        config=config.integration,
        config_hash=config_hash,
        number=number,
        arms=[
            ArmSpec("no_reputation", ReputationPolicy(), env),
            ArmSpec(reference_label, policy, env),
        ],
        seeds=seeds,
        code_sha=code_sha,
    )
    control = next(arm for arm in evaluated if arm["label"] == "no_reputation")
    reference = next(arm for arm in evaluated if arm["label"] == reference_label)
    effect = _effect(reference, control)
    sign = _sign(
        effect,
        feasible=bool(reference["feasible"]),
        epsilon=config.effect_epsilon,
    )
    return evaluated, reference, control, effect, sign


def _record_two(
    *,
    number: int,
    focus: str,
    question: str,
    arms: Sequence[Mapping[str, object]],
    selected: Mapping[str, object],
    motivating_failure: str,
    observed_failure: str | None,
    next_focus: str | None,
    extras: Mapping[str, object],
    validated: bool | None = None,
) -> dict[str, object]:
    record = _record(
        number=number,
        focus=focus,
        question=question,
        motivating_failure=motivating_failure,
        observed_failure=observed_failure,
        arms=arms,
        selected=selected,
        next_focus=next_focus,
        validated=validated,
    )
    record.update(extras)
    return record


def _initial_checkpoint(
    *,
    config: TwoTimescaleConfig,
    config_hash: str,
    code_sha: str,
) -> dict[str, object]:
    return {
        "version": _CHECKPOINT_VERSION,
        "campaign": config.integration.name,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "last_completed": 52,
        "next_experiment": 53,
        "measurements": [],
        "pending_formation": None,
        "model": None,
        "model_test": None,
        "model_test_validated": False,
        "candidate_policy": None,
        "candidate_label": None,
        "replication_validated": False,
        "validated": None,
    }


def _validate_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    number: int,
    config: TwoTimescaleConfig,
    config_hash: str,
    code_sha: str,
) -> None:
    if int(checkpoint.get("version", -1)) != _CHECKPOINT_VERSION:
        raise ValueError("unsupported two-timescale checkpoint version")
    if checkpoint.get("campaign") != config.integration.name:
        raise ValueError("checkpoint campaign does not match configuration")
    if checkpoint.get("config_hash") != config_hash:
        raise ValueError("checkpoint config hash does not match configuration")
    if checkpoint.get("code_sha") != code_sha:
        raise ValueError("checkpoint code SHA does not match current workflow")
    if int(checkpoint.get("last_completed", -1)) != number - 1:
        raise ValueError("checkpoint does not immediately precede requested experiment")
    if int(checkpoint.get("next_experiment", -1)) != number:
        raise ValueError("checkpoint next_experiment does not match requested experiment")


def _measure_formation(
    connection: Connection[Any],
    *,
    config: TwoTimescaleConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    practice_gain: float,
):
    env = stable_environment(
        config.integration.environment,
        cycles=config.stable_cycles,
        practice_gain=practice_gain,
    )
    arms, reference, control, effect, sign = _paired_experiment(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=number,
        env=env,
        seeds=config.integration.seeds,
        policy=reference_policy(),
    )
    tau_f = formation_timescale(connection, reference, env=env, config=config)
    control_tau_f = formation_timescale(connection, control, env=env, config=config)
    return arms, reference, control, tau_f, control_tau_f, effect, sign


def _measure_forgetting(
    connection: Connection[Any],
    *,
    config: TwoTimescaleConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    practice_gain: float,
):
    env = shift_environment(
        config.integration.environment,
        shift_period=config.measurement_shift_period,
        practice_gain=practice_gain,
    )
    arms, reference, control, effect, sign = _paired_experiment(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=number,
        env=env,
        seeds=config.integration.seeds,
        policy=reference_policy(),
    )
    forgetting = forgetting_metrics(connection, reference, env=env, config=config)
    control_forgetting = forgetting_metrics(connection, control, env=env, config=config)
    return arms, reference, control, forgetting, control_forgetting, effect, sign


def _run_measurement_step(
    connection: Connection[Any],
    *,
    config: TwoTimescaleConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    state: dict[str, object],
) -> dict[str, object]:
    base_gain = config.integration.environment.practice_gain
    formation_specs = {
        53: ("baseline", base_gain, "baseline_forgetting"),
        55: ("slow", config.slow_practice_gain, "slow_forgetting"),
        57: ("fast", config.fast_practice_gain, "fast_forgetting"),
    }
    forgetting_specs = {
        54: ("baseline", "slow_formation"),
        56: ("slow", "fast_formation"),
        58: ("fast", "model_fit"),
    }
    if number in formation_specs:
        label, gain, next_focus = formation_specs[number]
        arms, reference, control, tau_f, control_tau_f, effect, sign = _measure_formation(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            number=number,
            practice_gain=gain,
        )
        state["pending_formation"] = {
            "label": label,
            "practice_gain": gain,
            "tau_f": tau_f,
            "control_tau_f": control_tau_f,
        }
        return _record_two(
            number=number,
            focus=f"{label}_formation",
            question="How quickly does capability-backed specialization form under this practice gain?",
            arms=arms,
            selected=reference if sign == "positive" else control,
            motivating_failure="formation_timescale_unknown",
            observed_failure=None,
            next_focus=next_focus,
            extras={
                "practice_gain": gain,
                "tau_f": tau_f,
                "control_tau_f": control_tau_f,
                "reference_effect": effect,
                "reference_sign": sign,
            },
        )

    label, next_focus = forgetting_specs[number]
    pending = state.get("pending_formation")
    if not isinstance(pending, Mapping) or pending.get("label") != label:
        raise ValueError("checkpoint is missing the matching formation measurement")
    gain = float(pending["practice_gain"])
    arms, reference, control, forgetting, control_forgetting, effect, sign = _measure_forgetting(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=number,
        practice_gain=gain,
    )
    point = {
        "label": label,
        "practice_gain": gain,
        "tau_f": float(pending["tau_f"]),
        "control_tau_f": float(pending["control_tau_f"]),
        "tau_d": forgetting["tau_d"],
        "control_tau_d": control_forgetting["tau_d"],
        "tau_r": float(config.measurement_shift_period),
        "ratio_f": config.measurement_shift_period / max(float(pending["tau_f"]), 1.0),
        "ratio_d": config.measurement_shift_period / max(forgetting["tau_d"], 1.0),
        "reference_effect": effect,
        "reference_sign": sign,
    }
    measurements = [dict(item) for item in state["measurements"]]  # type: ignore[arg-type]
    measurements.append(point)
    state["measurements"] = measurements
    state["pending_formation"] = None
    return _record_two(
        number=number,
        focus=f"{label}_forgetting",
        question="How quickly does obsolete specialization dissolve after a clean skill remap?",
        arms=arms,
        selected=reference if sign == "positive" else control,
        motivating_failure="forgetting_timescale_unknown",
        observed_failure=sign,
        next_focus=next_focus,
        extras={
            "practice_gain": gain,
            "tau_f": point["tau_f"],
            "tau_d": forgetting["tau_d"],
            "control_tau_d": control_forgetting["tau_d"],
            "pre_incumbent_share": forgetting["pre_incumbent_share"],
            "late_incumbent_share": forgetting["late_incumbent_share"],
            "reference_effect": effect,
            "reference_sign": sign,
        },
    )


def _run_model_test(
    connection: Connection[Any],
    *,
    config: TwoTimescaleConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    measurements = [dict(item) for item in state["measurements"]]  # type: ignore[arg-type]
    if len(measurements) != 3:
        raise ValueError("three paired formation/forgetting measurements are required")
    model = fit_two_timescale_rule(measurements)
    tau_f, tau_d = interpolate_timescales(measurements, config.interpolation_practice_gain)
    boundary = max(model["theta_f"] * tau_f, model["theta_d"] * tau_d)
    shift = clamp_shift(config, config.challenge_multiplier * boundary)
    env = shift_environment(
        config.integration.environment,
        shift_period=shift,
        practice_gain=config.interpolation_practice_gain,
    )
    ratio_f = shift / max(tau_f, 1.0)
    ratio_d = shift / max(tau_d, 1.0)
    score = model_score(
        ratio_f=ratio_f,
        ratio_d=ratio_d,
        theta_f=model["theta_f"],
        theta_d=model["theta_d"],
    )
    predicted = model_sign(score, neutral_band=config.model_neutral_band)
    arms, reference, control, effect, observed = _paired_experiment(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=59,
        env=env,
        seeds=config.integration.seeds,
        policy=reference_policy(),
    )
    validated = model["accuracy"] >= config.minimum_model_accuracy and observed == predicted
    state["model"] = model
    state["model_test"] = {
        "practice_gain": config.interpolation_practice_gain,
        "tau_f": tau_f,
        "tau_d": tau_d,
        "shift_period": shift,
        "ratio_f": ratio_f,
        "ratio_d": ratio_d,
        "predicted_reference_sign": predicted,
        "observed_reference_sign": observed,
    }
    state["model_test_validated"] = validated
    return _record_two(
        number=59,
        focus="two_timescale_model",
        question="Does the fitted two-timescale rule predict reputation feasibility on a new practice gain?",
        arms=arms,
        selected=reference if observed == "positive" else control,
        motivating_failure="one_dimensional_timescale_failure",
        observed_failure=None if validated else "model_prediction",
        next_focus="derived_mechanism",
        extras={
            "practice_gain": config.interpolation_practice_gain,
            "tau_f": tau_f,
            "tau_d": tau_d,
            "theta_f": model["theta_f"],
            "theta_d": model["theta_d"],
            "model_accuracy": model["accuracy"],
            "model_score": score,
            "test_shift_period": shift,
            "predicted_reference_sign": predicted,
            "observed_reference_sign": observed,
            "reference_effect": effect,
        },
        validated=validated,
    )


def _run_mechanism_test(
    connection: Connection[Any],
    *,
    config: TwoTimescaleConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    model = state.get("model")
    test = state.get("model_test")
    if not isinstance(model, Mapping) or not isinstance(test, Mapping):
        raise ValueError("checkpoint is missing fitted model state")
    shift = int(test["shift_period"])
    tau_f = float(test["tau_f"])
    tau_d = float(test["tau_d"])
    ratio_f = shift / max(tau_f, 1.0)
    ratio_d = shift / max(tau_d, 1.0)
    scale = gate_scale(
        ratio_f=ratio_f,
        ratio_d=ratio_d,
        theta_f=float(model["theta_f"]),
        theta_d=float(model["theta_d"]),
    )
    reference = reference_policy()
    gated = replace(reference, weight=reference.weight * scale)
    env = shift_environment(
        config.integration.environment,
        shift_period=shift,
        practice_gain=float(test["practice_gain"]),
    )
    arms, _, _ = _run_experiment(
        connection,
        config=config.integration,
        config_hash=config_hash,
        number=60,
        arms=[
            ArmSpec("no_reputation", ReputationPolicy(), env),
            ArmSpec("full_reputation", reference, env),
            ArmSpec("two_timescale_gated", gated, env),
        ],
        seeds=config.integration.seeds,
        code_sha=code_sha,
    )
    control = next(arm for arm in arms if arm["label"] == "no_reputation")
    candidates = [
        arm
        for arm in arms
        if arm["label"] != "no_reputation" and bool(arm["feasible"])
    ]
    best = max(candidates, key=lambda arm: float(arm["utility"]), default=control)
    selected = best if float(best["utility"]) >= float(control["utility"]) else control
    if selected["label"] == "two_timescale_gated":
        chosen_policy = gated
    elif selected["label"] == "full_reputation":
        chosen_policy = reference
    else:
        chosen_policy = ReputationPolicy()
    state["candidate_policy"] = chosen_policy.as_dict()
    state["candidate_label"] = selected["label"]
    return _record_two(
        number=60,
        focus="derived_mechanism",
        question="Can a gate derived from formation and forgetting timescales improve the challenged regime?",
        arms=arms,
        selected=selected,
        motivating_failure="model_prediction",
        observed_failure=None if bool(selected["feasible"]) else "mechanism",
        next_focus="independent_replication",
        extras={
            "practice_gain": float(test["practice_gain"]),
            "tau_f": tau_f,
            "tau_d": tau_d,
            "theta_f": float(model["theta_f"]),
            "theta_d": float(model["theta_d"]),
            "test_shift_period": shift,
            "gate_scale": scale,
        },
    )


def _run_replication(
    connection: Connection[Any],
    *,
    config: TwoTimescaleConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    test = state.get("model_test")
    chosen = state.get("candidate_policy")
    if not isinstance(test, Mapping) or not isinstance(chosen, Mapping):
        raise ValueError("checkpoint is missing candidate mechanism state")
    policy = _policy_from_mapping(chosen)
    env = shift_environment(
        config.integration.environment,
        shift_period=int(test["shift_period"]),
        practice_gain=float(test["practice_gain"]),
    )
    arms, candidate, control, effect, sign = _paired_experiment(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=61,
        env=env,
        seeds=config.replication_seeds,
        policy=policy,
        reference_label="candidate_policy",
    )
    invariants = candidate["invariants"]
    assert isinstance(invariants, Mapping)
    validated = (
        bool(candidate["feasible"])
        and effect >= -config.integration.success_tolerance
        and all(bool(value) for value in invariants.values())
    )
    state["replication_validated"] = validated
    return _record_two(
        number=61,
        focus="independent_replication",
        question="Does the candidate mechanism remain feasible on independent seeds?",
        arms=arms,
        selected=candidate if validated else control,
        motivating_failure="generalization",
        observed_failure=None if validated else sign,
        next_focus="unseen_holdout",
        extras={
            "practice_gain": float(test["practice_gain"]),
            "tau_f": float(test["tau_f"]),
            "tau_d": float(test["tau_d"]),
            "test_shift_period": int(test["shift_period"]),
            "candidate_effect": effect,
        },
        validated=validated,
    )


def _run_holdout(
    connection: Connection[Any],
    *,
    config: TwoTimescaleConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    measurements = [dict(item) for item in state["measurements"]]  # type: ignore[arg-type]
    model = state.get("model")
    chosen = state.get("candidate_policy")
    test = state.get("model_test")
    if not isinstance(model, Mapping) or not isinstance(chosen, Mapping) or not isinstance(test, Mapping):
        raise ValueError("checkpoint is missing holdout model state")
    tau_f, tau_d = interpolate_timescales(measurements, config.holdout_practice_gain)
    boundary = max(float(model["theta_f"]) * tau_f, float(model["theta_d"]) * tau_d)
    multiplier = (
        config.holdout_multiplier
        if str(test["predicted_reference_sign"]) != "positive"
        else config.challenge_multiplier
    )
    shift = clamp_shift(config, multiplier * boundary)
    ratio_f = shift / max(tau_f, 1.0)
    ratio_d = shift / max(tau_d, 1.0)
    score = model_score(
        ratio_f=ratio_f,
        ratio_d=ratio_d,
        theta_f=float(model["theta_f"]),
        theta_d=float(model["theta_d"]),
    )
    predicted = model_sign(score, neutral_band=config.model_neutral_band)
    env = replace(
        config.integration.environment,
        cycles=max(config.integration.holdout_cycles, shift * 2),
        shift_period=shift,
        practice_gain=config.holdout_practice_gain,
        candidate_count=config.integration.holdout_candidate_count,
    )
    candidate_policy = _policy_from_mapping(chosen)
    arms, _, _ = _run_experiment(
        connection,
        config=config.integration,
        config_hash=config_hash,
        number=62,
        arms=[
            ArmSpec("no_reputation", ReputationPolicy(), env),
            ArmSpec("reference_reputation", reference_policy(), env),
            ArmSpec("candidate_policy", candidate_policy, env),
        ],
        seeds=config.integration.holdout_seeds,
        code_sha=code_sha,
    )
    control = next(arm for arm in arms if arm["label"] == "no_reputation")
    reference = next(arm for arm in arms if arm["label"] == "reference_reputation")
    candidate = next(arm for arm in arms if arm["label"] == "candidate_policy")
    reference_effect = _effect(reference, control)
    observed = _sign(
        reference_effect,
        feasible=bool(reference["feasible"]),
        epsilon=config.effect_epsilon,
    )
    candidate_effect = _effect(candidate, control)
    invariants = candidate["invariants"]
    assert isinstance(invariants, Mapping)
    validated = (
        bool(state["model_test_validated"])
        and bool(state["replication_validated"])
        and observed == predicted
        and bool(candidate["feasible"])
        and candidate_effect >= -config.integration.success_tolerance
        and all(bool(value) for value in invariants.values())
    )
    state["validated"] = validated
    return _record_two(
        number=62,
        focus="unseen_holdout",
        question="Does the two-timescale rule predict reputation on unseen seeds and an unseen practice gain?",
        arms=arms,
        selected=candidate,
        motivating_failure="generalization",
        observed_failure=None if validated else "model_or_candidate",
        next_focus=None,
        extras={
            "practice_gain": config.holdout_practice_gain,
            "tau_f": tau_f,
            "tau_d": tau_d,
            "theta_f": float(model["theta_f"]),
            "theta_d": float(model["theta_d"]),
            "model_accuracy": float(model["accuracy"]),
            "model_score": score,
            "test_shift_period": shift,
            "predicted_reference_sign": predicted,
            "observed_reference_sign": observed,
            "reference_effect": reference_effect,
            "candidate_effect": candidate_effect,
        },
        validated=validated,
    )


def run_two_timescale_step(
    connection: Connection[Any],
    *,
    config: TwoTimescaleConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    checkpoint: Mapping[str, object] | None,
    output_dir: str | Path,
) -> dict[str, object]:
    if not _FIRST_EXPERIMENT <= number <= _LAST_EXPERIMENT:
        raise ValueError("experiment number must be between 53 and 62")
    if checkpoint is None:
        if number != _FIRST_EXPERIMENT:
            raise ValueError("only Experiment 053 may start without a checkpoint")
        state = _initial_checkpoint(config=config, config_hash=config_hash, code_sha=code_sha)
    else:
        _validate_checkpoint(
            checkpoint,
            number=number,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
        )
        state = dict(checkpoint)

    if 53 <= number <= 58:
        record = _run_measurement_step(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            number=number,
            state=state,
        )
    elif number == 59:
        record = _run_model_test(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            state=state,
        )
    elif number == 60:
        record = _run_mechanism_test(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            state=state,
        )
    elif number == 61:
        record = _run_replication(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            state=state,
        )
    else:
        record = _run_holdout(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            state=state,
        )

    state["last_completed"] = number
    state["next_experiment"] = number + 1 if number < _LAST_EXPERIMENT else None
    write_step_artifacts(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        output_dir=output_dir,
        record=record,
        checkpoint=state,
    )
    return {
        "experiment": record,
        "checkpoint": state,
        "completed": number,
        "validated": state.get("validated") if number == _LAST_EXPERIMENT else None,
    }


def load_checkpoint(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("checkpoint must be a JSON object")
    return value


__all__ = [
    "TwoTimescaleConfig",
    "load_checkpoint",
    "load_two_timescale_config",
    "run_two_timescale_step",
]
