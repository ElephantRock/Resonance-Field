"""Checkpoint state machine for Coordination Topology Experiments 087–092."""

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
from .topology_campaign import run_topology_arms
from .topology_config import (
    TopologyConfig,
    TopologySpec,
    load_topology_config,
    topology_environment,
    with_fraction,
)

_CHECKPOINT_VERSION = 1
_FIRST_EXPERIMENT = 87
_LAST_EXPERIMENT = 92


def _initial_checkpoint(
    *,
    config: TopologyConfig,
    config_hash: str,
    code_sha: str,
) -> dict[str, object]:
    return {
        "version": _CHECKPOINT_VERSION,
        "campaign": config.integration.name,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "last_completed": 86,
        "next_experiment": 87,
        "selected_topology": None,
        "screen_validated": False,
        "decomposition_validated": False,
        "temporal_precedence_validated": False,
        "response_validated": False,
        "rapid_shift_validated": False,
        "reversal_validated": False,
        "replication_validated": False,
        "validated": None,
    }


def _validate_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    number: int,
    config: TopologyConfig,
    config_hash: str,
    code_sha: str,
) -> None:
    if int(checkpoint.get("version", -1)) != _CHECKPOINT_VERSION:
        raise ValueError("unsupported topology checkpoint version")
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


def _topology_effects(
    arm: Mapping[str, object],
    control: Mapping[str, object],
) -> dict[str, float]:
    effects = corrected_lifecycle_effects(arm, control)
    metrics = _metrics(arm)
    baseline = _metrics(control)
    effects.update(
        {
            "incumbent_opportunity_reduction": (
                float(baseline["incumbent_opportunity_share"])
                - float(metrics["incumbent_opportunity_share"])
            ),
            "opportunity_gini_reduction": (
                float(baseline["opportunity_agent_gini"])
                - float(metrics["opportunity_agent_gini"])
            ),
            "opportunity_edge_hhi_reduction": (
                float(baseline["opportunity_edge_hhi"])
                - float(metrics["opportunity_edge_hhi"])
            ),
            "opportunity_repeat_reduction": (
                float(baseline["opportunity_repeat_rate"])
                - float(metrics["opportunity_repeat_rate"])
            ),
        }
    )
    return effects


def _utility(arm: Mapping[str, object]) -> float:
    metrics = _metrics(arm)
    base = corrected_lifecycle_utility(metrics)  # type: ignore[arg-type]
    return (
        base
        - 0.05 * float(metrics["incumbent_opportunity_share"])
        - 0.02 * float(metrics["opportunity_agent_gini"])
    )


def _hard_gate(
    arm: Mapping[str, object],
    control: Mapping[str, object],
    *,
    config: TopologyConfig,
) -> tuple[bool, bool, dict[str, float]]:
    effects = _topology_effects(arm, control)
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
        and effects["incumbent_opportunity_reduction"] >= config.minimum_topology_improvement
        and float(metrics.get("exit_count", 0.0)) == 0.0
    )
    return hard, feasible, effects


def _evaluate(
    arms: Sequence[dict[str, object]],
    *,
    config: TopologyConfig,
    control_label: str = "baseline_topology",
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
        "incumbent_opportunity_reduction": 0.0,
        "opportunity_gini_reduction": 0.0,
        "opportunity_edge_hhi_reduction": 0.0,
        "opportunity_repeat_reduction": 0.0,
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
                float(item["utility"]),
                str(item["label"]),
            ),
        )
        return evaluated, selected, control, True

    # Preserve the strongest falsification candidate rather than collapsing to control.
    selected = max(
        candidates,
        key=lambda item: (
            float(item["effects"]["logical_incumbent_reduction"]),  # type: ignore[index]
            float(item["effects"]["incumbent_opportunity_reduction"]),  # type: ignore[index]
            float(item["effects"]["success_effect"]),  # type: ignore[index]
            float(item["utility"]),
            str(item["label"]),
        ),
    )
    return evaluated, selected, control, False


def _spec_from_arm(arm: Mapping[str, object]) -> TopologySpec:
    raw = arm.get("topology")
    if not isinstance(raw, Mapping):
        raise ValueError("arm missing topology specification")
    return TopologySpec.from_mapping(raw)


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
        "causal_family": "coordination_topology",
        "arms": list(arms),
        "selected_label": selected["label"],
        "next_experiment_focus": next_focus,
        "validated": validated,
        **dict(extras),
    }


