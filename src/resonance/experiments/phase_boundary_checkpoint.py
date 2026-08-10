"""Checkpointed execution for phase-boundary Experiments 041 through 052."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from psycopg import Connection

from .integration_campaign import (
    ArmSpec,
    ReputationPolicy,
    _run_experiment,
    export_integration_campaign_artifacts,
)
from .phase_boundary_campaign import (
    PhaseBoundaryConfig,
    _adjust_theta,
    _boundary_estimate,
    _candidate_policy_for_ratio,
    _choose_selected,
    _clamp_shift,
    _effect,
    _gated_policy,
    _learning_timescale,
    _next_bracket_shift,
    _paired_experiment,
    _predicted_sign,
    _record_phase,
    _sign,
    _stable_environment,
    _test_environment,
    reference_policy,
)

_CHECKPOINT_VERSION = 1
_FIRST_EXPERIMENT = 41
_LAST_EXPERIMENT = 52


def _policy_from_mapping(value: Mapping[str, object]) -> ReputationPolicy:
    return ReputationPolicy(**dict(value))  # type: ignore[arg-type]


def _initial_checkpoint(*, config: PhaseBoundaryConfig, config_hash: str, code_sha: str) -> dict[str, object]:
    return {
        "version": _CHECKPOINT_VERSION,
        "campaign": config.integration.name,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "last_completed": 40,
        "next_experiment": 41,
        "learning_timescale_cycles": None,
        "next_shift": None,
        "observations": [],
        "boundary_shift_cycles": None,
        "boundary_ratio": None,
        "boundary_bracketed": False,
        "validation_gains": [],
        "validation_results": [],
        "pending_validation": None,
        "chosen_policy": None,
        "timescale_gate_selected": False,
        "candidate_sign": None,
        "candidate_policy": None,
        "validated": None,
    }


def _validate_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    number: int,
    config: PhaseBoundaryConfig,
    config_hash: str,
    code_sha: str,
) -> None:
    if int(checkpoint.get("version", -1)) != _CHECKPOINT_VERSION:
        raise ValueError("unsupported phase-boundary checkpoint version")
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


def _require_float(checkpoint: Mapping[str, object], key: str) -> float:
    value = checkpoint.get(key)
    if value is None:
        raise ValueError(f"checkpoint is missing {key}")
    return float(value)


def _require_sequence(checkpoint: Mapping[str, object], key: str) -> list[object]:
    value = checkpoint.get(key)
    if not isinstance(value, list):
        raise ValueError(f"checkpoint is missing list {key}")
    return list(value)


def _selected_arm(record: Mapping[str, object]) -> Mapping[str, object]:
    arms = record["arms"]
    assert isinstance(arms, Sequence)
    return next(
        arm
        for arm in arms
        if isinstance(arm, Mapping) and arm["label"] == record["selected_label"]
    )


def _render_experiment_comment(
    record: Mapping[str, object],
    *,
    config_hash: str,
    code_sha: str,
) -> str:
    number = int(record["number"])
    selected = _selected_arm(record)
    metrics = selected["metrics"]
    invariants = selected["invariants"]
    assert isinstance(metrics, Mapping) and isinstance(invariants, Mapping)
    lines = [
        f"<!-- phase-boundary-041-052:experiment-{number:03d} -->",
        f"## Experiment {number:03d} — completed",
        "",
        f"**Question:** {record['question']}",
        "",
        f"- Commit: `{code_sha}`",
        f"- Config hash: `{config_hash}`",
        f"- Focus: `{record['focus']}`",
        f"- Selected arm: `{record['selected_label']}`",
        f"- Success: **{float(metrics['success_rate']):.6f}**",
        f"- Agent/domain MI: **{float(metrics['agent_domain_mutual_information']):.6f}**",
        f"- Specialization: **{float(metrics['mean_specialization']):.6f}**",
        f"- Early incumbent share: **{float(metrics['early_incumbent_share']):.6f}**",
        f"- Hard invariants: **{all(bool(value) for value in invariants.values())}**",
        f"- Next focus: `{record['next_experiment_focus']}`",
    ]
    for key in (
        "learning_timescale_cycles",
        "shift_period",
        "timescale_ratio",
        "reference_effect",
        "reference_sign",
        "boundary_ratio",
        "boundary_bracketed",
        "gate_scale",
        "candidate_effect",
        "predicted_reference_sign",
        "observed_reference_sign",
    ):
        if key in record:
            lines.append(f"- {key}: **{record[key]}**")
    if "validated" in record:
        lines.append(f"- Validated: **{record['validated']}**")
    lines.extend(["", "Top arms:"])
    arms = record["arms"]
    assert isinstance(arms, Sequence)
    for arm in sorted(
        (item for item in arms if isinstance(item, Mapping)),
        key=lambda item: float(item["utility"]),
        reverse=True,
    ):
        arm_metrics = arm["metrics"]
        assert isinstance(arm_metrics, Mapping)
        lines.append(
            f"- `{arm['label']}` — utility {float(arm['utility']):.6f}; "
            f"success {float(arm_metrics['success_rate']):.6f}; "
            f"incumbent {float(arm_metrics['early_incumbent_share']):.6f}; "
            f"feasible {bool(arm['feasible'])}"
        )
    return "\n".join(lines) + "\n"


def _render_synthesis(checkpoint: Mapping[str, object]) -> str:
    return "\n".join(
        [
            "<!-- phase-boundary-041-052:synthesis -->",
            "## Phase Boundary Campaign 041–052 — Final Synthesis",
            "",
            f"- Commit: `{checkpoint['code_sha']}`",
            f"- Config hash: `{checkpoint['config_hash']}`",
            f"- Learning timescale: **{float(checkpoint['learning_timescale_cycles']):.6f} cycles**",
            f"- Boundary shift: **{float(checkpoint['boundary_shift_cycles']):.6f} cycles**",
            f"- Boundary ratio θ: **{float(checkpoint['boundary_ratio']):.6f}**",
            f"- Boundary bracketed: **{bool(checkpoint['boundary_bracketed'])}**",
            f"- Candidate policy: `{checkpoint['candidate_policy']}`",
            f"- Holdout validated: **{bool(checkpoint['validated'])}**",
            "- Experiments completed: **12**",
            "",
            "Each experiment has its own checkpoint and raw real-market evidence artifact.",
        ]
    ) + "\n"


def _write_step_artifacts(
    connection: Connection[Any],
    *,
    config: PhaseBoundaryConfig,
    config_hash: str,
    code_sha: str,
    output_dir: str | Path,
    record: Mapping[str, object],
    checkpoint: Mapping[str, object],
) -> None:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    summary = {
        "campaign": config.integration.name,
        "code_sha": code_sha,
        "config_hash": config_hash,
        "experiments": [dict(record)],
        "checkpoint": dict(checkpoint),
    }
    export_integration_campaign_artifacts(
        connection,
        config=config.integration,
        output_dir=destination,
        summary=summary,
    )
    (destination / "checkpoint.json").write_text(
        json.dumps(dict(checkpoint), indent=2, sort_keys=True) + "\n"
    )
    (destination / "notebook.md").write_text(
        _render_experiment_comment(record, config_hash=config_hash, code_sha=code_sha)
    )
    if int(record["number"]) == _LAST_EXPERIMENT:
        (destination / "campaign-summary.md").write_text(_render_synthesis(checkpoint))


def run_phase_boundary_step(
    connection: Connection[Any],
    *,
    config: PhaseBoundaryConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    checkpoint: Mapping[str, object] | None,
    output_dir: str | Path,
) -> dict[str, object]:
    """Run exactly one adaptive phase-boundary experiment and emit a checkpoint."""

    if not _FIRST_EXPERIMENT <= number <= _LAST_EXPERIMENT:
        raise ValueError("experiment number must be between 41 and 52")
    if checkpoint is None:
        if number != _FIRST_EXPERIMENT:
            raise ValueError("only Experiment 041 may start without a checkpoint")
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

    base = config.integration.environment
    policy = reference_policy()
    record: dict[str, object]

    if number == 41:
        stable = _stable_environment(base, cycles=config.stable_cycles, practice_gain=base.practice_gain)
        arms, reference, control, effect, sign = _paired_experiment(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            number=number,
            env=stable,
            seeds=config.integration.seeds,
            policy=policy,
        )
        tau_learning = _learning_timescale(
            connection,
            reference,
            target_fraction=config.learning_target_fraction,
        )
        start_shift = _clamp_shift(config, tau_learning)
        record = _record_phase(
            number=number,
            focus="learning_timescale",
            question=(
                "How many cycles does identity-conditioned specialization need to reach half "
                "of its stable-regime level?"
            ),
            arms=arms,
            selected=_choose_selected(reference, control, sign),
            motivating_failure="timescale_unknown",
            observed_failure=None,
            next_focus=f"regime_period:{start_shift}",
            extras={
                "learning_timescale_cycles": tau_learning,
                "reference_effect": effect,
                "reference_sign": sign,
            },
        )
        state["learning_timescale_cycles"] = tau_learning
        state["next_shift"] = start_shift

    elif 42 <= number <= 45:
        tau_learning = _require_float(state, "learning_timescale_cycles")
        next_shift = int(_require_float(state, "next_shift"))
        env = _test_environment(base, shift_period=next_shift, practice_gain=base.practice_gain)
        arms, reference, control, effect, sign = _paired_experiment(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            number=number,
            env=env,
            seeds=config.integration.seeds,
            policy=policy,
        )
        observations = [dict(item) for item in _require_sequence(state, "observations")]
        observations.append(
            {
                "experiment": number,
                "shift_period": env.shift_period,
                "ratio": env.shift_period / max(tau_learning, 1.0),
                "effect": effect,
                "sign": sign,
                "feasible": bool(reference["feasible"]),
            }
        )
        selected = _choose_selected(reference, control, sign)
        if number < 45:
            next_shift = _next_bracket_shift(observations, config=config)
            state["next_shift"] = next_shift
            next_focus = f"regime_period:{next_shift}"
        else:
            boundary_shift, theta, bracketed = _boundary_estimate(
                observations,
                tau_learning=tau_learning,
            )
            validation_gains = (
                [config.slow_practice_gain, config.fast_practice_gain]
                if theta >= 1.0
                else [config.fast_practice_gain, config.slow_practice_gain]
            )
            state["boundary_shift_cycles"] = boundary_shift
            state["boundary_ratio"] = theta
            state["boundary_bracketed"] = bracketed
            state["validation_gains"] = validation_gains
            next_focus = "boundary_estimate"
        state["observations"] = observations
        record = _record_phase(
            number=number,
            focus="regime_period",
            question=(
                "At this regime duration, does the fixed reputation mechanism improve task success "
                "without violating plasticity or economic constraints?"
            ),
            arms=arms,
            selected=selected,
            motivating_failure="phase_boundary",
            observed_failure=None if sign == "neutral" else sign,
            next_focus=next_focus,
            extras={
                "learning_timescale_cycles": tau_learning,
                "shift_period": env.shift_period,
                "timescale_ratio": env.shift_period / max(tau_learning, 1.0),
                "reference_effect": effect,
                "reference_sign": sign,
            },
        )

    elif number in {46, 48}:
        gains = [float(item) for item in _require_sequence(state, "validation_gains")]
        pair_index = 0 if number == 46 else 1
        gain = gains[pair_index]
        theta = _require_float(state, "boundary_ratio")
        stable_env = _stable_environment(base, cycles=config.stable_cycles, practice_gain=gain)
        arms, reference, control, effect, sign = _paired_experiment(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            number=number,
            env=stable_env,
            seeds=config.integration.seeds,
            policy=policy,
        )
        tau_gain = _learning_timescale(
            connection,
            reference,
            target_fraction=config.learning_target_fraction,
        )
        predicted_shift = _clamp_shift(config, theta * tau_gain)
        state["pending_validation"] = {
            "pair_index": pair_index,
            "practice_gain": gain,
            "tau_learning": tau_gain,
            "predicted_shift": predicted_shift,
        }
        record = _record_phase(
            number=number,
            focus="learning_timescale_replication",
            question="Does changing practice gain move the measured specialization-learning timescale?",
            arms=arms,
            selected=_choose_selected(reference, control, sign),
            motivating_failure="boundary_scaling",
            observed_failure=None,
            next_focus=f"scaled_boundary:{predicted_shift}",
            extras={
                "practice_gain": gain,
                "learning_timescale_cycles": tau_gain,
                "boundary_ratio": theta,
                "predicted_boundary_shift": predicted_shift,
            },
        )

    elif number in {47, 49}:
        pending = state.get("pending_validation")
        if not isinstance(pending, Mapping):
            raise ValueError("checkpoint is missing pending validation state")
        gain = float(pending["practice_gain"])
        tau_gain = float(pending["tau_learning"])
        predicted_shift = int(pending["predicted_shift"])
        theta = _require_float(state, "boundary_ratio")
        test_env = _test_environment(base, shift_period=predicted_shift, practice_gain=gain)
        arms, reference, control, effect, sign = _paired_experiment(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            number=number,
            env=test_env,
            seeds=config.integration.seeds,
            policy=policy,
        )
        theta = _adjust_theta(theta, sign)
        validation_results = [dict(item) for item in _require_sequence(state, "validation_results")]
        validation_results.append(
            {
                "practice_gain": gain,
                "tau_learning": tau_gain,
                "shift_period": test_env.shift_period,
                "ratio": test_env.shift_period / max(tau_gain, 1.0),
                "effect": effect,
                "sign": sign,
            }
        )
        state["boundary_ratio"] = theta
        state["validation_results"] = validation_results
        state["pending_validation"] = None
        record = _record_phase(
            number=number,
            focus="scaled_boundary",
            question="Does the phase-boundary ratio predict reputation's sign after the learning rate changes?",
            arms=arms,
            selected=_choose_selected(reference, control, sign),
            motivating_failure="boundary_scaling",
            observed_failure=sign,
            next_focus="second_learning_rate" if number == 47 else "adaptive_disengagement",
            extras={
                "practice_gain": gain,
                "learning_timescale_cycles": tau_gain,
                "timescale_ratio": test_env.shift_period / max(tau_gain, 1.0),
                "reference_effect": effect,
                "reference_sign": sign,
                "updated_boundary_ratio": theta,
            },
        )

    elif number == 50:
        tau_learning = _require_float(state, "learning_timescale_cycles")
        theta = _require_float(state, "boundary_ratio")
        near_shift = _clamp_shift(config, 0.75 * theta * tau_learning)
        near_env = _test_environment(base, shift_period=near_shift, practice_gain=base.practice_gain)
        near_ratio = near_env.shift_period / max(tau_learning, 1.0)
        gated = _gated_policy(policy, near_ratio, theta)
        arms, _, control = _run_experiment(
            connection,
            config=config.integration,
            config_hash=config_hash,
            number=number,
            arms=[
                ArmSpec("no_reputation", ReputationPolicy(), near_env),
                ArmSpec("full_reputation", policy, near_env),
                ArmSpec("timescale_gated", gated, near_env),
            ],
            seeds=config.integration.seeds,
            code_sha=code_sha,
        )
        gated_arm = next(arm for arm in arms if arm["label"] == "timescale_gated")
        full_arm = next(arm for arm in arms if arm["label"] == "full_reputation")
        best_reputation = max(
            (gated_arm, full_arm),
            key=lambda arm: (bool(arm["feasible"]), float(arm["utility"])),
        )
        selected = best_reputation if bool(best_reputation["feasible"]) else control
        timescale_gate_selected = selected["label"] == "timescale_gated"
        if timescale_gate_selected:
            chosen_policy = gated
        elif selected["label"] == "full_reputation":
            chosen_policy = policy
        else:
            chosen_policy = ReputationPolicy()
        state["timescale_gate_selected"] = timescale_gate_selected
        state["chosen_policy"] = chosen_policy.as_dict()
        record = _record_phase(
            number=number,
            focus="adaptive_disengagement",
            question="Can a timescale-gated reputation weight recover quality just below the estimated phase boundary?",
            arms=arms,
            selected=selected,
            motivating_failure="rapid_regime_quality",
            observed_failure=None if bool(selected["feasible"]) else "quality",
            next_focus="independent_replication",
            extras={
                "boundary_ratio": theta,
                "test_ratio": near_ratio,
                "gate_scale": gated.weight / policy.weight,
            },
        )

    elif number == 51:
        gains = [float(item) for item in _require_sequence(state, "validation_gains")]
        validation_results = [dict(item) for item in _require_sequence(state, "validation_results")]
        if not validation_results:
            raise ValueError("checkpoint is missing validation results")
        chosen_data = state.get("chosen_policy")
        if not isinstance(chosen_data, Mapping):
            raise ValueError("checkpoint is missing chosen policy")
        chosen_policy = _policy_from_mapping(chosen_data)
        theta = _require_float(state, "boundary_ratio")
        replication_gain = gains[-1]
        replication_tau = float(validation_results[-1]["tau_learning"])
        replication_shift = _clamp_shift(config, theta * replication_tau)
        replication_env = _test_environment(
            base,
            shift_period=replication_shift,
            practice_gain=replication_gain,
        )
        replication_ratio = replication_env.shift_period / max(replication_tau, 1.0)
        replication_policy = _candidate_policy_for_ratio(
            policy,
            chosen_policy,
            timescale_gate_selected=bool(state["timescale_gate_selected"]),
            ratio=replication_ratio,
            theta=theta,
        )
        arms, candidate, control, effect, sign = _paired_experiment(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            number=number,
            env=replication_env,
            seeds=config.replication_seeds,
            policy=replication_policy,
            reference_label="candidate_policy",
        )
        state["candidate_sign"] = sign
        state["candidate_policy"] = replication_policy.as_dict()
        record = _record_phase(
            number=number,
            focus="independent_replication",
            question="Does the candidate timescale policy replicate on independent seeds near the inferred boundary?",
            arms=arms,
            selected=_choose_selected(candidate, control, sign),
            motivating_failure="generalization",
            observed_failure=sign,
            next_focus="unseen_holdout",
            extras={
                "boundary_ratio": theta,
                "practice_gain": replication_gain,
                "learning_timescale_cycles": replication_tau,
                "shift_period": replication_shift,
                "timescale_ratio": replication_ratio,
                "candidate_effect": effect,
                "candidate_weight": replication_policy.weight,
            },
        )

    else:
        tau_learning = _require_float(state, "learning_timescale_cycles")
        theta = _require_float(state, "boundary_ratio")
        candidate_sign = state.get("candidate_sign")
        if candidate_sign not in {"positive", "negative", "neutral"}:
            raise ValueError("checkpoint is missing candidate sign")
        chosen_data = state.get("chosen_policy")
        if not isinstance(chosen_data, Mapping):
            raise ValueError("checkpoint is missing chosen policy")
        chosen_policy = _policy_from_mapping(chosen_data)
        holdout_multiplier = 0.75 if candidate_sign == "positive" else 1.25
        holdout_shift = _clamp_shift(config, holdout_multiplier * theta * tau_learning)
        holdout_env = replace(
            _test_environment(base, shift_period=holdout_shift, practice_gain=base.practice_gain),
            cycles=config.integration.holdout_cycles,
            shift_period=min(holdout_shift, config.integration.holdout_cycles - 1),
            candidate_count=config.integration.holdout_candidate_count,
        )
        holdout_ratio = holdout_env.shift_period / max(tau_learning, 1.0)
        holdout_policy = _candidate_policy_for_ratio(
            policy,
            chosen_policy,
            timescale_gate_selected=bool(state["timescale_gate_selected"]),
            ratio=holdout_ratio,
            theta=theta,
        )
        arms, _, control = _run_experiment(
            connection,
            config=config.integration,
            config_hash=config_hash,
            number=number,
            arms=[
                ArmSpec("no_reputation", ReputationPolicy(), holdout_env),
                ArmSpec("reference_reputation", policy, holdout_env),
                ArmSpec("candidate_policy", holdout_policy, holdout_env),
            ],
            seeds=config.integration.holdout_seeds,
            code_sha=code_sha,
        )
        reference = next(arm for arm in arms if arm["label"] == "reference_reputation")
        candidate = next(arm for arm in arms if arm["label"] == "candidate_policy")
        reference_effect = _effect(reference, control)
        predicted_reference_sign = _predicted_sign(holdout_ratio, theta)
        observed_reference_sign = _sign(
            reference_effect,
            feasible=bool(reference["feasible"]),
            epsilon=config.effect_epsilon,
        )
        candidate_effect = _effect(candidate, control)
        invariants = candidate["invariants"]
        assert isinstance(invariants, Mapping)
        validated = (
            observed_reference_sign == predicted_reference_sign
            and bool(candidate["feasible"])
            and candidate_effect >= -config.integration.success_tolerance
            and all(bool(value) for value in invariants.values())
        )
        state["candidate_policy"] = holdout_policy.as_dict()
        state["validated"] = validated
        record = _record_phase(
            number=number,
            focus="unseen_holdout",
            question=(
                "Does the inferred timescale boundary predict reputation's sign on unseen seeds, "
                "and does the candidate policy remain feasible?"
            ),
            arms=arms,
            selected=candidate,
            motivating_failure="generalization",
            observed_failure=None if validated else "boundary_or_quality",
            next_focus=None,
            validated=validated,
            extras={
                "learning_timescale_cycles": tau_learning,
                "boundary_shift_cycles": state["boundary_shift_cycles"],
                "boundary_ratio": theta,
                "boundary_bracketed": state["boundary_bracketed"],
                "holdout_shift_period": holdout_env.shift_period,
                "holdout_ratio": holdout_ratio,
                "predicted_reference_sign": predicted_reference_sign,
                "observed_reference_sign": observed_reference_sign,
                "reference_effect": reference_effect,
                "candidate_effect": candidate_effect,
            },
        )

    state["last_completed"] = number
    state["next_experiment"] = number + 1 if number < _LAST_EXPERIMENT else None
    _write_step_artifacts(
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
