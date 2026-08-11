"""Checkpoint state machine for Matching Objective Experiments 093–098."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from psycopg import Connection

from .lifecycle_corrections import (
    corrected_lifecycle_effects,
    corrected_lifecycle_feasible,
    corrected_lifecycle_utility,
)
from .matching_campaign import run_matching_arms
from .matching_config import (
    MatchingConfig,
    MatchingObjectiveSpec,
    load_matching_config,
    matching_environment,
    with_blend,
)

_CHECKPOINT_VERSION = 1
_FIRST_EXPERIMENT = 93
_LAST_EXPERIMENT = 98


def _initial_checkpoint(
    *, config: MatchingConfig, config_hash: str, code_sha: str
) -> dict[str, object]:
    return {
        "version": _CHECKPOINT_VERSION,
        "campaign": config.integration.name,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "last_completed": 92,
        "next_experiment": 93,
        "selected_objective": None,
        "screen_validated": False,
        "decomposition_validated": False,
        "same_bid_causal_validated": False,
        "response_validated": False,
        "rapid_shift_validated": False,
        "reversal_validated": False,
        "replication_validated": False,
        "validated": None,
        "strong_matching_causal": False,
    }


def _validate_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    number: int,
    config: MatchingConfig,
    config_hash: str,
    code_sha: str,
) -> None:
    if int(checkpoint.get("version", -1)) != _CHECKPOINT_VERSION:
        raise ValueError("unsupported matching checkpoint version")
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


def _matching_effects(
    arm: Mapping[str, object], control: Mapping[str, object]
) -> dict[str, float]:
    effects = corrected_lifecycle_effects(arm, control)
    metrics = _metrics(arm)
    baseline = _metrics(control)
    effects.update(
        {
            "objective_override_rate": float(metrics["objective_override_rate"]),
            "same_bid_logical_improvement": float(metrics["same_bid_logical_improvement"]),
            "selected_confidence_reduction": (
                float(baseline["mean_selected_bid_confidence"])
                - float(metrics["mean_selected_bid_confidence"])
            ),
            "max_confidence_selection_reduction": (
                float(baseline["selected_max_confidence_share"])
                - float(metrics["selected_max_confidence_share"])
            ),
        }
    )
    return effects


def _utility(arm: Mapping[str, object]) -> float:
    metrics = _metrics(arm)
    base = corrected_lifecycle_utility(metrics)  # type: ignore[arg-type]
    return (
        base
        + 0.06 * float(metrics["same_bid_logical_improvement"])
        + 0.02 * float(metrics["objective_override_rate"])
    )


def _hard_gate(
    arm: Mapping[str, object],
    control: Mapping[str, object],
    *,
    config: MatchingConfig,
) -> tuple[bool, bool, dict[str, float]]:
    effects = _matching_effects(arm, control)
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
        and effects["logical_incumbent_reduction"] >= config.minimum_logical_improvement
        and effects["knowledge_effect"] >= -config.knowledge_tolerance
        and effects["objective_override_rate"] >= config.minimum_objective_override_rate
        and effects["same_bid_logical_improvement"]
        >= config.minimum_same_bid_logical_improvement
        and float(metrics.get("exit_count", 0.0)) == 0.0
    )
    return hard, feasible, effects


def _evaluate(
    arms: Sequence[dict[str, object]],
    *,
    config: MatchingConfig,
    control_label: str = "baseline_objective",
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object], bool]:
    control = next(arm for arm in arms if arm["label"] == control_label)
    evaluated: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    zero_effects = {
        "success_effect": 0.0,
        "logical_incumbent_reduction": 0.0,
        "identity_incumbent_reduction": 0.0,
        "hhi_reduction": 0.0,
        "knowledge_effect": 0.0,
        "cultural_hhi_reduction": 0.0,
        "objective_override_rate": 0.0,
        "same_bid_logical_improvement": 0.0,
        "selected_confidence_reduction": 0.0,
        "max_confidence_selection_reduction": 0.0,
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
                float(item["effects"]["logical_incumbent_reduction"]),  # type: ignore[index]
                float(item["effects"]["same_bid_logical_improvement"]),  # type: ignore[index]
                float(item["utility"]),
                str(item["label"]),
            ),
        )
        return evaluated, selected, control, True

    selected = max(
        candidates,
        key=lambda item: (
            float(item["effects"]["logical_incumbent_reduction"]),  # type: ignore[index]
            float(item["effects"]["same_bid_logical_improvement"]),  # type: ignore[index]
            float(item["effects"]["objective_override_rate"]),  # type: ignore[index]
            float(item["effects"]["success_effect"]),  # type: ignore[index]
            float(item["utility"]),
            str(item["label"]),
        ),
    )
    return evaluated, selected, control, False


def _spec_from_arm(arm: Mapping[str, object]) -> MatchingObjectiveSpec:
    raw = arm.get("matching_objective")
    if not isinstance(raw, Mapping):
        raise ValueError("arm missing matching objective specification")
    return MatchingObjectiveSpec.from_mapping(raw)


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
        "causal_family": "matching_objective",
        "arms": list(arms),
        "selected_label": selected["label"],
        "next_experiment_focus": next_focus,
        "validated": validated,
        **dict(extras),
    }


def _screen(
    connection: Connection[Any],
    *,
    config: MatchingConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    specs = [
        ("baseline_objective", MatchingObjectiveSpec()),
        (
            "confidence_light",
            MatchingObjectiveSpec(
                mode="weighted",
                confidence_weight=0.15,
                price_weight=0.50,
                speed_weight=0.35,
            ),
        ),
        (
            "price_speed_only",
            MatchingObjectiveSpec(
                mode="weighted",
                confidence_weight=0.0,
                price_weight=0.60,
                speed_weight=0.40,
            ),
        ),
        (
            "capped_confidence",
            MatchingObjectiveSpec(
                mode="capped_confidence",
                confidence_weight=0.45,
                price_weight=0.35,
                speed_weight=0.20,
                confidence_cap=0.65,
            ),
        ),
        ("geometric_balance", MatchingObjectiveSpec(mode="geometric")),
    ]
    arms = run_matching_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=93,
        specs=specs,
    )
    evaluated, selected, control, validated = _evaluate(arms, config=config)
    spec = _spec_from_arm(selected)
    state["selected_objective"] = spec.as_dict()
    state["screen_validated"] = validated
    effects = _matching_effects(selected, control)
    return _record(
        number=93,
        focus="objective_screen",
        question=(
            "Can changing only the sealed-bid matching objective reduce logical capture while "
            "preserving quality and public knowledge?"
        ),
        arms=evaluated,
        selected=selected,
        next_focus="decomposition_exact_bid_replay",
        validated=validated,
        extras={
            **effects,
            "screen_validated": validated,
            "selected_objective": spec.as_dict(),
        },
    )


def _decompose(
    connection: Connection[Any],
    *,
    config: MatchingConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_objective")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected matching objective")
    spec = MatchingObjectiveSpec.from_mapping(raw)
    arms = run_matching_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=94,
        specs=[
            ("baseline_objective", MatchingObjectiveSpec()),
            ("candidate_full", replace(spec, restore_after_cycle=None)),
            ("half_strength", with_blend(spec, 0.5)),
        ],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_full")
    hard, _, effects = _hard_gate(candidate, control, config=config)
    same_bid = (
        effects["objective_override_rate"] >= config.minimum_objective_override_rate
        and effects["same_bid_logical_improvement"]
        >= config.minimum_same_bid_logical_improvement
        and float(_metrics(candidate)["objective_replay_exact_rate"]) == 1.0
    )
    validated = bool(state["screen_validated"]) and hard and same_bid
    state["decomposition_validated"] = validated
    state["same_bid_causal_validated"] = same_bid
    return _record(
        number=94,
        focus="decomposition_exact_bid_replay",
        question=(
            "Does exact replay of the same sealed bid sets show that the selected objective itself "
            "causes the winner changes and logical-plasticity effect?"
        ),
        arms=evaluated,
        selected=candidate,
        next_focus="bounded_response",
        validated=validated,
        extras={
            **effects,
            "screen_validated": bool(state["screen_validated"]),
            "decomposition_validated": validated,
            "same_bid_causal_validated": same_bid,
            "selected_objective": spec.as_dict(),
        },
    )


def _response(
    connection: Connection[Any],
    *,
    config: MatchingConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_objective")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected matching objective")
    spec = MatchingObjectiveSpec.from_mapping(raw)
    specs: list[tuple[str, MatchingObjectiveSpec]] = [
        ("baseline_objective", MatchingObjectiveSpec())
    ]
    for blend in config.response_blends:
        specs.append((f"objective_{blend:g}", with_blend(spec, blend)))
    arms = run_matching_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=95,
        specs=specs,
    )
    evaluated, selected, control, _ = _evaluate(arms, config=config)
    passing = [
        arm
        for arm in evaluated
        if arm["label"] != "baseline_objective" and bool(arm.get("hard_gate"))
    ]
    validated = bool(state["decomposition_validated"]) and len(passing) >= 2
    if passing:
        selected = max(passing, key=lambda arm: (float(arm["utility"]), str(arm["label"])))
    selected_spec = _spec_from_arm(selected)
    state["selected_objective"] = selected_spec.as_dict()
    state["response_validated"] = validated
    effects = _matching_effects(selected, control)
    return _record(
        number=95,
        focus="bounded_response",
        question=(
            "Does the matching-objective effect survive multiple intervention strengths rather "
            "than a single tuned point?"
        ),
        arms=evaluated,
        selected=selected,
        next_focus="rapid_shift_reversal",
        validated=validated,
        extras={
            **effects,
            "decomposition_validated": bool(state["decomposition_validated"]),
            "response_validated": validated,
            "passing_settings": len(passing),
            "selected_objective": selected_spec.as_dict(),
        },
    )


def _rapid_reversal(
    connection: Connection[Any],
    *,
    config: MatchingConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_objective")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected matching objective")
    spec = MatchingObjectiveSpec.from_mapping(raw)
    env = matching_environment(config, shift_period=config.rapid_shift_period)
    restore_cycle = max(1, int(round(env.cycles * config.reversal_restore_fraction)))
    reversal = replace(spec, restore_after_cycle=restore_cycle)
    arms = run_matching_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=96,
        environment=env,
        specs=[
            ("baseline_objective", MatchingObjectiveSpec()),
            ("candidate_objective", replace(spec, restore_after_cycle=None)),
            ("restore_baseline_midrun", reversal),
        ],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_objective")
    reversal_arm = next(arm for arm in evaluated if arm["label"] == "restore_baseline_midrun")
    hard, _, effects = _hard_gate(candidate, control, config=config)
    rapid_validated = bool(state["response_validated"]) and hard
    reversal_metrics = _metrics(reversal_arm)
    reversal_validated = (
        rapid_validated
        and float(reversal_metrics["pre_restore_objective_override_rate"])
        >= config.minimum_objective_override_rate
        and float(reversal_metrics["post_restore_objective_override_rate"]) <= 1e-12
        and float(reversal_metrics["restoration_winner_rebound"])
        >= config.minimum_relock_winner_rebound
    )
    state["rapid_shift_validated"] = rapid_validated
    state["reversal_validated"] = reversal_validated
    return _record(
        number=96,
        focus="rapid_shift_reversal",
        question=(
            "Does the frozen matching objective survive faster remapping, and does restoring the "
            "baseline objective begin recreating lock-in without restoring agent state?"
        ),
        arms=evaluated,
        selected=candidate,
        next_focus="independent_replication",
        validated=rapid_validated,
        extras={
            **effects,
            "rapid_shift_validated": rapid_validated,
            "reversal_validated": reversal_validated,
            "restore_after_cycle": restore_cycle,
            "pre_restore_objective_override_rate": float(
                reversal_metrics["pre_restore_objective_override_rate"]
            ),
            "post_restore_objective_override_rate": float(
                reversal_metrics["post_restore_objective_override_rate"]
            ),
            "restoration_winner_rebound": float(reversal_metrics["restoration_winner_rebound"]),
            "selected_objective": spec.as_dict(),
        },
    )


def _replication(
    connection: Connection[Any],
    *,
    config: MatchingConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_objective")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected matching objective")
    spec = MatchingObjectiveSpec.from_mapping(raw)
    arms = run_matching_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=97,
        seeds=config.replication_seeds,
        specs=[
            ("baseline_objective", MatchingObjectiveSpec()),
            ("candidate_objective", replace(spec, restore_after_cycle=None)),
        ],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_objective")
    hard, _, effects = _hard_gate(candidate, control, config=config)
    validated = bool(state["rapid_shift_validated"]) and hard
    state["replication_validated"] = validated
    return _record(
        number=97,
        focus="independent_replication",
        question="Does the frozen matching objective reproduce on independent seeds without retuning?",
        arms=evaluated,
        selected=candidate,
        next_focus="unseen_holdout",
        validated=validated,
        extras={
            **effects,
            "replication_validated": validated,
            "selected_objective": spec.as_dict(),
        },
    )


def _holdout(
    connection: Connection[Any],
    *,
    config: MatchingConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_objective")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected matching objective")
    spec = MatchingObjectiveSpec.from_mapping(raw)
    env = matching_environment(
        config,
        cycles=config.integration.holdout_cycles,
        shift_period=config.integration.holdout_shift_period,
        candidate_count=config.integration.holdout_candidate_count,
    )
    restore_cycle = max(1, int(round(env.cycles * config.holdout_restore_fraction)))
    reversal = replace(spec, restore_after_cycle=restore_cycle)
    predicted_relock = bool(state["reversal_validated"])
    arms = run_matching_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=98,
        seeds=config.integration.holdout_seeds,
        environment=env,
        specs=[
            ("baseline_objective", MatchingObjectiveSpec()),
            ("candidate_objective", replace(spec, restore_after_cycle=None)),
            ("holdout_restore_baseline", reversal),
        ],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_objective")
    reversal_arm = next(arm for arm in evaluated if arm["label"] == "holdout_restore_baseline")
    hard, _, effects = _hard_gate(candidate, control, config=config)
    reversal_metrics = _metrics(reversal_arm)
    observed_relock = (
        float(reversal_metrics["pre_restore_objective_override_rate"])
        >= config.minimum_objective_override_rate
        and float(reversal_metrics["post_restore_objective_override_rate"]) <= 1e-12
        and float(reversal_metrics["restoration_winner_rebound"])
        >= config.minimum_relock_winner_rebound
    )
    prediction_agreement = predicted_relock == observed_relock
    validated = (
        bool(state["screen_validated"])
        and bool(state["decomposition_validated"])
        and bool(state["same_bid_causal_validated"])
        and bool(state["response_validated"])
        and bool(state["rapid_shift_validated"])
        and bool(state["replication_validated"])
        and hard
        and prediction_agreement
    )
    strong_matching_causal = validated and bool(state["reversal_validated"]) and observed_relock
    state["validated"] = validated
    state["strong_matching_causal"] = strong_matching_causal
    return _record(
        number=98,
        focus="unseen_holdout",
        question=(
            "Does the frozen matching objective generalize to unseen seeds and remapping, and "
            "does the predeclared restoration/re-lock prediction hold without agent-state reset?"
        ),
        arms=evaluated,
        selected=candidate,
        next_focus=None,
        validated=validated,
        extras={
            **effects,
            "screen_validated": bool(state["screen_validated"]),
            "decomposition_validated": bool(state["decomposition_validated"]),
            "same_bid_causal_validated": bool(state["same_bid_causal_validated"]),
            "response_validated": bool(state["response_validated"]),
            "rapid_shift_validated": bool(state["rapid_shift_validated"]),
            "reversal_validated": bool(state["reversal_validated"]),
            "replication_validated": bool(state["replication_validated"]),
            "relock_predicted": predicted_relock,
            "relock_observed": observed_relock,
            "relock_prediction_agreement": prediction_agreement,
            "strong_matching_causal": strong_matching_causal,
            "restoration_winner_rebound": float(reversal_metrics["restoration_winner_rebound"]),
            "selected_objective": spec.as_dict(),
        },
    )


_STEPS = {
    93: _screen,
    94: _decompose,
    95: _response,
    96: _rapid_reversal,
    97: _replication,
    98: _holdout,
}


def run_matching_step(
    connection: Connection[Any],
    *,
    config: MatchingConfig,
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
            raise ValueError("Experiment 093 must start without a checkpoint")
        state = _initial_checkpoint(config=config, config_hash=config_hash, code_sha=code_sha)
    else:
        if checkpoint is None:
            raise ValueError("later matching experiments require a checkpoint")
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

    from .matching_notebook import write_step_artifacts

    write_step_artifacts(output_dir, record=record, checkpoint=state)
    return {"record": record, "checkpoint": state}


def load_checkpoint(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("checkpoint must be a JSON object")
    return value


__all__ = ["load_checkpoint", "load_matching_config", "run_matching_step"]