def _screen(
    connection: Connection[Any],
    *,
    config: TopologyConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    fraction = config.screen_structured_fraction
    cooldown = config.screen_cooldown_cycles
    specs = [
        ("baseline_topology", TopologySpec()),
        ("global_balance", TopologySpec(mode="global_balance", structured_fraction=fraction)),
        ("domain_balance", TopologySpec(mode="domain_balance", structured_fraction=fraction)),
        (
            "domain_reset",
            TopologySpec(
                mode="domain_balance",
                structured_fraction=fraction,
                reset_each_regime=True,
            ),
        ),
        (
            "winner_cooldown",
            TopologySpec(
                mode="winner_cooldown",
                structured_fraction=fraction,
                cooldown_cycles=cooldown,
            ),
        ),
        (
            "hybrid",
            TopologySpec(
                mode="hybrid",
                structured_fraction=fraction,
                cooldown_cycles=cooldown,
            ),
        ),
    ]
    arms = run_topology_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=87,
        specs=specs,
    )
    evaluated, selected, control, validated = _evaluate(arms, config=config)
    spec = _spec_from_arm(selected)
    state["selected_topology"] = spec.as_dict()
    state["screen_validated"] = validated
    effects = _topology_effects(selected, control)
    return _record(
        number=87,
        focus="topology_screen",
        question=(
            "Can changing only the pre-award opportunity graph reduce logical capture while "
            "preserving quality and public knowledge?"
        ),
        arms=evaluated,
        selected=selected,
        next_focus="decomposition_temporal_precedence",
        validated=validated,
        extras={
            **effects,
            "screen_validated": validated,
            "selected_topology": spec.as_dict(),
        },
    )


def _decomposition_specs(spec: TopologySpec) -> list[tuple[str, TopologySpec]]:
    result: list[tuple[str, TopologySpec]] = [("candidate_full", spec)]
    if spec.mode == "hybrid":
        result.extend(
            [
                (
                    "without_winner_cooldown",
                    TopologySpec(
                        mode="domain_balance",
                        structured_fraction=spec.structured_fraction,
                        reset_each_regime=spec.reset_each_regime,
                    ),
                ),
                (
                    "without_domain_balance",
                    TopologySpec(
                        mode="winner_cooldown",
                        structured_fraction=spec.structured_fraction,
                        cooldown_cycles=spec.cooldown_cycles,
                    ),
                ),
            ]
        )
    elif spec.mode == "domain_balance" and spec.reset_each_regime:
        result.append(
            (
                "without_regime_reset",
                TopologySpec(
                    mode="domain_balance",
                    structured_fraction=spec.structured_fraction,
                ),
            )
        )
    elif spec.mode == "winner_cooldown":
        result.append(
            (
                "exposure_balance_comparator",
                TopologySpec(
                    mode="domain_balance",
                    structured_fraction=spec.structured_fraction,
                ),
            )
        )
    elif spec.mode == "domain_balance":
        result.append(
            (
                "global_balance_comparator",
                TopologySpec(
                    mode="global_balance",
                    structured_fraction=spec.structured_fraction,
                ),
            )
        )
    return result


def _decompose(
    connection: Connection[Any],
    *,
    config: TopologyConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_topology")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected topology")
    spec = TopologySpec.from_mapping(raw)
    specs = [("baseline_topology", TopologySpec()), *_decomposition_specs(spec)]
    arms = run_topology_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=88,
        specs=specs,
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_full")
    hard, _, effects = _hard_gate(candidate, control, config=config)
    temporal = (
        effects["incumbent_opportunity_reduction"] >= config.minimum_topology_improvement
        and effects["logical_incumbent_reduction"] >= config.minimum_logical_improvement
    )
    validated = bool(state["screen_validated"]) and hard and temporal
    state["decomposition_validated"] = validated
    state["temporal_precedence_validated"] = temporal
    return _record(
        number=88,
        focus="decomposition_temporal_precedence",
        question=(
            "Does the selected topology act through pre-award opportunity structure, and does "
            "that structural change precede reduced logical incumbency?"
        ),
        arms=evaluated,
        selected=candidate,
        next_focus="bounded_response",
        validated=validated,
        extras={
            **effects,
            "screen_validated": bool(state["screen_validated"]),
            "decomposition_validated": validated,
            "temporal_precedence_validated": temporal,
            "selected_topology": spec.as_dict(),
        },
    )


