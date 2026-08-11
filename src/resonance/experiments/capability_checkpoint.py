"""Checkpoint state machine for Capability Decay Experiments 081–086."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from psycopg import Connection

from .capability_campaign import CapabilityArmSpec, run_capability_experiment
from .capability_config import (
    CapabilityDecayConfig,
    CapabilityDecaySpec,
    capability_environment,
    load_capability_decay_config,
    scaled_decay,
)

_CHECKPOINT_VERSION = 1
_FIRST_EXPERIMENT = 81
_LAST_EXPERIMENT = 86


def _initial_checkpoint(
    *,
    config: CapabilityDecayConfig,
    config_hash: str,
    code_sha: str,
) -> dict[str, object]:
    return {
        "version": _CHECKPOINT_VERSION,
        "campaign": config.integration.name,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "last_completed": 80,
        "next_experiment": 81,
        "selected_decay": None,
        "screen_validated": False,
        "decomposition_validated": False,
        "response_validated": False,
        "rapid_shift_validated": False,
        "replication_validated": False,
        "clock_reference": None,
        "clock_prediction_inside": None,
        "clock_prediction_agreement": None,
        "validated": None,
    }


def _validate_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    number: int,
    config: CapabilityDecayConfig,
    config_hash: str,
    code_sha: str,
) -> None:
    if int(checkpoint.get("version", -1)) != _CHECKPOINT_VERSION:
        raise ValueError("unsupported capability-decay checkpoint version")
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


def _arm(
    config: CapabilityDecayConfig,
    *,
    label: str,
    decay: CapabilityDecaySpec,
    env=None,
) -> CapabilityArmSpec:
    effective_env = env if env is not None else capability_environment(config)
    return CapabilityArmSpec(
        label=label,
        environment=effective_env,
        decay=decay,
        public_trace_confidence_weight=config.public_trace_confidence_weight,
        retrieval_top_k=config.retrieval_top_k,
        knowledge_signal_threshold=config.knowledge_signal_threshold,
        dormant_inactivity_threshold=config.dormant_inactivity_threshold,
        formation_target_fraction=config.formation_target_fraction,
        formation_window=config.formation_window,
        formation_persistence=config.formation_persistence,
        association_reference_window=config.association_reference_window,
        association_rolling_window=config.association_rolling_window,
        association_target_fraction=config.association_target_fraction,
        association_persistence=config.association_persistence,
        clock_visit_margin=config.clock_visit_margin,
    )


def _run_specs(
    connection: Connection[Any],
    *,
    config: CapabilityDecayConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    specs: Sequence[tuple[str, CapabilityDecaySpec]],
    seeds: Sequence[int] | None = None,
    env_overrides: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    env = capability_environment(config, **dict(env_overrides or {}))
    arms = [_arm(config, label=label, decay=spec, env=env) for label, spec in specs]
    return run_capability_experiment(
        connection,
        config=config.integration,
        config_hash=config_hash,
        experiment_number=number,
        arms=arms,
        seeds=seeds if seeds is not None else config.integration.seeds,
        code_sha=code_sha,
    )


def _utility(metrics: Mapping[str, float]) -> float:
    return (
        metrics["success_rate"]
        + 0.04 * metrics["late_public_knowledge_coverage"]
        + 0.03 * metrics["skill_rank_turnover"]
        - 0.14 * metrics["early_incumbent_share"]
        - 0.06 * metrics["mean_winner_hhi"]
        - 0.02 * metrics["mean_effective_practice_gini"]
        - 0.03 * metrics["credit_gini"]
    )


def _effects(
    arm: Mapping[str, object],
    control: Mapping[str, object],
) -> dict[str, float]:
    metrics = arm["metrics"]
    baseline = control["metrics"]
    assert isinstance(metrics, Mapping) and isinstance(baseline, Mapping)
    return {
        "success_effect": float(metrics["success_rate"]) - float(baseline["success_rate"]),
        "logical_incumbent_reduction": (
            float(baseline["early_incumbent_share"])
            - float(metrics["early_incumbent_share"])
        ),
        "identity_incumbent_reduction": (
            float(baseline["identity_early_incumbent_share"])
            - float(metrics["identity_early_incumbent_share"])
        ),
        "hhi_reduction": (
            float(baseline["mean_winner_hhi"])
            - float(metrics["mean_winner_hhi"])
        ),
        "knowledge_effect": (
            float(metrics["late_public_knowledge_coverage"])
            - float(baseline["late_public_knowledge_coverage"])
        ),
        "dormant_erosion": (
            float(baseline["dormant_effective_ratio"])
            - float(metrics["dormant_effective_ratio"])
        ),
        "skill_rank_turnover_effect": (
            float(metrics["skill_rank_turnover"])
            - float(baseline["skill_rank_turnover"])
        ),
        "refresh_feedback_effect": (
            float(metrics["incumbent_refresh_feedback"])
            - float(baseline["incumbent_refresh_feedback"])
        ),
    }


def _feasible(
    arm: Mapping[str, object],
    control: Mapping[str, object],
    *,
    config: CapabilityDecayConfig,
) -> bool:
    invariants = arm["invariants"]
    metrics = arm["metrics"]
    baseline = control["metrics"]
    assert isinstance(invariants, Mapping)
    assert isinstance(metrics, Mapping) and isinstance(baseline, Mapping)
    return (
        all(bool(value) for value in invariants.values())
        and float(metrics["success_rate"])
        >= float(baseline["success_rate"]) - config.integration.success_tolerance
        and float(metrics["mean_winning_price_fraction"])
        <= float(baseline["mean_winning_price_fraction"])
        + config.integration.economic_tolerance
        and float(metrics["credit_gini"])
        <= float(baseline["credit_gini"]) + config.integration.economic_tolerance
        and float(metrics["late_public_knowledge_coverage"])
        >= float(baseline["late_public_knowledge_coverage"]) - config.knowledge_tolerance
        and float(metrics["exit_count"]) == 0.0
    )


def _hard_gate(
    arm: Mapping[str, object],
    control: Mapping[str, object],
    *,
    config: CapabilityDecayConfig,
) -> tuple[bool, dict[str, float]]:
    effects = _effects(arm, control)
    hard = (
        _feasible(arm, control, config=config)
        and effects["logical_incumbent_reduction"] >= config.minimum_logical_improvement
        and effects["dormant_erosion"] >= config.minimum_dormant_erosion
    )
    return hard, effects


def _evaluate(
    arms: Sequence[dict[str, object]],
    *,
    config: CapabilityDecayConfig,
    control_label: str = "immortal_no_decay",
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object], bool]:
    control = next(arm for arm in arms if arm["label"] == control_label)
    evaluated: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    for arm in arms:
        item = dict(arm)
        metrics = item["metrics"]
        assert isinstance(metrics, Mapping)
        item["utility"] = _utility(metrics)  # type: ignore[arg-type]
        item["feasible"] = _feasible(arm, control, config=config)
        if arm["label"] == control_label:
            item["hard_gate"] = True
            item["effects"] = {
                "success_effect": 0.0,
                "logical_incumbent_reduction": 0.0,
                "identity_incumbent_reduction": 0.0,
                "hhi_reduction": 0.0,
                "knowledge_effect": 0.0,
                "dormant_erosion": 0.0,
                "skill_rank_turnover_effect": 0.0,
                "refresh_feedback_effect": 0.0,
            }
        else:
            hard, effects = _hard_gate(arm, control, config=config)
            item["hard_gate"] = hard
            item["effects"] = effects
            candidates.append(item)
        evaluated.append(item)

    passing = [item for item in candidates if bool(item["hard_gate"])]
    if passing:
        selected = max(passing, key=lambda item: (float(item["utility"]), str(item["label"])))
        return evaluated, selected, control, True

    feasible = [item for item in candidates if bool(item["feasible"])]
    pool = feasible or candidates
    if not pool:
        selected = next(item for item in evaluated if item["label"] == control_label)
        return evaluated, selected, control, False
    selected = max(
        pool,
        key=lambda item: (
            float(item["effects"]["logical_incumbent_reduction"]),  # type: ignore[index]
            float(item["effects"]["dormant_erosion"]),  # type: ignore[index]
            float(item["utility"]),
            str(item["label"]),
        ),
    )
    return evaluated, selected, control, False


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
        "motivating_failure": "persistent_private_capability",
        "observed_failure": None if validated else focus,
        "arms": list(arms),
        "selected_label": selected["label"],
        "next_experiment_focus": next_focus,
        "validated": validated,
        **dict(extras),
    }


def _screen(
    connection: Connection[Any],
    *,
    config: CapabilityDecayConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    specs: list[tuple[str, CapabilityDecaySpec]] = [
        ("immortal_no_decay", CapabilityDecaySpec()),
    ]
    for half_life in config.screen_exponential_half_lives:
        specs.append(
            (
                f"exponential_tau{half_life:g}",
                CapabilityDecaySpec(mode="exponential", half_life_cycles=half_life),
            )
        )
    specs.extend(
        [
            (
                f"step_idle{config.screen_step_inactive_cycles}",
                CapabilityDecaySpec(
                    mode="step",
                    inactive_cycles=config.screen_step_inactive_cycles,
                ),
            ),
            (
                f"floor_tau{config.screen_floor_half_life:g}",
                CapabilityDecaySpec(
                    mode="exponential_floor",
                    half_life_cycles=config.screen_floor_half_life,
                    retention_floor=config.screen_retention_floor,
                ),
            ),
        ]
    )
    arms = _run_specs(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=81,
        specs=specs,
    )
    evaluated, selected, control, validated = _evaluate(arms, config=config)
    raw = selected.get("capability_decay")
    assert isinstance(raw, Mapping)
    state["selected_decay"] = dict(raw)
    state["screen_validated"] = validated
    effects = _effects(selected, control)
    return _record(
        number=81,
        focus="capability_memory_screen",
        question=(
            "Can inactivity-dependent private capability decay materially reduce logical capture "
            "without sacrificing quality or public knowledge?"
        ),
        arms=evaluated,
        selected=selected,
        next_focus="causal_decomposition",
        validated=validated,
        extras={
            **effects,
            "screen_validated": validated,
            "selected_decay": dict(raw),
        },
    )


def _decompose(
    connection: Connection[Any],
    *,
    config: CapabilityDecayConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_decay")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected capability decay")
    spec = CapabilityDecaySpec.from_mapping(raw)
    specs: list[tuple[str, CapabilityDecaySpec]] = [
        ("immortal_no_decay", CapabilityDecaySpec()),
        ("candidate_full", spec),
    ]
    if spec.mode == "exponential_floor":
        assert spec.half_life_cycles is not None
        specs.append(
            (
                "without_retention_floor",
                CapabilityDecaySpec(
                    mode="exponential",
                    half_life_cycles=spec.half_life_cycles,
                ),
            )
        )
    arms = _run_specs(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=82,
        specs=specs,
    )
    evaluated, selected, control, any_hard = _evaluate(arms, config=config)
    validated = bool(state["screen_validated"]) and any_hard
    raw_selected = selected.get("capability_decay")
    assert isinstance(raw_selected, Mapping)
    state["selected_decay"] = dict(raw_selected)
    state["decomposition_validated"] = validated
    effects = _effects(selected, control)
    return _record(
        number=82,
        focus="causal_decomposition",
        question=(
            "Is actual effective-capability forgetting necessary for the screened plasticity effect, "
            "and are any retention components dispensable?"
        ),
        arms=evaluated,
        selected=selected,
        next_focus="decay_timescale_bracket",
        validated=validated,
        extras={
            **effects,
            "screen_validated": bool(state["screen_validated"]),
            "decomposition_validated": validated,
            "selected_decay": dict(raw_selected),
        },
    )


def _response(
    connection: Connection[Any],
    *,
    config: CapabilityDecayConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_decay")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected capability decay")
    reference = CapabilityDecaySpec.from_mapping(raw)
    specs: list[tuple[str, CapabilityDecaySpec]] = [
        ("immortal_no_decay", CapabilityDecaySpec()),
    ]
    seen: set[tuple[object, ...]] = set()
    for scale in config.response_scales:
        spec = scaled_decay(reference, scale)
        key = (
            spec.mode,
            spec.half_life_cycles,
            spec.inactive_cycles,
            spec.retention_floor,
        )
        if key in seen:
            continue
        seen.add(key)
        specs.append((f"timescale_{scale:g}x", spec))
    arms = _run_specs(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=83,
        specs=specs,
    )
    evaluated, selected, control, _ = _evaluate(arms, config=config)
    passing = [
        arm
        for arm in evaluated
        if arm["label"] != "immortal_no_decay" and bool(arm.get("hard_gate"))
    ]
    response_validated = bool(state["decomposition_validated"]) and len(passing) >= 2
    if passing:
        selected = max(passing, key=lambda item: (float(item["utility"]), str(item["label"])))
    raw_selected = selected.get("capability_decay")
    assert isinstance(raw_selected, Mapping)
    state["selected_decay"] = dict(raw_selected)
    state["response_validated"] = response_validated
    metrics = selected["metrics"]
    assert isinstance(metrics, Mapping)
    state["clock_reference"] = {
        "tau_f": float(metrics["tau_f"]),
        "tau_d_assoc": float(metrics["tau_d_assoc"]),
        "tau_visit": float(metrics["tau_visit"]),
        "tau_d_skill": float(metrics["tau_d_skill"]),
        "tau_d_skill_empirical": float(metrics["tau_d_skill_empirical"]),
        "tau_r": float(config.integration.environment.shift_period),
        "clock_window_inside": bool(float(metrics["clock_window_inside"])),
    }
    effects = _effects(selected, control)
    return _record(
        number=83,
        focus="decay_timescale_bracket",
        question=(
            "Is there a bounded capability-decay timescale region that preserves quality while "
            "preventing logical lock-in?"
        ),
        arms=evaluated,
        selected=selected,
        next_focus="rapid_regime_shift",
        validated=response_validated,
        extras={
            **effects,
            "decomposition_validated": bool(state["decomposition_validated"]),
            "response_validated": response_validated,
            "passing_settings": len(passing),
            "selected_decay": dict(raw_selected),
            "clock_reference": dict(state["clock_reference"]),
        },
    )


def _frozen_pair(
    connection: Connection[Any],
    *,
    config: CapabilityDecayConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    spec: CapabilityDecaySpec,
    seeds: Sequence[int],
    env_overrides: Mapping[str, object] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object], bool]:
    arms = _run_specs(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=number,
        seeds=seeds,
        env_overrides=env_overrides,
        specs=[
            ("immortal_no_decay", CapabilityDecaySpec()),
            ("candidate_decay", spec),
        ],
    )
    return _evaluate(arms, config=config)


def _rapid_shift(
    connection: Connection[Any],
    *,
    config: CapabilityDecayConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_decay")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected capability decay")
    spec = CapabilityDecaySpec.from_mapping(raw)
    evaluated, selected, control, _ = _frozen_pair(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=84,
        spec=spec,
        seeds=config.integration.seeds,
        env_overrides={"shift_period": config.rapid_shift_period},
    )
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_decay")
    validated = bool(state["response_validated"]) and bool(candidate["hard_gate"])
    state["rapid_shift_validated"] = validated
    effects = _effects(candidate, control)
    return _record(
        number=84,
        focus="rapid_regime_shift",
        question=(
            "Does the frozen capability-decay timescale preserve quality and logical plasticity "
            "when the environment changes faster?"
        ),
        arms=evaluated,
        selected=candidate if validated else selected,
        next_focus="independent_replication",
        validated=validated,
        extras={
            **effects,
            "rapid_shift_validated": validated,
            "selected_decay": spec.as_dict(),
        },
    )


def _replication(
    connection: Connection[Any],
    *,
    config: CapabilityDecayConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_decay")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected capability decay")
    spec = CapabilityDecaySpec.from_mapping(raw)
    evaluated, selected, control, _ = _frozen_pair(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=85,
        spec=spec,
        seeds=config.replication_seeds,
    )
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_decay")
    validated = bool(state["rapid_shift_validated"]) and bool(candidate["hard_gate"])
    state["replication_validated"] = validated
    effects = _effects(candidate, control)
    return _record(
        number=85,
        focus="independent_replication",
        question=(
            "Does the frozen capability-decay mechanism reproduce on independent seeds without "
            "retuning?"
        ),
        arms=evaluated,
        selected=candidate if validated else selected,
        next_focus="unseen_clock_holdout",
        validated=validated,
        extras={
            **effects,
            "replication_validated": validated,
            "selected_decay": spec.as_dict(),
        },
    )


def _holdout(
    connection: Connection[Any],
    *,
    config: CapabilityDecayConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_decay")
    clocks = state.get("clock_reference")
    if not isinstance(raw, Mapping) or not isinstance(clocks, Mapping):
        raise ValueError("missing selected capability decay or clock reference")
    spec = CapabilityDecaySpec.from_mapping(raw)

    tau_visit = float(clocks["tau_visit"])
    tau_f = float(clocks["tau_f"])
    tau_skill = float(clocks["tau_d_skill_empirical"])
    tau_r = float(config.integration.holdout_shift_period)
    predicted_inside = (
        tau_visit * config.clock_visit_margin < tau_skill < tau_r
        and tau_f < tau_r
    )
    state["clock_prediction_inside"] = predicted_inside

    evaluated, selected, control, _ = _frozen_pair(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=86,
        spec=spec,
        seeds=config.integration.holdout_seeds,
        env_overrides={
            "cycles": config.integration.holdout_cycles,
            "shift_period": config.integration.holdout_shift_period,
            "candidate_count": config.integration.holdout_candidate_count,
        },
    )
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_decay")
    observed_healthy = bool(candidate["hard_gate"])
    agreement = predicted_inside == observed_healthy
    state["clock_prediction_agreement"] = agreement
    validated = (
        bool(state["decomposition_validated"])
        and bool(state["response_validated"])
        and bool(state["rapid_shift_validated"])
        and bool(state["replication_validated"])
        and predicted_inside
        and observed_healthy
        and agreement
    )
    state["validated"] = validated
    effects = _effects(candidate, control)
    return _record(
        number=86,
        focus="unseen_clock_holdout",
        question=(
            "Does the frozen capability-decay mechanism behave as predicted on unseen seeds and "
            "an unseen regime duration without retuning?"
        ),
        arms=evaluated,
        selected=candidate if observed_healthy else selected,
        next_focus=None,
        validated=validated,
        extras={
            **effects,
            "screen_validated": bool(state["screen_validated"]),
            "decomposition_validated": bool(state["decomposition_validated"]),
            "response_validated": bool(state["response_validated"]),
            "rapid_shift_validated": bool(state["rapid_shift_validated"]),
            "replication_validated": bool(state["replication_validated"]),
            "clock_prediction_inside": predicted_inside,
            "clock_prediction_agreement": agreement,
            "holdout_observed_healthy": observed_healthy,
            "prediction_clocks": {
                "tau_visit": tau_visit,
                "tau_f": tau_f,
                "tau_d_skill_empirical": tau_skill,
                "tau_r_holdout": tau_r,
                "visit_margin": config.clock_visit_margin,
            },
            "selected_decay": spec.as_dict(),
        },
    )


_STEPS = {
    81: _screen,
    82: _decompose,
    83: _response,
    84: _rapid_shift,
    85: _replication,
    86: _holdout,
}


def run_capability_decay_step(
    connection: Connection[Any],
    *,
    config: CapabilityDecayConfig,
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
            raise ValueError("Experiment 081 must start without a checkpoint")
        state = _initial_checkpoint(config=config, config_hash=config_hash, code_sha=code_sha)
    else:
        if checkpoint is None:
            raise ValueError("later capability-decay experiments require a checkpoint")
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

    from .capability_notebook import write_step_artifacts

    write_step_artifacts(output_dir, record=record, checkpoint=state)
    return {"record": record, "checkpoint": state}


def load_checkpoint(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("checkpoint must be a JSON object")
    return value


__all__ = [
    "load_capability_decay_config",
    "load_checkpoint",
    "run_capability_decay_step",
]
