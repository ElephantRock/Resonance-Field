"""Checkpoint state machine for Lifecycle Experiments 063 through 074."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from psycopg import Connection

from .integration_campaign import ReputationPolicy
from .lifecycle_campaign import (
    LifecyclePolicy,
    SuccessionArm,
    choose_lifecycle,
    finite_arm,
    immortal_arm,
    lifecycle_interaction,
    no_reputation_policy,
    reference_reputation_policy,
    run_succession_experiment,
)
from .lifecycle_config import LifecycleConfig, load_lifecycle_config, with_shift
from .lifecycle_notebook import write_step_artifacts

_CHECKPOINT_VERSION = 1
_FIRST_EXPERIMENT = 63
_LAST_EXPERIMENT = 74


def _policy_from_mapping(value: Mapping[str, object]) -> ReputationPolicy:
    return ReputationPolicy(**dict(value))  # type: ignore[arg-type]


def _lifecycle_from_mapping(value: Mapping[str, object]) -> LifecyclePolicy:
    return LifecyclePolicy(**dict(value))  # type: ignore[arg-type]


def _decorate(arms: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for arm in arms:
        item = dict(arm)
        invariants = item["invariants"]
        assert isinstance(invariants, Mapping)
        item["feasible"] = all(bool(value) for value in invariants.values())
        result.append(item)
    return result


def _record(
    *,
    number: int,
    focus: str,
    question: str,
    arms: Sequence[dict[str, object]],
    selected: Mapping[str, object],
    next_focus: str | None,
    extras: Mapping[str, object] | None = None,
    validated: bool | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "number": number,
        "focus": focus,
        "question": question,
        "selected_label": selected["label"],
        "arms": list(arms),
        "next_experiment_focus": next_focus,
    }
    if extras:
        record.update(extras)
    if validated is not None:
        record["validated"] = validated
    return record


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
        "exit_validated": False,
        "best_lifecycle": None,
        "best_lifecycle_utility": None,
        "candidate_lifecycle": None,
        "candidate_policy": reference_reputation_policy().as_dict(),
        "death_retirement_equivalent": None,
        "advisory_result": None,
        "reputation_interaction": None,
        "cultural_diversification_selected": False,
        "stress_validated": False,
        "mechanism_validated": False,
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


def _run(
    connection: Connection[Any],
    *,
    config: LifecycleConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    arms: Sequence[SuccessionArm],
    seeds: Sequence[int] | None = None,
) -> list[dict[str, object]]:
    return _decorate(
        run_succession_experiment(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            number=number,
            arms=arms,
            seeds=seeds or config.integration.seeds,
        )
    )


def _baseline(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str) -> dict[str, object]:
    env = config.integration.environment
    arms = _run(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=63,
        arms=[
            immortal_arm("immortal_no_reputation", policy=no_reputation_policy(), env=env),
            immortal_arm("immortal_reference", policy=reference_reputation_policy(), env=env),
        ],
    )
    selected = next(arm for arm in arms if arm["label"] == "immortal_reference")
    return _record(
        number=63,
        focus="immortal_high_learning_baseline",
        question=(
            "Under fast practice formation, what quality and lock-in pattern appears when "
            "market-active identities never exit?"
        ),
        arms=arms,
        selected=selected,
        next_focus="fixed_competitive_exit",
    )


def _fixed_exit(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    env = config.integration.environment
    reference = immortal_arm("immortal_reference", policy=reference_reputation_policy(), env=env)
    fixed = finite_arm(
        "fixed_exit_reference",
        policy=reference_reputation_policy(),
        env=env,
        lifetime=config.expected_lifetime,
        disposition="retire",
    )
    arms = _run(connection, config=config, config_hash=config_hash, code_sha=code_sha, number=64, arms=[reference, fixed])
    fixed_summary = next(arm for arm in arms if arm["label"] == "fixed_exit_reference")
    _, immortal, diagnostics = choose_lifecycle(arms, reference_label="immortal_reference", config=config)
    diag = diagnostics["fixed_exit_reference"]
    valid = (
        float(diag["actor_incumbency_reduction"]) >= config.minimum_actor_incumbency_reduction
        and float(diag["success_delta"]) >= -config.integration.success_tolerance
        and float(diag["knowledge_retention_ratio"]) >= config.minimum_knowledge_retention
        and all(bool(v) for v in fixed_summary["invariants"].values())  # type: ignore[union-attr]
    )
    state["exit_validated"] = valid
    state["best_lifecycle"] = fixed.lifecycle.as_dict()
    state["best_lifecycle_utility"] = fixed_summary["utility"]
    selected = fixed_summary if valid else immortal
    return _record(
        number=64,
        focus="fixed_competitive_exit",
        question=(
            "Does fixed-age competitive exit with immediate fresh replacement preserve quality "
            "and public knowledge while materially reducing actor incumbency?"
        ),
        arms=arms,
        selected=selected,
        next_focus="stochastic_retirement",
        extras={
            "lifecycle_validated": valid,
            **diag,
            "selected_lifetime": config.expected_lifetime,
            "selected_mode": "fixed",
            "selected_disposition": "retire",
        },
        validated=valid,
    )


def _stochastic_exit(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    env = config.integration.environment
    armspec = [
        immortal_arm("immortal_reference", policy=reference_reputation_policy(), env=env),
        finite_arm(
            "stochastic_retirement",
            policy=reference_reputation_policy(),
            env=env,
            lifetime=config.expected_lifetime,
            mode="stochastic",
            disposition="retire",
        ),
    ]
    arms = _run(connection, config=config, config_hash=config_hash, code_sha=code_sha, number=65, arms=armspec)
    stochastic = next(arm for arm in arms if arm["label"] == "stochastic_retirement")
    _, immortal, diagnostics = choose_lifecycle(arms, reference_label="immortal_reference", config=config)
    diag = diagnostics["stochastic_retirement"]
    valid = (
        float(diag["actor_incumbency_reduction"]) >= config.minimum_actor_incumbency_reduction
        and float(diag["success_delta"]) >= -config.integration.success_tolerance
        and float(diag["knowledge_retention_ratio"]) >= config.minimum_knowledge_retention
    )
    previous_utility = float(state.get("best_lifecycle_utility") or float("-inf"))
    if valid and float(stochastic["utility"]) > previous_utility:
        state["best_lifecycle"] = armspec[1].lifecycle.as_dict()
        state["best_lifecycle_utility"] = stochastic["utility"]
    state["exit_validated"] = bool(state["exit_validated"]) or valid
    selected = stochastic if valid else immortal
    return _record(
        number=65,
        focus="stochastic_retirement",
        question=(
            "Does stochastic retirement with the same expected lifetime reproduce the causal "
            "benefit of deterministic competitive exit?"
        ),
        arms=arms,
        selected=selected,
        next_focus="lifetime_response",
        extras={
            "lifecycle_validated": valid,
            **diag,
            "selected_lifetime": config.expected_lifetime,
            "selected_mode": "stochastic",
            "selected_disposition": "retire",
        },
        validated=valid,
    )


def _lifetime_response(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    env = config.integration.environment
    candidates = [
        finite_arm(
            f"fixed_exit_L{lifetime}",
            policy=reference_reputation_policy(),
            env=env,
            lifetime=lifetime,
            disposition="retire",
        )
        for lifetime in (config.short_lifetime, config.expected_lifetime, config.long_lifetime)
    ]
    arms = _run(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=66,
        arms=[immortal_arm("immortal_reference", policy=reference_reputation_policy(), env=env), *candidates],
    )
    selected, _, diagnostics = choose_lifecycle(arms, reference_label="immortal_reference", config=config)
    finite_summaries = [arm for arm in arms if arm["label"] != "immortal_reference"]
    if selected["label"] == "immortal_reference":
        selected = max(finite_summaries, key=lambda arm: float(arm["utility"]))
    chosen_spec = next(spec for spec in candidates if spec.label == selected["label"])
    diag = diagnostics[str(selected["label"])]
    valid = (
        float(diag["actor_incumbency_reduction"]) >= config.minimum_actor_incumbency_reduction
        and float(diag["success_delta"]) >= -config.integration.success_tolerance
        and float(diag["knowledge_retention_ratio"]) >= config.minimum_knowledge_retention
    )
    state["exit_validated"] = bool(state["exit_validated"]) or valid
    state["best_lifecycle"] = chosen_spec.lifecycle.as_dict()
    state["best_lifecycle_utility"] = selected["utility"]
    return _record(
        number=66,
        focus="lifetime_response",
        question=(
            "How does the quality/plasticity tradeoff change as exogenous competitive lifetime "
            "is shortened or lengthened?"
        ),
        arms=arms,
        selected=selected,
        next_focus="death_vs_retirement",
        extras={
            "lifecycle_validated": valid,
            **diag,
            "selected_lifetime": chosen_spec.lifecycle.lifetime_cycles,
            "selected_mode": chosen_spec.lifecycle.mode,
            "selected_disposition": chosen_spec.lifecycle.disposition,
        },
        validated=valid,
    )


def _death_vs_retirement(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    env = config.integration.environment
    raw = state["best_lifecycle"]
    if not isinstance(raw, Mapping):
        raise ValueError("best lifecycle is missing")
    best = _lifecycle_from_mapping(raw)
    assert best.lifetime_cycles is not None
    retire = finite_arm(
        "silent_retirement",
        policy=reference_reputation_policy(),
        env=env,
        lifetime=best.lifetime_cycles,
        mode=best.mode,
        disposition="retire",
        phase_offset=best.phase_offset,
    )
    death = finite_arm(
        "hard_death",
        policy=reference_reputation_policy(),
        env=env,
        lifetime=best.lifetime_cycles,
        mode=best.mode,
        disposition="death",
        phase_offset=best.phase_offset,
    )
    arms = _run(connection, config=config, config_hash=config_hash, code_sha=code_sha, number=67, arms=[retire, death])
    r = next(arm for arm in arms if arm["label"] == "silent_retirement")
    d = next(arm for arm in arms if arm["label"] == "hard_death")
    rm = r["metrics"]
    dm = d["metrics"]
    assert isinstance(rm, Mapping) and isinstance(dm, Mapping)
    distance = (
        abs(float(rm["success_rate"]) - float(dm["success_rate"]))
        + abs(float(rm["early_actor_incumbent_share"]) - float(dm["early_actor_incumbent_share"]))
        + abs(float(rm["mean_public_knowledge_signal"]) - float(dm["mean_public_knowledge_signal"]))
    )
    equivalent = distance <= 0.03
    selected = r if equivalent or float(r["utility"]) >= float(d["utility"]) else d
    chosen = retire.lifecycle if selected["label"] == "silent_retirement" else death.lifecycle
    state["death_retirement_equivalent"] = equivalent
    state["best_lifecycle"] = chosen.as_dict()
    state["best_lifecycle_utility"] = selected["utility"]
    return _record(
        number=67,
        focus="death_vs_retirement",
        question=(
            "Once competitive eligibility ends, does destroying the old executable identity "
            "change outcomes relative to silent retirement with the same public traces?"
        ),
        arms=arms,
        selected=selected,
        next_focus="advisory_retirement",
        extras={
            "death_retirement_distance": distance,
            "death_retirement_equivalent": equivalent,
            "selected_lifetime": chosen.lifetime_cycles,
            "selected_mode": chosen.mode,
            "selected_disposition": chosen.disposition,
        },
        validated=equivalent,
    )


def _advisory_retirement(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    env = config.integration.environment
    raw = state["best_lifecycle"]
    if not isinstance(raw, Mapping):
        raise ValueError("best lifecycle is missing")
    best = _lifecycle_from_mapping(raw)
    assert best.lifetime_cycles is not None
    silent = finite_arm(
        "silent_retirement",
        policy=reference_reputation_policy(),
        env=env,
        lifetime=best.lifetime_cycles,
        mode=best.mode,
        disposition="retire",
        phase_offset=best.phase_offset,
    )
    advisor = finite_arm(
        "advisor_retirement",
        policy=reference_reputation_policy(),
        env=env,
        lifetime=best.lifetime_cycles,
        mode=best.mode,
        disposition="advisor",
        advisory=True,
        phase_offset=best.phase_offset,
    )
    arms = _run(connection, config=config, config_hash=config_hash, code_sha=code_sha, number=68, arms=[silent, advisor])
    s = next(arm for arm in arms if arm["label"] == "silent_retirement")
    a = next(arm for arm in arms if arm["label"] == "advisor_retirement")
    sm = s["metrics"]
    am = a["metrics"]
    assert isinstance(sm, Mapping) and isinstance(am, Mapping)
    effect = float(am["success_rate"]) - float(sm["success_rate"])
    safe = (
        float(am["early_actor_incumbent_share"]) <= float(sm["early_actor_incumbent_share"]) + config.integration.incumbent_tolerance
        and float(am["early_incumbent_share"]) <= float(sm["early_incumbent_share"]) + config.integration.incumbent_tolerance
    )
    selected = a if safe and float(a["utility"]) > float(s["utility"]) else s
    chosen = advisor.lifecycle if selected["label"] == "advisor_retirement" else silent.lifecycle
    state["advisory_result"] = {"selected": selected["label"], "success_effect": effect, "safe": safe}
    state["best_lifecycle"] = chosen.as_dict()
    state["best_lifecycle_utility"] = selected["utility"]
    return _record(
        number=68,
        focus="advisory_retirement",
        question=(
            "Can a retired expert remain explicitly consultable without re-creating competitive "
            "incumbency or lineage lock-in?"
        ),
        arms=arms,
        selected=selected,
        next_focus="reputation_interaction",
        extras={
            "advisor_effect": effect,
            "selected_lifetime": chosen.lifetime_cycles,
            "selected_mode": chosen.mode,
            "selected_disposition": chosen.disposition,
        },
    )


def _candidate_arm(label: str, *, env, policy: ReputationPolicy, lifecycle: LifecyclePolicy, public_retrieval: str | None = None) -> SuccessionArm:
    if lifecycle.mode == "immortal":
        return immortal_arm(label, policy=policy, env=env)
    assert lifecycle.lifetime_cycles is not None
    return finite_arm(
        label,
        policy=policy,
        env=env,
        lifetime=lifecycle.lifetime_cycles,
        mode=lifecycle.mode,
        disposition=lifecycle.disposition,
        advisory=lifecycle.advisory,
        public_retrieval=public_retrieval or lifecycle.public_retrieval,
        phase_offset=lifecycle.phase_offset,
    )


def _reputation_interaction_step(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    env = config.integration.environment
    raw = state["best_lifecycle"]
    if not isinstance(raw, Mapping):
        raise ValueError("best lifecycle is missing")
    lifecycle = _lifecycle_from_mapping(raw)
    ref = reference_reputation_policy()
    none = no_reputation_policy()
    armspec = [
        immortal_arm("immortal_reference", policy=ref, env=env),
        _candidate_arm("lifecycle_reference", env=env, policy=ref, lifecycle=lifecycle),
        immortal_arm("immortal_no_reputation", policy=none, env=env),
        _candidate_arm("lifecycle_no_reputation", env=env, policy=none, lifecycle=lifecycle),
    ]
    arms = _run(connection, config=config, config_hash=config_hash, code_sha=code_sha, number=69, arms=armspec)
    lookup = {str(arm["label"]): arm for arm in arms}
    interaction = lifecycle_interaction(
        immortal_reputation=lookup["immortal_reference"],
        lifecycle_reputation=lookup["lifecycle_reference"],
        immortal_none=lookup["immortal_no_reputation"],
        lifecycle_none=lookup["lifecycle_no_reputation"],
    )
    ref_selected, _, ref_diag = choose_lifecycle(
        [lookup["immortal_reference"], lookup["lifecycle_reference"]],
        reference_label="immortal_reference",
        config=config,
    )
    none_selected, _, none_diag = choose_lifecycle(
        [lookup["immortal_no_reputation"], lookup["lifecycle_no_reputation"]],
        reference_label="immortal_no_reputation",
        config=config,
    )
    valid_ref = ref_selected["label"] == "lifecycle_reference"
    valid_none = none_selected["label"] == "lifecycle_no_reputation"
    options: list[tuple[dict[str, object], ReputationPolicy]] = []
    if valid_ref:
        options.append((lookup["lifecycle_reference"], ref))
    if valid_none:
        options.append((lookup["lifecycle_no_reputation"], none))
    if options:
        selected, policy = max(options, key=lambda pair: float(pair[0]["utility"]))
    else:
        selected, policy = max(
            [(lookup["lifecycle_reference"], ref), (lookup["lifecycle_no_reputation"], none)],
            key=lambda pair: float(pair[0]["utility"]),
        )
    state["candidate_policy"] = policy.as_dict()
    state["candidate_lifecycle"] = lifecycle.as_dict()
    state["reputation_interaction"] = interaction
    state["exit_validated"] = bool(state["exit_validated"]) and (valid_ref or valid_none)
    selected_diag = ref_diag["lifecycle_reference"] if selected["label"] == "lifecycle_reference" else none_diag["lifecycle_no_reputation"]
    return _record(
        number=69,
        focus="reputation_interaction",
        question=(
            "Does competitive exit improve the ecology independently of reputation, or is the "
            "lifecycle effect specifically an interaction with reputation accumulation?"
        ),
        arms=arms,
        selected=selected,
        next_focus="rapid_regime_shift",
        extras={"lifecycle_reputation_interaction": interaction, **selected_diag},
        validated=valid_ref or valid_none,
    )


def _rapid_shift(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    raw_lifecycle = state["candidate_lifecycle"]
    raw_policy = state["candidate_policy"]
    if not isinstance(raw_lifecycle, Mapping) or not isinstance(raw_policy, Mapping):
        raise ValueError("candidate is missing")
    lifecycle = _lifecycle_from_mapping(raw_lifecycle)
    policy = _policy_from_mapping(raw_policy)
    env = with_shift(config.integration.environment, config.rapid_shift_period)
    arms = _run(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=70,
        arms=[
            immortal_arm("immortal_candidate_policy", policy=policy, env=env),
            _candidate_arm("lifecycle_candidate", env=env, policy=policy, lifecycle=lifecycle),
        ],
    )
    selected, immortal, diagnostics = choose_lifecycle(arms, reference_label="immortal_candidate_policy", config=config)
    candidate = next(arm for arm in arms if arm["label"] == "lifecycle_candidate")
    diag = diagnostics["lifecycle_candidate"]
    valid = selected["label"] == "lifecycle_candidate"
    state["stress_validated"] = valid
    return _record(
        number=70,
        focus="rapid_regime_shift",
        question=(
            "Does the selected lifecycle preserve its quality/plasticity advantage when the "
            "task-to-skill regime changes faster?"
        ),
        arms=arms,
        selected=candidate if valid else immortal,
        next_focus="cultural_persistence",
        extras={"lifecycle_validated": valid, **diag},
        validated=valid,
    )


def _cultural_persistence(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    raw_lifecycle = state["candidate_lifecycle"]
    raw_policy = state["candidate_policy"]
    if not isinstance(raw_lifecycle, Mapping) or not isinstance(raw_policy, Mapping):
        raise ValueError("candidate is missing")
    lifecycle = _lifecycle_from_mapping(raw_lifecycle)
    policy = _policy_from_mapping(raw_policy)
    env = config.integration.environment
    standard = _candidate_arm(
        "standard_public_retrieval",
        env=env,
        policy=policy,
        lifecycle=replace(lifecycle, public_retrieval="standard"),
    )
    diversified = _candidate_arm(
        "lineage_diversified_retrieval",
        env=env,
        policy=policy,
        lifecycle=replace(lifecycle, public_retrieval="diversified"),
    )
    arms = _run(connection, config=config, config_hash=config_hash, code_sha=code_sha, number=71, arms=[standard, diversified])
    s = next(arm for arm in arms if arm["label"] == "standard_public_retrieval")
    d = next(arm for arm in arms if arm["label"] == "lineage_diversified_retrieval")
    sm = s["metrics"]
    dm = d["metrics"]
    assert isinstance(sm, Mapping) and isinstance(dm, Mapping)
    hhi_reduction = float(sm["mean_retrieval_lineage_hhi"]) - float(dm["mean_retrieval_lineage_hhi"])
    knowledge_ratio = float(dm["mean_public_knowledge_signal"]) / max(float(sm["mean_public_knowledge_signal"]), 1e-9)
    safe = (
        float(dm["success_rate"]) >= float(sm["success_rate"]) - config.integration.success_tolerance
        and knowledge_ratio >= config.minimum_knowledge_retention
    )
    selected = d if safe and hhi_reduction >= 0.05 else s
    selected_retrieval = "diversified" if selected["label"] == "lineage_diversified_retrieval" else "standard"
    state["cultural_diversification_selected"] = selected_retrieval == "diversified"
    state["candidate_lifecycle"] = replace(lifecycle, public_retrieval=selected_retrieval).as_dict()
    return _record(
        number=71,
        focus="cultural_persistence",
        question=(
            "After actor succession, does lineage-diversified public retrieval reduce cultural "
            "monopoly without destroying useful shared knowledge?"
        ),
        arms=arms,
        selected=selected,
        next_focus="lifecycle_synthesis",
        extras={"cultural_hhi_reduction": hhi_reduction, "knowledge_retention_ratio": knowledge_ratio},
        validated=safe and hhi_reduction >= 0.05,
    )


def _synthesis(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    raw_lifecycle = state["candidate_lifecycle"]
    raw_policy = state["candidate_policy"]
    if not isinstance(raw_lifecycle, Mapping) or not isinstance(raw_policy, Mapping):
        raise ValueError("candidate is missing")
    lifecycle = _lifecycle_from_mapping(raw_lifecycle)
    policy = _policy_from_mapping(raw_policy)
    env = config.integration.environment
    arms = _run(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=72,
        arms=[
            immortal_arm("immortal_candidate_policy", policy=policy, env=env),
            _candidate_arm("lifecycle_candidate", env=env, policy=policy, lifecycle=lifecycle),
            immortal_arm("immortal_no_reputation", policy=no_reputation_policy(), env=env),
        ],
    )
    candidate = next(arm for arm in arms if arm["label"] == "lifecycle_candidate")
    immortal = next(arm for arm in arms if arm["label"] == "immortal_candidate_policy")
    selected, _, diagnostics = choose_lifecycle([immortal, candidate], reference_label="immortal_candidate_policy", config=config)
    diag = diagnostics["lifecycle_candidate"]
    valid = bool(state["exit_validated"]) and bool(state["stress_validated"]) and selected["label"] == "lifecycle_candidate"
    state["mechanism_validated"] = valid
    return _record(
        number=72,
        focus="lifecycle_synthesis",
        question=(
            "Can fast learning retain task quality while succession materially reduces actor "
            "entrenchment and useful public knowledge survives?"
        ),
        arms=arms,
        selected=candidate if valid else immortal,
        next_focus="independent_replication",
        extras={"mechanism_validated": valid, **diag},
        validated=valid,
    )


def _replication(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    raw_lifecycle = state["candidate_lifecycle"]
    raw_policy = state["candidate_policy"]
    if not isinstance(raw_lifecycle, Mapping) or not isinstance(raw_policy, Mapping):
        raise ValueError("candidate is missing")
    lifecycle = _lifecycle_from_mapping(raw_lifecycle)
    policy = _policy_from_mapping(raw_policy)
    env = config.integration.environment
    arms = _run(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=73,
        seeds=config.replication_seeds,
        arms=[
            immortal_arm("immortal_candidate_policy", policy=policy, env=env),
            _candidate_arm("lifecycle_candidate", env=env, policy=policy, lifecycle=lifecycle),
        ],
    )
    candidate = next(arm for arm in arms if arm["label"] == "lifecycle_candidate")
    immortal = next(arm for arm in arms if arm["label"] == "immortal_candidate_policy")
    selected, _, diagnostics = choose_lifecycle(arms, reference_label="immortal_candidate_policy", config=config)
    diag = diagnostics["lifecycle_candidate"]
    valid = bool(state["mechanism_validated"]) and selected["label"] == "lifecycle_candidate"
    state["replication_validated"] = valid
    return _record(
        number=73,
        focus="independent_replication",
        question="Does the selected succession mechanism replicate on independent seeds?",
        arms=arms,
        selected=candidate if valid else immortal,
        next_focus="unseen_holdout",
        extras={"replication_validated": valid, **diag},
        validated=valid,
    )


def _holdout(connection: Connection[Any], *, config: LifecycleConfig, config_hash: str, code_sha: str, state: dict[str, object]) -> dict[str, object]:
    raw_lifecycle = state["candidate_lifecycle"]
    raw_policy = state["candidate_policy"]
    if not isinstance(raw_lifecycle, Mapping) or not isinstance(raw_policy, Mapping):
        raise ValueError("candidate is missing")
    lifecycle = _lifecycle_from_mapping(raw_lifecycle)
    policy = _policy_from_mapping(raw_policy)
    base = config.integration.environment
    env = replace(
        base,
        cycles=config.integration.holdout_cycles,
        shift_period=config.integration.holdout_shift_period,
        candidate_count=config.integration.holdout_candidate_count,
    )
    if lifecycle.mode != "immortal":
        lifecycle = replace(
            lifecycle,
            lifetime_cycles=config.holdout_lifetime,
            phase_offset=(lifecycle.phase_offset + 5) % config.holdout_lifetime,
        )
    arms = _run(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=74,
        seeds=config.integration.holdout_seeds,
        arms=[
            immortal_arm("immortal_candidate_policy", policy=policy, env=env),
            _candidate_arm("lifecycle_candidate", env=env, policy=policy, lifecycle=lifecycle),
            immortal_arm("immortal_no_reputation", policy=no_reputation_policy(), env=env),
        ],
    )
    candidate = next(arm for arm in arms if arm["label"] == "lifecycle_candidate")
    immortal = next(arm for arm in arms if arm["label"] == "immortal_candidate_policy")
    selected, _, diagnostics = choose_lifecycle([immortal, candidate], reference_label="immortal_candidate_policy", config=config)
    diag = diagnostics["lifecycle_candidate"]
    valid = (
        bool(state["mechanism_validated"])
        and bool(state["replication_validated"])
        and selected["label"] == "lifecycle_candidate"
    )
    state["validated"] = valid
    return _record(
        number=74,
        focus="unseen_holdout",
        question=(
            "Does the succession mechanism generalize to unseen seeds, a new remap cadence, "
            "and an unseen competitive-lifetime schedule?"
        ),
        arms=arms,
        selected=candidate if valid else immortal,
        next_focus=None,
        extras={**diag},
        validated=valid,
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
            raise ValueError("only Experiment 063 can start without a checkpoint")
        state = _initial_checkpoint(config=config, config_hash=config_hash, code_sha=code_sha)
    else:
        _validate_checkpoint(checkpoint, number=number, config=config, config_hash=config_hash, code_sha=code_sha)
        state = dict(checkpoint)

    if number == 63:
        record = _baseline(connection, config=config, config_hash=config_hash, code_sha=code_sha)
    elif number == 64:
        record = _fixed_exit(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
    elif number == 65:
        record = _stochastic_exit(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
    elif number == 66:
        record = _lifetime_response(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
    elif number == 67:
        record = _death_vs_retirement(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
    elif number == 68:
        record = _advisory_retirement(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
    elif number == 69:
        record = _reputation_interaction_step(connection, config=config, config_hash=config_hash, code_sha=code_sha, state=state)
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
    write_step_artifacts(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        output_dir=output_dir,
        record=record,
        checkpoint=state,
    )
    return {"record": record, "checkpoint": state}


def load_checkpoint(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("checkpoint must contain a JSON object")
    return value
