"""Checkpoint state machine for Lifecycle & Succession Experiments 063–074."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from psycopg import Connection

from .integration_campaign import ReputationPolicy, _record
from .lifecycle_campaign import (
    LifecycleArmSpec,
    LifecycleSpec,
    evaluate_lifecycle_arms,
    lifecycle_effects,
    lifecycle_feasible,
    lifecycle_utility,
    run_lifecycle_experiment,
)
from .lifecycle_config import LifecycleConfig, high_practice_environment, load_lifecycle_config
from .lifecycle_notebook import write_step_artifacts
from .phase_boundary_campaign import reference_policy

_CHECKPOINT_VERSION = 1
_FIRST_EXPERIMENT = 63
_LAST_EXPERIMENT = 74


def _lifecycle_from_mapping(value: Mapping[str, object]) -> LifecycleSpec:
    return LifecycleSpec(**dict(value))  # type: ignore[arg-type]


def _arm(
    config: LifecycleConfig,
    *,
    label: str,
    lifecycle: LifecycleSpec,
    policy: ReputationPolicy | None = None,
    env=None,
) -> LifecycleArmSpec:
    return LifecycleArmSpec(
        label=label,
        policy=policy if policy is not None else reference_policy(),
        environment=env if env is not None else high_practice_environment(config),
        lifecycle=lifecycle,
        public_trace_confidence_weight=config.public_trace_confidence_weight,
        retrieval_top_k=config.retrieval_top_k,
        diversified_lineages=config.diversified_lineages,
        knowledge_signal_threshold=config.knowledge_signal_threshold,
    )


def _initial_checkpoint(
    *,
    config: LifecycleConfig,
    config_hash: str,
    code_sha: str,
) -> dict[str, object]:
    return {
        "version": _CHECKPOINT_VERSION,
        "campaign": config.integration.name,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "last_completed": 62,
        "next_experiment": 63,
        "baseline": None,
        "fixed_exit": None,
        "stochastic_exit": None,
        "selected_lifecycle": None,
        "exit_causal": False,
        "exit_mechanism": None,
        "reputation_independent": False,
        "rapid_shift_validated": False,
        "cultural_diversification_selected": False,
        "candidate_lifecycle": None,
        "synthesis_validated": False,
        "replication_validated": False,
        "validated": None,
    }


def _validate_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    number: int,
    config: LifecycleConfig,
    config_hash: str,
    code_sha: str,
) -> None:
    if int(checkpoint.get("version", -1)) != _CHECKPOINT_VERSION:
        raise ValueError("unsupported lifecycle checkpoint version")
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


def _record_lifecycle(
    *,
    number: int,
    focus: str,
    question: str,
    arms: Sequence[Mapping[str, object]],
    selected: Mapping[str, object],
    observed_failure: str | None,
    next_focus: str | None,
    extras: Mapping[str, object],
    validated: bool | None = None,
) -> dict[str, object]:
    record = _record(
        number=number,
        focus=focus,
        question=question,
        motivating_failure="identity_immortality",
        observed_failure=observed_failure,
        arms=arms,
        selected=selected,
        next_focus=next_focus,
        validated=validated,
    )
    record.update(extras)
    return record


def _run_arms(
    connection: Connection[Any],
    *,
    config: LifecycleConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    arms: Sequence[LifecycleArmSpec],
    seeds: Sequence[int] | None = None,
) -> list[dict[str, object]]:
    return run_lifecycle_experiment(
        connection,
        config=config.integration,
        config_hash=config_hash,
        experiment_number=number,
        arms=arms,
        seeds=seeds if seeds is not None else config.integration.seeds,
        code_sha=code_sha,
    )


def _baseline(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    immortal = LifecycleSpec()
    arms = _run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=63,
        arms=[
            _arm(config, label="immortal_control", lifecycle=immortal),
            _arm(config, label="immortal_no_reputation", lifecycle=immortal, policy=ReputationPolicy()),
        ],
    )
    control = next(arm for arm in arms if arm["label"] == "immortal_control")
    item = dict(control)
    item["feasible"] = True
    metrics = item["metrics"]
    assert isinstance(metrics, Mapping)
    item["utility"] = lifecycle_utility(metrics)  # type: ignore[arg-type]
    state["baseline"] = item
    return _record_lifecycle(
        number=63,
        focus="immortal_baseline",
        question="What does fast-learning organization look like when market-active identities never exit?",
        arms=arms,
        selected=item,
        observed_failure="identity_persistence",
        next_focus="fixed_competitive_exit",
        extras={
            "practice_gain": config.reference_practice_gain,
            "identity_early_incumbent_share": metrics["identity_early_incumbent_share"],
            "cultural_lineage_hhi": metrics["cultural_lineage_hhi"],
            "public_knowledge_coverage": metrics["public_knowledge_coverage"],
        },
    )


def _single_exit_test(
    connection: Connection[Any],
    *,
    config: LifecycleConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    spec: LifecycleSpec,
    label: str,
    state_key: str,
    focus: str,
    question: str,
    next_focus: str,
    state: dict[str, object],
) -> dict[str, object]:
    arms = _run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=number,
        arms=[
            _arm(config, label="immortal_control", lifecycle=LifecycleSpec()),
            _arm(config, label=label, lifecycle=spec),
        ],
    )
    evaluated, selected, control = evaluate_lifecycle_arms(
        arms,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    candidate = next(arm for arm in evaluated if arm["label"] == label)
    effects = lifecycle_effects(candidate, control)
    state[state_key] = {
        "lifecycle": spec.as_dict(),
        "effects": effects,
        "feasible": bool(candidate["feasible"]),
        "utility": float(candidate["utility"]),
    }
    return _record_lifecycle(
        number=number,
        focus=focus,
        question=question,
        arms=evaluated,
        selected=selected,
        observed_failure=None if bool(candidate["feasible"]) else "lifecycle_cost",
        next_focus=next_focus,
        extras=effects,
        validated=bool(candidate["feasible"]),
    )


def _bracket_lifetime(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    specs = [LifecycleSpec(mode="fixed", lifetime_cycles=lifetime) for lifetime in config.lifetime_candidates]
    arms = _run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=66,
        arms=[
            _arm(config, label="immortal_control", lifecycle=LifecycleSpec()),
            *[
                _arm(config, label=f"fixed_lifetime_{spec.lifetime_cycles}", lifecycle=spec)
                for spec in specs
            ],
        ],
    )
    evaluated, selected, control = evaluate_lifecycle_arms(
        arms,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    finite = [arm for arm in evaluated if arm["label"] != "immortal_control" and bool(arm["feasible"])]
    chosen = max(finite, key=lambda arm: float(arm["utility"])) if finite else selected
    effects = lifecycle_effects(chosen, control)
    exit_causal = (
        bool(chosen["feasible"])
        and (
            effects["identity_incumbent_reduction"] >= config.minimum_incumbent_improvement
            or effects["hhi_reduction"] >= config.minimum_hhi_improvement
        )
    )
    lifecycle_raw = chosen.get("lifecycle")
    if not isinstance(lifecycle_raw, Mapping):
        lifecycle_raw = LifecycleSpec().as_dict()
    state["selected_lifecycle"] = dict(lifecycle_raw)
    state["exit_causal"] = exit_causal
    return _record_lifecycle(
        number=66,
        focus="lifetime_response",
        question="Across finite lifetimes, does competitive exit materially reduce identity capture without sacrificing quality or public knowledge?",
        arms=evaluated,
        selected=chosen,
        observed_failure=None if exit_causal else "no_material_turnover_effect",
        next_focus="death_vs_retirement",
        extras={**effects, "selected_lifecycle": dict(lifecycle_raw), "exit_causal": exit_causal},
        validated=exit_causal,
    )


def _death_vs_retirement(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    raw = state.get("selected_lifecycle")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected lifecycle")
    selected = _lifecycle_from_mapping(raw)
    lifetime = selected.lifetime_cycles or config.fixed_lifetime_cycles
    death = LifecycleSpec(mode="death", lifetime_cycles=lifetime)
    retirement = LifecycleSpec(mode="retirement", lifetime_cycles=lifetime)
    arms = _run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=67,
        arms=[
            _arm(config, label="immortal_control", lifecycle=LifecycleSpec()),
            _arm(config, label="death", lifecycle=death),
            _arm(config, label="retirement", lifecycle=retirement),
        ],
    )
    evaluated, selected_arm, control = evaluate_lifecycle_arms(
        arms,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    finite = [arm for arm in evaluated if arm["label"] in {"death", "retirement"} and bool(arm["feasible"])]
    chosen = max(finite, key=lambda arm: float(arm["utility"])) if finite else selected_arm
    lifecycle_raw = chosen.get("lifecycle")
    assert isinstance(lifecycle_raw, Mapping)
    state["exit_mechanism"] = dict(lifecycle_raw)
    death_arm = next(arm for arm in evaluated if arm["label"] == "death")
    retirement_arm = next(arm for arm in evaluated if arm["label"] == "retirement")
    death_metrics = death_arm["metrics"]
    retirement_metrics = retirement_arm["metrics"]
    assert isinstance(death_metrics, Mapping) and isinstance(retirement_metrics, Mapping)
    difference = float(death_metrics["success_rate"]) - float(retirement_metrics["success_rate"])
    effects = lifecycle_effects(chosen, control)
    return _record_lifecycle(
        number=67,
        focus="death_vs_retirement",
        question="Once actors exit competition, does literal identity destruction matter beyond retirement?",
        arms=evaluated,
        selected=chosen,
        observed_failure=None,
        next_focus="retired_advisory_access",
        extras={**effects, "death_minus_retirement_success": difference, "selected_exit_mechanism": dict(lifecycle_raw)},
    )


def _advisor_test(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    raw = state.get("exit_mechanism")
    if not isinstance(raw, Mapping):
        raise ValueError("missing exit mechanism")
    base = _lifecycle_from_mapping(raw)
    lifetime = base.lifetime_cycles or config.fixed_lifetime_cycles
    retirement = LifecycleSpec(mode="retirement", lifetime_cycles=lifetime)
    advisor = LifecycleSpec(mode="advisor", lifetime_cycles=lifetime, advisor_weight=config.advisor_weight)
    arms = _run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=68,
        arms=[
            _arm(config, label="immortal_control", lifecycle=LifecycleSpec()),
            _arm(config, label="retirement", lifecycle=retirement),
            _arm(config, label="retirement_with_advisor", lifecycle=advisor),
        ],
    )
    evaluated, selected, control = evaluate_lifecycle_arms(
        arms,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    finite = [arm for arm in evaluated if arm["label"] != "immortal_control" and bool(arm["feasible"])]
    chosen = max(finite, key=lambda arm: float(arm["utility"])) if finite else selected
    lifecycle_raw = chosen.get("lifecycle")
    assert isinstance(lifecycle_raw, Mapping)
    state["exit_mechanism"] = dict(lifecycle_raw)
    effects = lifecycle_effects(chosen, control)
    return _record_lifecycle(
        number=68,
        focus="retired_advisory_access",
        question="Can retired actors preserve useful tacit knowledge through consultation without regaining competitive privilege?",
        arms=evaluated,
        selected=chosen,
        observed_failure=None,
        next_focus="reputation_independence",
        extras={**effects, "selected_exit_mechanism": dict(lifecycle_raw)},
    )


def _reputation_independence(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    raw = state.get("exit_mechanism")
    if not isinstance(raw, Mapping):
        raise ValueError("missing exit mechanism")
    lifecycle = _lifecycle_from_mapping(raw)
    no_rep = ReputationPolicy()
    arms = _run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=69,
        arms=[
            _arm(config, label="immortal_no_reputation", lifecycle=LifecycleSpec(), policy=no_rep),
            _arm(config, label="lifecycle_no_reputation", lifecycle=lifecycle, policy=no_rep),
        ],
    )
    control = next(arm for arm in arms if arm["label"] == "immortal_no_reputation")
    candidate = next(arm for arm in arms if arm["label"] == "lifecycle_no_reputation")
    control_metrics = control["metrics"]
    candidate_metrics = candidate["metrics"]
    assert isinstance(control_metrics, Mapping) and isinstance(candidate_metrics, Mapping)
    control_item = dict(control)
    candidate_item = dict(candidate)
    control_item["feasible"] = True
    control_item["utility"] = lifecycle_utility(control_metrics)  # type: ignore[arg-type]
    candidate_item["feasible"] = lifecycle_feasible(candidate, control, config=config.integration, knowledge_tolerance=config.knowledge_tolerance)
    candidate_item["utility"] = lifecycle_utility(candidate_metrics)  # type: ignore[arg-type]
    effects = lifecycle_effects(candidate_item, control_item)
    independent = (
        bool(candidate_item["feasible"])
        and (
            effects["identity_incumbent_reduction"] >= config.minimum_incumbent_improvement
            or effects["hhi_reduction"] >= config.minimum_hhi_improvement
        )
    )
    state["reputation_independent"] = independent
    selected = candidate_item if independent else control_item
    return _record_lifecycle(
        number=69,
        focus="reputation_independence",
        question="Does competitive exit still reduce capture when reputation is removed entirely?",
        arms=[control_item, candidate_item],
        selected=selected,
        observed_failure=None if independent else "reputation_dependency",
        next_focus="rapid_regime_shift",
        extras={**effects, "reputation_independent": independent},
        validated=independent,
    )


def _rapid_shift(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    raw = state.get("exit_mechanism")
    if not isinstance(raw, Mapping):
        raise ValueError("missing exit mechanism")
    lifecycle = _lifecycle_from_mapping(raw)
    env = high_practice_environment(config, shift_period=config.rapid_shift_period)
    arms = _run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=70,
        arms=[
            _arm(config, label="immortal_control", lifecycle=LifecycleSpec(), env=env),
            _arm(config, label="lifecycle_candidate", lifecycle=lifecycle, env=env),
        ],
    )
    evaluated, _, control = evaluate_lifecycle_arms(arms, config=config.integration, knowledge_tolerance=config.knowledge_tolerance)
    candidate = next(arm for arm in evaluated if arm["label"] == "lifecycle_candidate")
    effects = lifecycle_effects(candidate, control)
    validated = bool(candidate["feasible"]) and effects["success_effect"] >= -config.integration.success_tolerance
    state["rapid_shift_validated"] = validated
    return _record_lifecycle(
        number=70,
        focus="rapid_regime_shift",
        question="Does the selected lifecycle preserve quality and plasticity when skill mappings change rapidly?",
        arms=evaluated,
        selected=candidate if validated else control,
        observed_failure=None if validated else "rapid_shift",
        next_focus="cultural_persistence",
        extras={**effects, "rapid_shift_validated": validated},
        validated=validated,
    )


def _cultural_persistence(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    raw = state.get("exit_mechanism")
    if not isinstance(raw, Mapping):
        raise ValueError("missing exit mechanism")
    ordinary = _lifecycle_from_mapping(raw)
    diverse = replace(ordinary, diversified_retrieval=True)
    arms = _run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=71,
        arms=[
            _arm(config, label="ordinary_substrate", lifecycle=ordinary),
            _arm(config, label="diversified_retrieval", lifecycle=diverse),
        ],
    )
    ordinary_arm = next(arm for arm in arms if arm["label"] == "ordinary_substrate")
    diverse_arm = next(arm for arm in arms if arm["label"] == "diversified_retrieval")
    ordinary_metrics = ordinary_arm["metrics"]
    diverse_metrics = diverse_arm["metrics"]
    assert isinstance(ordinary_metrics, Mapping) and isinstance(diverse_metrics, Mapping)
    ordinary_item = dict(ordinary_arm)
    diverse_item = dict(diverse_arm)
    ordinary_item["feasible"] = True
    ordinary_item["utility"] = lifecycle_utility(ordinary_metrics)  # type: ignore[arg-type]
    diverse_item["feasible"] = lifecycle_feasible(diverse_arm, ordinary_arm, config=config.integration, knowledge_tolerance=config.knowledge_tolerance)
    diverse_item["utility"] = lifecycle_utility(diverse_metrics)  # type: ignore[arg-type]
    selected = diverse_item if bool(diverse_item["feasible"]) and float(diverse_item["utility"]) > float(ordinary_item["utility"]) else ordinary_item
    use_diverse = selected["label"] == "diversified_retrieval"
    state["cultural_diversification_selected"] = use_diverse
    lifecycle_raw = selected["lifecycle"]
    assert isinstance(lifecycle_raw, Mapping)
    state["candidate_lifecycle"] = dict(lifecycle_raw)
    return _record_lifecycle(
        number=71,
        focus="cultural_persistence",
        question="After competitive exit, does lineage-diversified retrieval improve adaptation or merely damage useful institutional memory?",
        arms=[ordinary_item, diverse_item],
        selected=selected,
        observed_failure=None,
        next_focus="fast_learning_synthesis",
        extras={
            "cultural_hhi_effect": float(diverse_metrics["cultural_lineage_hhi"]) - float(ordinary_metrics["cultural_lineage_hhi"]),
            "knowledge_effect": float(diverse_metrics["public_knowledge_coverage"]) - float(ordinary_metrics["public_knowledge_coverage"]),
            "success_effect": float(diverse_metrics["success_rate"]) - float(ordinary_metrics["success_rate"]),
            "diversification_selected": use_diverse,
        },
    )


def _synthesis(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    raw = state.get("candidate_lifecycle") or state.get("exit_mechanism")
    if not isinstance(raw, Mapping):
        raise ValueError("missing candidate lifecycle")
    lifecycle = _lifecycle_from_mapping(raw)
    env = high_practice_environment(config, cycles=config.synthesis_cycles)
    arms = _run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=72,
        arms=[
            _arm(config, label="immortal_control", lifecycle=LifecycleSpec(), env=env),
            _arm(config, label="candidate_lifecycle", lifecycle=lifecycle, env=env),
        ],
    )
    evaluated, _, control = evaluate_lifecycle_arms(arms, config=config.integration, knowledge_tolerance=config.knowledge_tolerance)
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_lifecycle")
    effects = lifecycle_effects(candidate, control)
    validated = (
        bool(state["exit_causal"])
        and bool(candidate["feasible"])
        and effects["success_effect"] >= -config.integration.success_tolerance
        and (
            effects["identity_incumbent_reduction"] >= config.minimum_incumbent_improvement
            or effects["hhi_reduction"] >= config.minimum_hhi_improvement
        )
    )
    state["candidate_lifecycle"] = lifecycle.as_dict()
    state["synthesis_validated"] = validated
    return _record_lifecycle(
        number=72,
        focus="fast_learning_synthesis",
        question="Can fast learning retain its quality advantage once competitive privilege has a finite lifetime?",
        arms=evaluated,
        selected=candidate if validated else control,
        observed_failure=None if validated else "quality_or_plasticity",
        next_focus="independent_replication",
        extras={**effects, "synthesis_validated": validated},
        validated=validated,
    )


def _replication(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    raw = state.get("candidate_lifecycle")
    if not isinstance(raw, Mapping):
        raise ValueError("missing candidate lifecycle")
    lifecycle = _lifecycle_from_mapping(raw)
    env = high_practice_environment(config, cycles=config.synthesis_cycles)
    arms = _run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=73,
        seeds=config.replication_seeds,
        arms=[
            _arm(config, label="immortal_control", lifecycle=LifecycleSpec(), env=env),
            _arm(config, label="candidate_lifecycle", lifecycle=lifecycle, env=env),
        ],
    )
    evaluated, _, control = evaluate_lifecycle_arms(arms, config=config.integration, knowledge_tolerance=config.knowledge_tolerance)
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_lifecycle")
    effects = lifecycle_effects(candidate, control)
    invariants = candidate["invariants"]
    assert isinstance(invariants, Mapping)
    validated = (
        bool(state["synthesis_validated"])
        and bool(candidate["feasible"])
        and effects["success_effect"] >= -config.integration.success_tolerance
        and all(bool(value) for value in invariants.values())
    )
    state["replication_validated"] = validated
    return _record_lifecycle(
        number=73,
        focus="independent_replication",
        question="Does the selected lifecycle reproduce its quality/plasticity effect on independent seeds?",
        arms=evaluated,
        selected=candidate if validated else control,
        observed_failure=None if validated else "replication",
        next_focus="unseen_holdout",
        extras={**effects, "replication_validated": validated},
        validated=validated,
    )


def _holdout(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    raw = state.get("candidate_lifecycle")
    if not isinstance(raw, Mapping):
        raise ValueError("missing candidate lifecycle")
    candidate = _lifecycle_from_mapping(raw)
    if candidate.finite:
        candidate = replace(candidate, lifetime_cycles=config.holdout_lifetime_cycles, schedule_offset=7)
    base = config.integration.environment
    env = replace(
        base,
        practice_gain=config.reference_practice_gain,
        cycles=config.integration.holdout_cycles,
        shift_period=config.holdout_shift_period,
        candidate_count=config.integration.holdout_candidate_count,
    )
    arms = _run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=74,
        seeds=config.integration.holdout_seeds,
        arms=[
            _arm(config, label="immortal_control", lifecycle=LifecycleSpec(), env=env),
            _arm(config, label="candidate_lifecycle", lifecycle=candidate, env=env),
        ],
    )
    evaluated, _, control = evaluate_lifecycle_arms(arms, config=config.integration, knowledge_tolerance=config.knowledge_tolerance)
    lifecycle_arm = next(arm for arm in evaluated if arm["label"] == "candidate_lifecycle")
    effects = lifecycle_effects(lifecycle_arm, control)
    invariants = lifecycle_arm["invariants"]
    assert isinstance(invariants, Mapping)
    validated = (
        bool(state["exit_causal"])
        and bool(state["synthesis_validated"])
        and bool(state["replication_validated"])
        and bool(lifecycle_arm["feasible"])
        and effects["success_effect"] >= -config.integration.success_tolerance
        and (
            effects["identity_incumbent_reduction"] >= config.minimum_incumbent_improvement
            or effects["hhi_reduction"] >= config.minimum_hhi_improvement
        )
        and all(bool(value) for value in invariants.values())
    )
    state["validated"] = validated
    return _record_lifecycle(
        number=74,
        focus="unseen_holdout",
        question="Does succession generalize to unseen seeds, a new task-remap schedule, and an unseen lifecycle timing?",
        arms=evaluated,
        selected=lifecycle_arm,
        observed_failure=None if validated else "holdout",
        next_focus=None,
        extras={
            **effects,
            "holdout_lifecycle": candidate.as_dict(),
            "exit_causal": bool(state["exit_causal"]),
            "reputation_independent": bool(state["reputation_independent"]),
            "rapid_shift_validated": bool(state["rapid_shift_validated"]),
            "synthesis_validated": bool(state["synthesis_validated"]),
            "replication_validated": bool(state["replication_validated"]),
        },
        validated=validated,
    )


def run_lifecycle_step(
    connection: Connection[Any],
    *,
    config: LifecycleConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    checkpoint: Mapping[str, object] | None,
    output_dir: str | Path,
) -> dict[str, object]:
    if not _FIRST_EXPERIMENT <= number <= _LAST_EXPERIMENT:
        raise ValueError("experiment number must be between 63 and 74")
    if checkpoint is None:
        if number != _FIRST_EXPERIMENT:
            raise ValueError("only Experiment 063 may start without a checkpoint")
        state = _initial_checkpoint(config=config, config_hash=config_hash, code_sha=code_sha)
    else:
        _validate_checkpoint(checkpoint, number=number, config=config, config_hash=config_hash, code_sha=code_sha)
        state = dict(checkpoint)

    if number == 63:
        record = _baseline(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
    elif number == 64:
        record = _single_exit_test(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            number=64,
            spec=LifecycleSpec(mode="fixed", lifetime_cycles=config.fixed_lifetime_cycles),
            label="fixed_exit",
            state_key="fixed_exit",
            focus="fixed_competitive_exit",
            question="Does fixed-age competitive exit plus fresh replacement reduce identity capture?",
            next_focus="stochastic_retirement",
            state=state,
        )
    elif number == 65:
        record = _single_exit_test(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            number=65,
            spec=LifecycleSpec(mode="stochastic", lifetime_cycles=config.fixed_lifetime_cycles, stochastic_min_age=config.stochastic_min_age),
            label="stochastic_exit",
            state_key="stochastic_exit",
            focus="stochastic_retirement",
            question="Does a matched expected lifetime work without synchronized generational replacement?",
            next_focus="lifetime_response",
            state=state,
        )
    elif number == 66:
        record = _bracket_lifetime(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
    elif number == 67:
        record = _death_vs_retirement(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
    elif number == 68:
        record = _advisor_test(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
    elif number == 69:
        record = _reputation_independence(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
    elif number == 70:
        record = _rapid_shift(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
    elif number == 71:
        record = _cultural_persistence(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
    elif number == 72:
        record = _synthesis(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
    elif number == 73:
        record = _replication(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
    else:
        record = _holdout(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)

    state["last_completed"] = number
    state["next_experiment"] = number + 1 if number < _LAST_EXPERIMENT else None
    state["last_record"] = record
    write_step_artifacts(output_dir, record=record, checkpoint=state)
    return {"record": record, "checkpoint": state}


def load_checkpoint(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("checkpoint must contain an object")
    return value


__all__ = ["LifecycleConfig", "load_checkpoint", "load_lifecycle_config", "run_lifecycle_step"]
