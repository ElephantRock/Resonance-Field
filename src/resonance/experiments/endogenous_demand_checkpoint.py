"""Checkpoint state machine for Endogenous Demand Feedback Experiments 105–110."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from psycopg import Connection

from .endogenous_demand_campaign import run_endogenous_arms
from .endogenous_demand_config import (
    EndogenousDemandConfig,
    EndogenousDemandSpec,
    endogenous_environment,
    load_endogenous_demand_config,
)
from .lifecycle_corrections import (
    corrected_lifecycle_effects,
    corrected_lifecycle_feasible,
    corrected_lifecycle_utility,
)

_CHECKPOINT_VERSION = 1
_FIRST_EXPERIMENT = 105
_LAST_EXPERIMENT = 110


def _initial_checkpoint(
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
) -> dict[str, object]:
    return {
        "version": _CHECKPOINT_VERSION,
        "campaign": config.integration.name,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "last_completed": 104,
        "next_experiment": 105,
        "selected_strength": None,
        "screen_validated": False,
        "decomposition_validated": False,
        "response_validated": False,
        "reversal_validated": False,
        "replication_validated": False,
        "validated": None,
        "strong_endogenous_demand_causal": False,
    }


def _validate_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    number: int,
    config: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
) -> None:
    if int(checkpoint.get("version", -1)) != _CHECKPOINT_VERSION:
        raise ValueError("unsupported endogenous-demand checkpoint version")
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


def _metrics(arm: Mapping[str, object]) -> Mapping[str, object]:
    value = arm["metrics"]
    assert isinstance(value, Mapping)
    return value


def _effects(arm: Mapping[str, object], control: Mapping[str, object]) -> dict[str, float]:
    effects = corrected_lifecycle_effects(arm, control)
    metrics = _metrics(arm)
    baseline = _metrics(control)
    effects.update(
        {
            "logical_incumbent_increase": (
                float(metrics["early_incumbent_share"])
                - float(baseline["early_incumbent_share"])
            ),
            "identity_incumbent_increase": (
                float(metrics["identity_early_incumbent_share"])
                - float(baseline["identity_early_incumbent_share"])
            ),
            "feedback_override_effect": (
                float(metrics["feedback_override_rate"])
                - float(baseline["feedback_override_rate"])
            ),
            "alignment_effect": (
                float(metrics["success_same_domain_follow_on_alignment"])
                - float(baseline["success_same_domain_follow_on_alignment"])
            ),
            "demand_hhi_effect": (
                float(metrics["generated_demand_hhi"])
                - float(baseline["generated_demand_hhi"])
            ),
        }
    )
    return effects


def _utility(arm: Mapping[str, object]) -> float:
    metrics = _metrics(arm)
    return (
        corrected_lifecycle_utility(metrics)  # type: ignore[arg-type]
        + 0.08 * float(metrics["early_incumbent_share"])
        + 0.02 * float(metrics["feedback_override_rate"])
    )


def _hard_gate(
    arm: Mapping[str, object],
    control: Mapping[str, object],
    *,
    config: EndogenousDemandConfig,
) -> tuple[bool, bool, dict[str, float]]:
    effects = _effects(arm, control)
    feasible = corrected_lifecycle_feasible(
        arm,
        control,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    metrics = _metrics(arm)
    invariants = arm["invariants"]
    assert isinstance(invariants, Mapping)
    hard = (
        feasible
        and all(bool(value) for value in invariants.values())
        and effects["success_effect"] >= -config.integration.success_tolerance
        and effects["logical_incumbent_increase"] >= config.minimum_logical_change
        and effects["knowledge_effect"] >= -config.knowledge_tolerance
        and float(metrics["feedback_override_rate"]) >= config.minimum_feedback_override
        and float(metrics.get("exit_count", 0.0)) == 0.0
    )
    return hard, feasible, effects


def _evaluate(
    arms: Sequence[dict[str, object]],
    *,
    config: EndogenousDemandConfig,
    control_label: str = "exogenous_control",
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object], bool]:
    control = next(arm for arm in arms if arm["label"] == control_label)
    evaluated: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    zero_effects = {
        "success_effect": 0.0,
        "logical_incumbent_reduction": 0.0,
        "logical_incumbent_increase": 0.0,
        "identity_incumbent_reduction": 0.0,
        "identity_incumbent_increase": 0.0,
        "hhi_reduction": 0.0,
        "knowledge_effect": 0.0,
        "cultural_hhi_reduction": 0.0,
        "feedback_override_effect": 0.0,
        "alignment_effect": 0.0,
        "demand_hhi_effect": 0.0,
    }
    for arm in arms:
        item = dict(arm)
        item["utility"] = _utility(arm)
        if arm["label"] == control_label:
            item["feasible"] = True
            item["hard_gate"] = True
            item["effects"] = dict(zero_effects)
        else:
            hard, feasible, effects = _hard_gate(arm, control, config=config)
            item["feasible"] = feasible
            item["hard_gate"] = hard
            item["effects"] = effects
            candidates.append(item)
        evaluated.append(item)

    passing = [item for item in candidates if bool(item["hard_gate"])]
    if passing:
        selected = max(
            passing,
            key=lambda item: (
                float(item["effects"]["logical_incumbent_increase"]),  # type: ignore[index]
                float(item["effects"]["success_effect"]),  # type: ignore[index]
                -float(item["endogenous_demand"]["strength"]),  # type: ignore[index]
            ),
        )
        return evaluated, selected, control, True

    selected = max(
        candidates,
        key=lambda item: (
            float(item["effects"]["logical_incumbent_increase"]),  # type: ignore[index]
            float(item["effects"]["success_effect"]),  # type: ignore[index]
            -float(item["endogenous_demand"]["strength"]),  # type: ignore[index]
        ),
    )
    return evaluated, selected, control, False


def _spec_from_arm(arm: Mapping[str, object]) -> EndogenousDemandSpec:
    raw = arm.get("endogenous_demand")
    if not isinstance(raw, Mapping):
        raise ValueError("arm missing endogenous-demand specification")
    return EndogenousDemandSpec.from_mapping(raw)


def _record(
    *,
    number: int,
    focus: str,
    question: str,
    arms: Sequence[Mapping[str, object]],
    selected: Mapping[str, object],
    next_focus: str | None,
    validated: bool,
    extras: Mapping[str, object],
) -> dict[str, object]:
    return {
        "number": number,
        "focus": focus,
        "question": question,
        "causal_family": "endogenous_demand_feedback",
        "arms": list(arms),
        "selected_label": selected["label"],
        "next_experiment_focus": next_focus,
        "validated": validated,
        **dict(extras),
    }


def _screen(
    connection: Connection[Any],
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    specs = [("exogenous_control", EndogenousDemandSpec())]
    specs.extend(
        (
            f"feedback_{strength:g}",
            EndogenousDemandSpec(mode="closed_loop", strength=strength),
        )
        for strength in config.strengths
    )
    arms = run_endogenous_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=105,
        specs=specs,
    )
    evaluated, selected, control, validated = _evaluate(arms, config=config)
    spec = _spec_from_arm(selected)
    state["selected_strength"] = spec.strength
    state["screen_validated"] = validated
    return _record(
        number=105,
        focus="feedback_screen",
        question=(
            "Does successful completed work feeding future same-domain demand increase logical "
            "incumbency while preserving quality and public knowledge?"
        ),
        arms=evaluated,
        selected=selected,
        next_focus="causal_link_decomposition",
        validated=validated,
        extras={
            **_effects(selected, control),
            "screen_validated": validated,
            "selected_strength": spec.strength,
        },
    )


def _decompose(
    connection: Connection[Any],
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    strength = float(state["selected_strength"])
    arms = run_endogenous_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=106,
        specs=[
            ("exogenous_control", EndogenousDemandSpec()),
            ("aligned_closed_loop", EndogenousDemandSpec(mode="closed_loop", strength=strength)),
            ("permuted_source", EndogenousDemandSpec(mode="permuted_source", strength=strength)),
        ],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    aligned = next(arm for arm in evaluated if arm["label"] == "aligned_closed_loop")
    permuted = next(arm for arm in evaluated if arm["label"] == "permuted_source")
    hard, _, effects = _hard_gate(aligned, control, config=config)
    aligned_increase = effects["logical_incumbent_increase"]
    permuted_increase = _effects(permuted, control)["logical_incumbent_increase"]
    specificity = aligned_increase > permuted_increase
    validated = bool(state["screen_validated"]) and hard and specificity
    state["decomposition_validated"] = validated
    return _record(
        number=106,
        focus="causal_link_decomposition",
        question=(
            "Is same-domain alignment of actual successful work necessary for the lock-in effect, "
            "rather than a generic success-timed demand perturbation?"
        ),
        arms=evaluated,
        selected=aligned,
        next_focus="bounded_strength_response",
        validated=validated,
        extras={
            **effects,
            "screen_validated": bool(state["screen_validated"]),
            "decomposition_validated": validated,
            "aligned_logical_increase": aligned_increase,
            "permuted_logical_increase": permuted_increase,
            "specificity_direction_validated": specificity,
            "selected_strength": strength,
        },
    )


def _response(
    connection: Connection[Any],
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    specs = [("exogenous_control", EndogenousDemandSpec())]
    specs.extend(
        (
            f"feedback_{strength:g}",
            EndogenousDemandSpec(mode="closed_loop", strength=strength),
        )
        for strength in config.strengths
    )
    arms = run_endogenous_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=107,
        specs=specs,
    )
    evaluated, selected, control, _ = _evaluate(arms, config=config)
    candidates = sorted(
        [arm for arm in evaluated if arm["label"] != "exogenous_control"],
        key=lambda arm: float(arm["endogenous_demand"]["strength"]),  # type: ignore[index]
    )
    activation_monotone = all(
        float(_metrics(candidates[index])["feedback_branch_rate"])
        <= float(_metrics(candidates[index + 1])["feedback_branch_rate"])
        for index in range(len(candidates) - 1)
    )
    logical_values = [float(_metrics(arm)["early_incumbent_share"]) for arm in candidates]
    logical_non_decreasing = all(
        logical_values[index] <= logical_values[index + 1]
        for index in range(len(logical_values) - 1)
    )
    logical_span = logical_values[-1] - logical_values[0]
    response_validated = (
        bool(state["decomposition_validated"])
        and activation_monotone
        and logical_non_decreasing
        and logical_span >= config.minimum_logical_change
        and all(
            _effects(arm, control)["success_effect"] >= -config.integration.success_tolerance
            and _effects(arm, control)["knowledge_effect"] >= -config.knowledge_tolerance
            for arm in candidates
        )
    )
    state["response_validated"] = response_validated
    spec = _spec_from_arm(selected)
    return _record(
        number=107,
        focus="bounded_strength_response",
        question=(
            "Across the frozen 0.25/0.50/0.75 feedback bracket, does stronger endogenous feedback "
            "produce a bounded non-decreasing logical-incumbency response?"
        ),
        arms=evaluated,
        selected=selected,
        next_focus="feedback_reversal",
        validated=response_validated,
        extras={
            **_effects(selected, control),
            "decomposition_validated": bool(state["decomposition_validated"]),
            "response_validated": response_validated,
            "activation_monotone": activation_monotone,
            "logical_non_decreasing": logical_non_decreasing,
            "logical_span": logical_span,
            "selected_strength": spec.strength,
        },
    )


def _reversal(
    connection: Connection[Any],
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    strength = float(state["selected_strength"])
    reversal = EndogenousDemandSpec(
        mode="closed_loop",
        strength=strength,
        phase_strengths=(strength, 0.0, strength),
    )
    arms = run_endogenous_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=108,
        specs=[
            ("exogenous_control", EndogenousDemandSpec()),
            ("steady_feedback", EndogenousDemandSpec(mode="closed_loop", strength=strength)),
            ("feedback_on_off_on", reversal),
        ],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    steady = next(arm for arm in evaluated if arm["label"] == "steady_feedback")
    reversal_arm = next(arm for arm in evaluated if arm["label"] == "feedback_on_off_on")
    hard, _, effects = _hard_gate(steady, control, config=config)
    metrics = _metrics(reversal_arm)
    unlock_logical = float(metrics["disable_logical_change"])
    relock_logical = float(metrics["restore_logical_rebound"])
    unlock_repeat = float(metrics["disable_winner_repeat_change"])
    relock_repeat = float(metrics["restore_winner_repeat_rebound"])
    feedback_precedes = (
        float(metrics["feedback_branch_middle"]) < float(metrics["feedback_branch_first"])
        and float(metrics["feedback_branch_final"]) > float(metrics["feedback_branch_middle"])
    )
    validated = (
        bool(state["response_validated"])
        and hard
        and unlock_logical <= -config.minimum_logical_change
        and unlock_repeat <= -config.minimum_winner_repeat_change
        and relock_logical > 0.0
        and relock_repeat >= config.minimum_winner_repeat_change
        and feedback_precedes
    )
    state["reversal_validated"] = validated
    return _record(
        number=108,
        focus="feedback_reversal",
        question=(
            "Without resetting agents, does switching endogenous feedback off release incumbent "
            "continuation and does restoring it recreate reinforcement?"
        ),
        arms=evaluated,
        selected=reversal_arm,
        next_focus="independent_replication",
        validated=validated,
        extras={
            **effects,
            "response_validated": bool(state["response_validated"]),
            "reversal_validated": validated,
            "disable_logical_change": unlock_logical,
            "restore_logical_rebound": relock_logical,
            "disable_winner_repeat_change": unlock_repeat,
            "restore_winner_repeat_rebound": relock_repeat,
            "feedback_temporal_precedence": feedback_precedes,
            "selected_strength": strength,
        },
    )


def _replication(
    connection: Connection[Any],
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    strength = float(state["selected_strength"])
    arms = run_endogenous_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=109,
        seeds=config.replication_seeds,
        specs=[
            ("exogenous_control", EndogenousDemandSpec()),
            ("selected_feedback", EndogenousDemandSpec(mode="closed_loop", strength=strength)),
        ],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    candidate = next(arm for arm in evaluated if arm["label"] == "selected_feedback")
    hard, _, effects = _hard_gate(candidate, control, config=config)
    validated = bool(state["reversal_validated"]) and hard
    state["replication_validated"] = validated
    return _record(
        number=109,
        focus="independent_replication",
        question="Does the frozen success-reinforced endogenous-demand mechanism replicate?",
        arms=evaluated,
        selected=candidate,
        next_focus="unseen_holdout",
        validated=validated,
        extras={
            **effects,
            "replication_validated": validated,
            "selected_strength": strength,
        },
    )


def _holdout(
    connection: Connection[Any],
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    strength = float(state["selected_strength"])
    env = endogenous_environment(
        config,
        cycles=config.integration.holdout_cycles,
        shift_period=config.integration.holdout_shift_period,
        candidate_count=config.integration.holdout_candidate_count,
    )
    predicted_active_lock_in = bool(state["replication_validated"])
    predicted_relock = bool(state["reversal_validated"])
    arms = run_endogenous_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=110,
        seeds=config.integration.holdout_seeds,
        environment=env,
        specs=[
            ("exogenous_control", EndogenousDemandSpec()),
            ("selected_feedback", EndogenousDemandSpec(mode="closed_loop", strength=strength)),
            (
                "holdout_on_off_on",
                EndogenousDemandSpec(
                    mode="closed_loop",
                    strength=strength,
                    phase_strengths=(strength, 0.0, strength),
                ),
            ),
        ],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    candidate = next(arm for arm in evaluated if arm["label"] == "selected_feedback")
    reversal_arm = next(arm for arm in evaluated if arm["label"] == "holdout_on_off_on")
    hard, _, effects = _hard_gate(candidate, control, config=config)
    reversal_metrics = _metrics(reversal_arm)
    observed_active_lock_in = effects["logical_incumbent_increase"] >= config.minimum_logical_change
    observed_relock = (
        float(reversal_metrics["restore_winner_repeat_rebound"])
        >= config.minimum_winner_repeat_change
        and float(reversal_metrics["restore_logical_rebound"]) > 0.0
    )
    prediction_agreement = (
        predicted_active_lock_in == observed_active_lock_in
        and predicted_relock == observed_relock
    )
    validated = (
        bool(state["screen_validated"])
        and bool(state["decomposition_validated"])
        and bool(state["response_validated"])
        and bool(state["reversal_validated"])
        and bool(state["replication_validated"])
        and hard
        and prediction_agreement
    )
    strong = validated and observed_active_lock_in and observed_relock
    state["validated"] = validated
    state["strong_endogenous_demand_causal"] = strong
    return _record(
        number=110,
        focus="unseen_holdout",
        question=(
            "Does the frozen endogenous-demand loop generalize to unseen seeds and reproduce the "
            "predeclared active-lock-in and on/off/on re-lock directions?"
        ),
        arms=evaluated,
        selected=candidate,
        next_focus=None,
        validated=validated,
        extras={
            **effects,
            "screen_validated": bool(state["screen_validated"]),
            "decomposition_validated": bool(state["decomposition_validated"]),
            "response_validated": bool(state["response_validated"]),
            "reversal_validated": bool(state["reversal_validated"]),
            "replication_validated": bool(state["replication_validated"]),
            "active_lock_in_predicted": predicted_active_lock_in,
            "active_lock_in_observed": observed_active_lock_in,
            "relock_predicted": predicted_relock,
            "relock_observed": observed_relock,
            "prediction_agreement": prediction_agreement,
            "strong_endogenous_demand_causal": strong,
            "selected_strength": strength,
        },
    )


_STEPS = {
    105: _screen,
    106: _decompose,
    107: _response,
    108: _reversal,
    109: _replication,
    110: _holdout,
}


def run_endogenous_demand_step(
    connection: Connection[Any],
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    checkpoint: Mapping[str, object] | None,
    output_dir: str | Path,
) -> dict[str, object]:
    if number not in _STEPS:
        raise ValueError(f"experiment must be between {_FIRST_EXPERIMENT} and {_LAST_EXPERIMENT}")
    if number == _FIRST_EXPERIMENT:
        if checkpoint is not None:
            raise ValueError("Experiment 105 must start without a checkpoint")
        state = _initial_checkpoint(config=config, config_hash=config_hash, code_sha=code_sha)
    else:
        if checkpoint is None:
            raise ValueError("later endogenous-demand experiments require a checkpoint")
        _validate_checkpoint(
            checkpoint,
            number=number,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
        )
        state = dict(checkpoint)

    record = _STEPS[number](
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        state=state,
    )
    state["last_completed"] = number
    state["next_experiment"] = number + 1 if number < _LAST_EXPERIMENT else None

    from .endogenous_demand_notebook import write_step_artifacts

    write_step_artifacts(output_dir, record=record, checkpoint=state)
    return {"record": record, "checkpoint": state}


def load_checkpoint(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("checkpoint must be a JSON object")
    return value


__all__ = [
    "load_checkpoint",
    "load_endogenous_demand_config",
    "run_endogenous_demand_step",
]
