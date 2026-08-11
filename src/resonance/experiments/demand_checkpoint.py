"""Checkpoint state machine for Demand-Structure Experiments 099–104."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from psycopg import Connection

from .demand_campaign import run_demand_arms
from .demand_config import DemandConfig, DemandScheduleSpec, demand_environment, load_demand_config
from .lifecycle_corrections import (
    corrected_lifecycle_effects,
    corrected_lifecycle_feasible,
    corrected_lifecycle_utility,
)

_CHECKPOINT_VERSION = 1
_FIRST_EXPERIMENT = 99
_LAST_EXPERIMENT = 104


def _initial_checkpoint(*, config: DemandConfig, config_hash: str, code_sha: str) -> dict[str, object]:
    return {
        "version": _CHECKPOINT_VERSION,
        "campaign": config.integration.name,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "last_completed": 98,
        "next_experiment": 99,
        "selected_schedule": None,
        "screen_validated": False,
        "decomposition_validated": False,
        "response_validated": False,
        "reversal_validated": False,
        "replication_validated": False,
        "validated": None,
        "strong_demand_causal": False,
    }


def _validate_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    number: int,
    config: DemandConfig,
    config_hash: str,
    code_sha: str,
) -> None:
    if int(checkpoint.get("version", -1)) != _CHECKPOINT_VERSION:
        raise ValueError("unsupported demand checkpoint version")
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
            "persistence_reduction": (
                float(baseline["demand_adjacent_repeat_rate"])
                - float(metrics["demand_adjacent_repeat_rate"])
            ),
            "run_length_reduction": (
                float(baseline["demand_mean_run_length"])
                - float(metrics["demand_mean_run_length"])
            ),
            "order_changed_rate": float(metrics["demand_order_changed_rate"]),
        }
    )
    return effects


def _utility(arm: Mapping[str, object]) -> float:
    metrics = _metrics(arm)
    return (
        corrected_lifecycle_utility(metrics)  # type: ignore[arg-type]
        + 0.05 * max(0.0, 0.25 - float(metrics["demand_adjacent_repeat_rate"]))
    )


def _hard_gate(
    arm: Mapping[str, object],
    control: Mapping[str, object],
    *,
    config: DemandConfig,
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
        and effects["logical_incumbent_reduction"] >= config.minimum_logical_improvement
        and effects["knowledge_effect"] >= -config.knowledge_tolerance
        and abs(effects["persistence_reduction"]) >= config.minimum_persistence_change
        and float(metrics.get("exit_count", 0.0)) == 0.0
    )
    return hard, feasible, effects


def _evaluate(
    arms: Sequence[dict[str, object]],
    *,
    config: DemandConfig,
    control_label: str = "baseline_order",
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
        "persistence_reduction": 0.0,
        "run_length_reduction": 0.0,
        "order_changed_rate": 0.0,
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
                float(item["effects"]["persistence_reduction"]),  # type: ignore[index]
                float(item["utility"]),
                str(item["label"]),
            ),
        )
        return evaluated, selected, control, True

    selected = max(
        candidates,
        key=lambda item: (
            float(item["effects"]["logical_incumbent_reduction"]),  # type: ignore[index]
            float(item["effects"]["persistence_reduction"]),  # type: ignore[index]
            float(item["effects"]["success_effect"]),  # type: ignore[index]
            float(item["utility"]),
            str(item["label"]),
        ),
    )
    return evaluated, selected, control, False


def _spec_from_arm(arm: Mapping[str, object]) -> DemandScheduleSpec:
    raw = arm.get("demand_schedule")
    if not isinstance(raw, Mapping):
        raise ValueError("arm missing demand schedule specification")
    return DemandScheduleSpec.from_mapping(raw)


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
        "causal_family": "demand_structure",
        "arms": list(arms),
        "selected_label": selected["label"],
        "next_experiment_focus": next_focus,
        "validated": validated,
        **dict(extras),
    }


def _screen(
    connection: Connection[Any],
    *,
    config: DemandConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    arms = run_demand_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=99,
        specs=[
            ("baseline_order", DemandScheduleSpec()),
            ("shuffled_order", DemandScheduleSpec(mode="shuffled")),
            ("blocked_order", DemandScheduleSpec(mode="blocked")),
            ("interleaved_order", DemandScheduleSpec(mode="interleaved")),
        ],
    )
    evaluated, selected, control, validated = _evaluate(arms, config=config)
    spec = _spec_from_arm(selected)
    state["selected_schedule"] = spec.as_dict()
    state["screen_validated"] = validated
    effects = _effects(selected, control)
    return _record(
        number=99,
        focus="temporal_order_screen",
        question=(
            "Can reordering the exact same exogenous task packets change logical capture while "
            "preserving quality and public knowledge?"
        ),
        arms=evaluated,
        selected=selected,
        next_focus="exact_task_decomposition",
        validated=validated,
        extras={**effects, "screen_validated": validated, "selected_schedule": spec.as_dict()},
    )


def _decompose(
    connection: Connection[Any],
    *,
    config: DemandConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_schedule")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected demand schedule")
    spec = DemandScheduleSpec.from_mapping(raw)
    arms = run_demand_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=100,
        specs=[("baseline_order", DemandScheduleSpec()), ("candidate_order", spec)],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_order")
    hard, _, effects = _hard_gate(candidate, control, config=config)
    invariants = candidate["invariants"]
    assert isinstance(invariants, Mapping)
    exact_task = (
        bool(invariants.get("exact_task_multiset_per_regime"))
        and bool(invariants.get("source_packet_reordering_only"))
        and bool(invariants.get("demand_schedule_regime_local"))
    )
    validated = bool(state["screen_validated"]) and hard and exact_task
    state["decomposition_validated"] = validated
    return _record(
        number=100,
        focus="exact_task_decomposition",
        question=(
            "With exogenous task packets fixed as a per-regime multiset, does changing only their "
            "temporal order reproduce the plasticity effect?"
        ),
        arms=evaluated,
        selected=candidate,
        next_focus="persistence_response",
        validated=validated,
        extras={
            **effects,
            "screen_validated": bool(state["screen_validated"]),
            "decomposition_validated": validated,
            "exact_task_multiset_validated": exact_task,
            "selected_schedule": spec.as_dict(),
        },
    )


def _response(
    connection: Connection[Any],
    *,
    config: DemandConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    specs: list[tuple[str, DemandScheduleSpec]] = [("baseline_order", DemandScheduleSpec())]
    for mode in config.response_modes:
        specs.append((f"persistence_{mode}", DemandScheduleSpec(mode=mode)))
    arms = run_demand_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=101,
        specs=specs,
    )
    evaluated, selected, control, _ = _evaluate(arms, config=config)
    candidates = [arm for arm in evaluated if arm["label"] != "baseline_order"]
    ordered = sorted(candidates, key=lambda arm: float(_metrics(arm)["demand_adjacent_repeat_rate"]))
    low = ordered[0]
    high = ordered[-1]
    low_hard, _, _ = _hard_gate(low, control, config=config)
    persistence_span = (
        float(_metrics(high)["demand_adjacent_repeat_rate"])
        - float(_metrics(low)["demand_adjacent_repeat_rate"])
    )
    logical_span = (
        float(_metrics(high)["early_incumbent_share"])
        - float(_metrics(low)["early_incumbent_share"])
    )
    near_monotone = all(
        float(_metrics(ordered[index])["early_incumbent_share"])
        <= float(_metrics(ordered[index + 1])["early_incumbent_share"]) + 0.01
        for index in range(len(ordered) - 1)
    )
    validated = (
        bool(state["decomposition_validated"])
        and low_hard
        and persistence_span >= config.minimum_persistence_change
        and logical_span >= config.minimum_logical_improvement
        and near_monotone
    )
    if low_hard:
        selected = low
    spec = _spec_from_arm(selected)
    state["selected_schedule"] = spec.as_dict()
    state["response_validated"] = validated
    effects = _effects(selected, control)
    return _record(
        number=101,
        focus="persistence_response",
        question=(
            "Across low, medium, and high demand persistence over the same task multiset, does "
            "logical incumbency increase with temporal clustering?"
        ),
        arms=evaluated,
        selected=selected,
        next_focus="within_run_reversal",
        validated=validated,
        extras={
            **effects,
            "decomposition_validated": bool(state["decomposition_validated"]),
            "response_validated": validated,
            "persistence_span": persistence_span,
            "logical_span": logical_span,
            "persistence_order_consistent": near_monotone,
            "selected_schedule": spec.as_dict(),
        },
    )


def _reversal(
    connection: Connection[Any],
    *,
    config: DemandConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_schedule")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected demand schedule")
    spec = DemandScheduleSpec.from_mapping(raw)
    reversal = DemandScheduleSpec(
        mode="baseline",
        phase_modes=("blocked", "blocked", "interleaved", "blocked"),
    )
    arms = run_demand_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=102,
        specs=[
            ("baseline_order", DemandScheduleSpec()),
            ("candidate_order", spec),
            ("cluster_interleave_restore", reversal),
        ],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_order")
    reversal_arm = next(arm for arm in evaluated if arm["label"] == "cluster_interleave_restore")
    hard, _, effects = _hard_gate(candidate, control, config=config)
    reversal_metrics = _metrics(reversal_arm)
    unlock_change = float(reversal_metrics["unlock_winner_repeat_change"])
    relock_rebound = float(reversal_metrics["relock_winner_repeat_rebound"])
    reversal_validated = (
        bool(state["response_validated"])
        and hard
        and unlock_change <= -config.minimum_unlock_winner_change
        and relock_rebound >= config.minimum_relock_winner_rebound
    )
    state["reversal_validated"] = reversal_validated
    return _record(
        number=102,
        focus="within_run_reversal",
        question=(
            "After clustered demand establishes reinforcement, does switching to interleaved demand "
            "reduce winner repetition and does restoring clustering recreate it without agent reset?"
        ),
        arms=evaluated,
        selected=candidate,
        next_focus="independent_replication",
        validated=reversal_validated,
        extras={
            **effects,
            "response_validated": bool(state["response_validated"]),
            "reversal_validated": reversal_validated,
            "unlock_winner_repeat_change": unlock_change,
            "relock_winner_repeat_rebound": relock_rebound,
            "selected_schedule": spec.as_dict(),
        },
    )


def _replication(
    connection: Connection[Any],
    *,
    config: DemandConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_schedule")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected demand schedule")
    spec = DemandScheduleSpec.from_mapping(raw)
    arms = run_demand_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=103,
        seeds=config.replication_seeds,
        specs=[("baseline_order", DemandScheduleSpec()), ("candidate_order", spec)],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_order")
    hard, _, effects = _hard_gate(candidate, control, config=config)
    validated = bool(state["reversal_validated"]) and hard
    state["replication_validated"] = validated
    return _record(
        number=103,
        focus="independent_replication",
        question="Does the frozen demand-order intervention reproduce on independent seeds?",
        arms=evaluated,
        selected=candidate,
        next_focus="unseen_holdout",
        validated=validated,
        extras={**effects, "replication_validated": validated, "selected_schedule": spec.as_dict()},
    )


def _holdout_phase_spec(*, env, restore_fraction: float) -> DemandScheduleSpec:
    regime_count = (env.cycles + env.shift_period - 1) // env.shift_period
    restore_cycle = int(round(env.cycles * restore_fraction))
    restore_regime = max(1, min(regime_count - 1, restore_cycle // env.shift_period))
    phases = tuple(
        "interleaved" if regime < restore_regime else "blocked"
        for regime in range(regime_count)
    )
    return DemandScheduleSpec(mode="baseline", phase_modes=phases)


def _holdout(
    connection: Connection[Any],
    *,
    config: DemandConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_schedule")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected demand schedule")
    spec = DemandScheduleSpec.from_mapping(raw)
    env = demand_environment(
        config,
        cycles=config.integration.holdout_cycles,
        shift_period=config.integration.holdout_shift_period,
        candidate_count=config.integration.holdout_candidate_count,
    )
    reversal = _holdout_phase_spec(env=env, restore_fraction=config.holdout_restore_fraction)
    predicted_relock = bool(state["reversal_validated"])
    arms = run_demand_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=104,
        seeds=config.integration.holdout_seeds,
        environment=env,
        specs=[
            ("baseline_order", DemandScheduleSpec()),
            ("candidate_order", spec),
            ("holdout_restore_clustered", reversal),
        ],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_order")
    reversal_arm = next(arm for arm in evaluated if arm["label"] == "holdout_restore_clustered")
    hard, _, effects = _hard_gate(candidate, control, config=config)
    reversal_metrics = _metrics(reversal_arm)
    observed_relock = (
        float(reversal_metrics["relock_winner_repeat_rebound"])
        >= config.minimum_relock_winner_rebound
    )
    prediction_agreement = predicted_relock == observed_relock
    validated = (
        bool(state["screen_validated"])
        and bool(state["decomposition_validated"])
        and bool(state["response_validated"])
        and bool(state["reversal_validated"])
        and bool(state["replication_validated"])
        and hard
        and prediction_agreement
    )
    strong = validated and observed_relock
    state["validated"] = validated
    state["strong_demand_causal"] = strong
    return _record(
        number=104,
        focus="unseen_holdout",
        question=(
            "Does the frozen demand-order intervention generalize to unseen task multisets, and "
            "does the predeclared clustering re-lock prediction hold without agent-state reset?"
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
            "relock_predicted": predicted_relock,
            "relock_observed": observed_relock,
            "relock_prediction_agreement": prediction_agreement,
            "strong_demand_causal": strong,
            "restoration_winner_rebound": float(reversal_metrics["relock_winner_repeat_rebound"]),
            "selected_schedule": spec.as_dict(),
        },
    )


_STEPS = {99: _screen, 100: _decompose, 101: _response, 102: _reversal, 103: _replication, 104: _holdout}


def run_demand_step(
    connection: Connection[Any],
    *,
    config: DemandConfig,
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
            raise ValueError("Experiment 099 must start without a checkpoint")
        state = _initial_checkpoint(config=config, config_hash=config_hash, code_sha=code_sha)
    else:
        if checkpoint is None:
            raise ValueError("later demand experiments require a checkpoint")
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

    from .demand_notebook import write_step_artifacts

    write_step_artifacts(output_dir, record=record, checkpoint=state)
    return {"record": record, "checkpoint": state}


def load_checkpoint(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("checkpoint must be a JSON object")
    return value


__all__ = ["load_checkpoint", "load_demand_config", "run_demand_step"]