def _response(
    connection: Connection[Any],
    *,
    config: TopologyConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_topology")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected topology")
    spec = TopologySpec.from_mapping(raw)
    specs: list[tuple[str, TopologySpec]] = [("baseline_topology", TopologySpec())]
    for fraction in config.response_fractions:
        specs.append((f"routing_{fraction:g}", with_fraction(spec, fraction)))
    arms = run_topology_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=89,
        specs=specs,
    )
    evaluated, selected, control, _ = _evaluate(arms, config=config)
    passing = [
        arm
        for arm in evaluated
        if arm["label"] != "baseline_topology" and bool(arm.get("hard_gate"))
    ]
    validated = bool(state["decomposition_validated"]) and len(passing) >= 2
    if passing:
        selected = max(
            passing,
            key=lambda arm: (float(arm["utility"]), str(arm["label"])),
        )
    selected_spec = _spec_from_arm(selected)
    state["selected_topology"] = selected_spec.as_dict()
    state["response_validated"] = validated
    effects = _topology_effects(selected, control)
    return _record(
        number=89,
        focus="bounded_response",
        question=(
            "Does the topology effect survive multiple structured-routing strengths rather than "
            "a single tuned point?"
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
            "selected_topology": selected_spec.as_dict(),
        },
    )


def _rapid_reversal(
    connection: Connection[Any],
    *,
    config: TopologyConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_topology")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected topology")
    spec = TopologySpec.from_mapping(raw)
    env = topology_environment(config, shift_period=config.rapid_shift_period)
    restore_cycle = max(1, int(round(env.cycles * config.reversal_restore_fraction)))
    reversal = replace(spec, restore_after_cycle=restore_cycle)
    arms = run_topology_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=90,
        environment=env,
        specs=[
            ("baseline_topology", TopologySpec()),
            ("candidate_topology", spec),
            ("restore_baseline_midrun", reversal),
        ],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_topology")
    reversal_arm = next(arm for arm in evaluated if arm["label"] == "restore_baseline_midrun")
    hard, _, effects = _hard_gate(candidate, control, config=config)
    rapid_validated = bool(state["response_validated"]) and hard
    reversal_metrics = _metrics(reversal_arm)
    reversal_validated = (
        rapid_validated
        and float(reversal_metrics["restoration_opportunity_rebound"])
        >= config.minimum_relock_opportunity_rebound
        and float(reversal_metrics["restoration_winner_rebound"])
        >= config.minimum_relock_winner_rebound
    )
    state["rapid_shift_validated"] = rapid_validated
    state["reversal_validated"] = reversal_validated
    return _record(
        number=90,
        focus="rapid_shift_reversal",
        question=(
            "Does frozen topology intervention survive faster remapping, and does restoring the "
            "baseline routing rule begin recreating lock-in without restoring agent state?"
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
            "restoration_opportunity_rebound": float(
                reversal_metrics["restoration_opportunity_rebound"]
            ),
            "restoration_winner_rebound": float(
                reversal_metrics["restoration_winner_rebound"]
            ),
            "selected_topology": spec.as_dict(),
        },
    )


def _replication(
    connection: Connection[Any],
    *,
    config: TopologyConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_topology")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected topology")
    spec = TopologySpec.from_mapping(raw)
    arms = run_topology_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=91,
        seeds=config.replication_seeds,
        specs=[
            ("baseline_topology", TopologySpec()),
            ("candidate_topology", spec),
        ],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_topology")
    hard, _, effects = _hard_gate(candidate, control, config=config)
    validated = bool(state["rapid_shift_validated"]) and hard
    state["replication_validated"] = validated
    return _record(
        number=91,
        focus="independent_replication",
        question=(
            "Does the frozen coordination-topology intervention reproduce on independent seeds "
            "without retuning?"
        ),
        arms=evaluated,
        selected=candidate,
        next_focus="unseen_holdout",
        validated=validated,
        extras={
            **effects,
            "replication_validated": validated,
            "selected_topology": spec.as_dict(),
        },
    )


def _holdout(
    connection: Connection[Any],
    *,
    config: TopologyConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_topology")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected topology")
    spec = TopologySpec.from_mapping(raw)
    env = topology_environment(
        config,
        cycles=config.integration.holdout_cycles,
        shift_period=config.integration.holdout_shift_period,
        candidate_count=config.integration.holdout_candidate_count,
    )
    restore_cycle = max(1, int(round(env.cycles * config.holdout_restore_fraction)))
    reversal = replace(spec, restore_after_cycle=restore_cycle)
    predicted_relock = bool(state["reversal_validated"])
    arms = run_topology_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=92,
        seeds=config.integration.holdout_seeds,
        environment=env,
        specs=[
            ("baseline_topology", TopologySpec()),
            ("candidate_topology", spec),
            ("holdout_restore_baseline", reversal),
        ],
    )
    evaluated, _, control, _ = _evaluate(arms, config=config)
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_topology")
    reversal_arm = next(arm for arm in evaluated if arm["label"] == "holdout_restore_baseline")
    hard, _, effects = _hard_gate(candidate, control, config=config)
    reversal_metrics = _metrics(reversal_arm)
    observed_relock = (
        float(reversal_metrics["restoration_opportunity_rebound"])
        >= config.minimum_relock_opportunity_rebound
        and float(reversal_metrics["restoration_winner_rebound"])
        >= config.minimum_relock_winner_rebound
    )
    prediction_agreement = predicted_relock == observed_relock
    validated = (
        bool(state["screen_validated"])
        and bool(state["decomposition_validated"])
        and bool(state["temporal_precedence_validated"])
        and bool(state["response_validated"])
        and bool(state["rapid_shift_validated"])
        and bool(state["replication_validated"])
        and hard
        and prediction_agreement
    )
    strong_coordination_causal = validated and bool(state["reversal_validated"]) and observed_relock
    state["validated"] = validated
    state["strong_coordination_causal"] = strong_coordination_causal
    return _record(
        number=92,
        focus="unseen_holdout",
        question=(
            "Does frozen topology generalize to unseen seeds and remapping, and does the "
            "predeclared restoration/re-lock prediction hold without agent-state restoration?"
        ),
        arms=evaluated,
        selected=candidate,
        next_focus=None,
        validated=validated,
        extras={
            **effects,
            "screen_validated": bool(state["screen_validated"]),
            "decomposition_validated": bool(state["decomposition_validated"]),
            "temporal_precedence_validated": bool(state["temporal_precedence_validated"]),
            "response_validated": bool(state["response_validated"]),
            "rapid_shift_validated": bool(state["rapid_shift_validated"]),
            "reversal_validated": bool(state["reversal_validated"]),
            "replication_validated": bool(state["replication_validated"]),
            "relock_predicted": predicted_relock,
            "relock_observed": observed_relock,
            "relock_prediction_agreement": prediction_agreement,
            "strong_coordination_causal": strong_coordination_causal,
            "restoration_opportunity_rebound": float(
                reversal_metrics["restoration_opportunity_rebound"]
            ),
            "restoration_winner_rebound": float(
                reversal_metrics["restoration_winner_rebound"]
            ),
            "selected_topology": spec.as_dict(),
        },
    )


_STEPS = {
    87: _screen,
    88: _decompose,
    89: _response,
    90: _rapid_reversal,
    91: _replication,
    92: _holdout,
}


def run_topology_step(
    connection: Connection[Any],
    *,
    config: TopologyConfig,
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
            raise ValueError("Experiment 087 must start without a checkpoint")
        state = _initial_checkpoint(config=config, config_hash=config_hash, code_sha=code_sha)
    else:
        if checkpoint is None:
            raise ValueError("later topology experiments require a checkpoint")
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

    from .topology_notebook import write_step_artifacts

    write_step_artifacts(output_dir, record=record, checkpoint=state)
    return {"record": record, "checkpoint": state}


def load_checkpoint(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("checkpoint must be a JSON object")
    return value


__all__ = [
    "load_checkpoint",
    "load_topology_config",
    "run_topology_step",
]
