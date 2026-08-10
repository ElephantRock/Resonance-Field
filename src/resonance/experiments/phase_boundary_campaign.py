"""Adaptive phase-boundary campaign for Experiments 041 through 052."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import Connection

from .integration_campaign import (
    ArmSpec,
    IntegrationCampaignConfig,
    IntegrationEnvironment,
    ReputationPolicy,
    _evaluate_arms,
    _record,
    _run_experiment,
    export_integration_campaign_artifacts,
)


@dataclass(frozen=True, slots=True)
class PhaseBoundaryConfig:
    integration: IntegrationCampaignConfig
    stable_cycles: int
    min_shift_period: int
    max_shift_period: int
    learning_target_fraction: float
    effect_epsilon: float
    slow_practice_gain: float
    fast_practice_gain: float
    replication_seeds: tuple[int, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "PhaseBoundaryConfig":
        integration = IntegrationCampaignConfig.from_mapping(value)
        phase = value["phase_boundary"]
        assert isinstance(phase, Mapping)
        config = cls(
            integration=integration,
            stable_cycles=int(phase["stable_cycles"]),
            min_shift_period=int(phase["min_shift_period"]),
            max_shift_period=int(phase["max_shift_period"]),
            learning_target_fraction=float(phase["learning_target_fraction"]),
            effect_epsilon=float(phase["effect_epsilon"]),
            slow_practice_gain=float(phase["slow_practice_gain"]),
            fast_practice_gain=float(phase["fast_practice_gain"]),
            replication_seeds=tuple(int(item) for item in phase["replication_seeds"]),
        )
        if config.stable_cycles <= 12:
            raise ValueError("stable_cycles must exceed twelve cycles")
        if not 1 <= config.min_shift_period < config.max_shift_period < config.stable_cycles:
            raise ValueError("shift-period bounds must fit inside stable_cycles")
        if not 0 < config.learning_target_fraction < 1:
            raise ValueError("learning_target_fraction must be in (0, 1)")
        if config.effect_epsilon < 0:
            raise ValueError("effect_epsilon must be non-negative")
        if min(config.slow_practice_gain, config.fast_practice_gain) <= 0:
            raise ValueError("practice gains must be positive")
        if config.slow_practice_gain >= config.fast_practice_gain:
            raise ValueError("slow_practice_gain must be below fast_practice_gain")
        if not config.replication_seeds:
            raise ValueError("replication_seeds are required")
        return config


def reference_policy() -> ReputationPolicy:
    """Return the pre-stress policy selected before Experiment 038."""

    return ReputationPolicy(
        mode="reputation",
        weight=0.45,
        freshness_half_life_cycles=None,
        mass_gate=0.0,
        blend_skill=0.25,
        positive_weight=1.0,
        negative_weight=1.0,
        shift_reset=0.10,
        temperature=1.0,
        score_cap=0.20,
        uncertainty_prior=0.0,
        exposure_penalty=0.04,
        exposure_window=12,
    )


def _mutual_information(rows: Sequence[tuple[str, int]]) -> float:
    if not rows:
        return 0.0
    total = len(rows)
    joint = Counter(rows)
    domains = Counter(domain for domain, _ in rows)
    winners = Counter(winner for _, winner in rows)
    value = 0.0
    for (domain, winner), count in joint.items():
        p_joint = count / total
        p_domain = domains[domain] / total
        p_winner = winners[winner] / total
        value += p_joint * math.log(p_joint / (p_domain * p_winner))
    return value


def _learning_timescale_for_run(
    connection: Connection[Any],
    run_id: str,
    *,
    target_fraction: float,
) -> float:
    rows = connection.execute(
        """
        SELECT cycle, task_domain, winner_slot
        FROM integration_campaign_outcomes
        WHERE run_id = %s
        ORDER BY cycle
        """,
        (UUID(str(run_id)),),
    ).fetchall()
    observations = [(str(row["task_domain"]), int(row["winner_slot"])) for row in rows]
    if len(observations) < 8:
        return float(len(observations))
    final_mi = _mutual_information(observations)
    if final_mi <= 1e-12:
        return float(len(observations))
    threshold = target_fraction * final_mi
    crossings: list[float] = []
    for end in range(8, len(observations) + 1):
        if _mutual_information(observations[:end]) >= threshold:
            crossings.append(float(end))
            if len(crossings) >= 3 and crossings[-1] - crossings[-3] == 2:
                return crossings[-3]
        else:
            crossings.clear()
    return float(len(observations))


def _learning_timescale(
    connection: Connection[Any],
    arm: Mapping[str, object],
    *,
    target_fraction: float,
) -> float:
    run_ids = arm["run_ids"]
    assert isinstance(run_ids, Sequence)
    return statistics.mean(
        _learning_timescale_for_run(connection, str(run_id), target_fraction=target_fraction)
        for run_id in run_ids
    )


def _metrics(arm: Mapping[str, object]) -> Mapping[str, float]:
    metrics = arm["metrics"]
    assert isinstance(metrics, Mapping)
    return metrics  # type: ignore[return-value]


def _effect(reference: Mapping[str, object], control: Mapping[str, object]) -> float:
    return float(_metrics(reference)["success_rate"]) - float(_metrics(control)["success_rate"])


def _sign(effect: float, *, feasible: bool, epsilon: float) -> str:
    if not feasible or effect <= -epsilon:
        return "negative"
    if effect >= epsilon:
        return "positive"
    return "neutral"


def _clamp_shift(config: PhaseBoundaryConfig, value: float) -> int:
    return max(config.min_shift_period, min(config.max_shift_period, int(round(value))))


def _next_unused(candidate: int, used: set[int], config: PhaseBoundaryConfig) -> int:
    candidate = _clamp_shift(config, candidate)
    if candidate not in used:
        return candidate
    for distance in range(1, config.max_shift_period - config.min_shift_period + 1):
        for value in (candidate - distance, candidate + distance):
            if config.min_shift_period <= value <= config.max_shift_period and value not in used:
                return value
    raise RuntimeError("no unused shift period remains inside configured bounds")


def _next_bracket_shift(
    observations: Sequence[Mapping[str, object]],
    *,
    config: PhaseBoundaryConfig,
) -> int:
    used = {int(item["shift_period"]) for item in observations}
    positive = sorted(
        int(item["shift_period"]) for item in observations if item["sign"] == "positive"
    )
    negative = sorted(
        int(item["shift_period"]) for item in observations if item["sign"] == "negative"
    )
    if positive and negative:
        pairs = [(n, p) for n in negative for p in positive if n < p]
        if pairs:
            low, high = min(pairs, key=lambda pair: pair[1] - pair[0])
            return _next_unused((low + high) // 2, used, config)
        nearest = min(
            ((n, p) for n in negative for p in positive),
            key=lambda pair: abs(pair[1] - pair[0]),
        )
        return _next_unused(sum(nearest) // 2, used, config)
    if positive:
        return _next_unused(max(config.min_shift_period, min(positive) // 2), used, config)
    if negative:
        return _next_unused(min(config.max_shift_period, max(negative) * 2), used, config)
    best = min(observations, key=lambda item: abs(float(item["effect"])))
    direction = -1 if float(best["effect"]) >= 0 else 1
    return _next_unused(
        int(best["shift_period"]) + direction * max(2, int(best["shift_period"]) // 3),
        used,
        config,
    )


def _boundary_estimate(
    observations: Sequence[Mapping[str, object]],
    *,
    tau_learning: float,
) -> tuple[float, float, bool]:
    positive = sorted(
        (int(item["shift_period"]), float(item["effect"]))
        for item in observations
        if item["sign"] == "positive"
    )
    negative = sorted(
        (int(item["shift_period"]), float(item["effect"]))
        for item in observations
        if item["sign"] == "negative"
    )
    ordered = [(n, p) for n, _ in negative for p, _ in positive if n < p]
    if ordered:
        low, high = min(ordered, key=lambda pair: pair[1] - pair[0])
        shift = (low + high) / 2
        return shift, shift / max(tau_learning, 1.0), True
    closest = min(observations, key=lambda item: abs(float(item["effect"])))
    shift = float(closest["shift_period"])
    return shift, shift / max(tau_learning, 1.0), False


def _test_environment(base: IntegrationEnvironment, *, shift_period: int, practice_gain: float) -> IntegrationEnvironment:
    cycles = max(base.cycles, min(180, max(24, shift_period * 3)))
    return replace(base, cycles=cycles, shift_period=min(shift_period, cycles - 1), practice_gain=practice_gain)


def _stable_environment(base: IntegrationEnvironment, *, cycles: int, practice_gain: float) -> IntegrationEnvironment:
    return replace(base, cycles=cycles, shift_period=cycles - 1, practice_gain=practice_gain)


def _paired_experiment(
    connection: Connection[Any],
    *,
    config: PhaseBoundaryConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    env: IntegrationEnvironment,
    seeds: Sequence[int],
    policy: ReputationPolicy,
    reference_label: str = "reference_reputation",
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object], float, str]:
    evaluated, _, control = _run_experiment(
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
    reference = next(arm for arm in evaluated if arm["label"] == reference_label)
    effect = _effect(reference, control)
    sign = _sign(
        effect,
        feasible=bool(reference["feasible"]),
        epsilon=config.effect_epsilon,
    )
    return evaluated, reference, control, effect, sign


def _record_phase(
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


def _choose_selected(reference: Mapping[str, object], control: Mapping[str, object], sign: str) -> Mapping[str, object]:
    return reference if sign == "positive" else control


def _adjust_theta(theta: float, sign: str) -> float:
    if sign == "positive":
        return max(0.20, theta * 0.90)
    if sign == "negative":
        return min(8.0, theta * 1.10)
    return theta


def _gated_policy(policy: ReputationPolicy, ratio: float, theta: float) -> ReputationPolicy:
    scale = max(0.0, min(1.0, ratio / max(theta, 1e-9)))
    return replace(policy, weight=policy.weight * scale)


def _predicted_sign(ratio: float, theta: float) -> str:
    relative = ratio / max(theta, 1e-9)
    if relative >= 1.05:
        return "positive"
    if relative <= 0.95:
        return "negative"
    return "neutral"


def run_phase_boundary_campaign(
    connection: Connection[Any],
    *,
    config: PhaseBoundaryConfig,
    config_hash: str,
    code_sha: str,
    output_dir: str | Path,
) -> dict[str, object]:
    base = config.integration.environment
    policy = reference_policy()
    experiments: list[dict[str, object]] = []

    stable = _stable_environment(base, cycles=config.stable_cycles, practice_gain=base.practice_gain)
    arms, reference, control, effect, sign = _paired_experiment(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=41,
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
    selected = _choose_selected(reference, control, sign)
    experiments.append(
        _record_phase(
            number=41,
            focus="learning_timescale",
            question="How many cycles does identity-conditioned specialization need to reach half of its stable-regime level?",
            arms=arms,
            selected=selected,
            motivating_failure="timescale_unknown",
            observed_failure=None,
            next_focus=f"regime_period:{start_shift}",
            extras={
                "learning_timescale_cycles": tau_learning,
                "reference_effect": effect,
                "reference_sign": sign,
            },
        )
    )

    observations: list[dict[str, object]] = []
    next_shift = start_shift
    for number in range(42, 46):
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
            next_focus = f"regime_period:{next_shift}"
        else:
            next_focus = "boundary_estimate"
        experiments.append(
            _record_phase(
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
        )

    boundary_shift, theta, bracketed = _boundary_estimate(observations, tau_learning=tau_learning)
    validation_gains = (
        (config.slow_practice_gain, config.fast_practice_gain)
        if theta >= 1.0
        else (config.fast_practice_gain, config.slow_practice_gain)
    )
    validation_results: list[dict[str, object]] = []

    for pair_index, gain in enumerate(validation_gains):
        measure_number = 46 + pair_index * 2
        stable_env = _stable_environment(base, cycles=config.stable_cycles, practice_gain=gain)
        arms, reference, control, effect, sign = _paired_experiment(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            number=measure_number,
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
        experiments.append(
            _record_phase(
                number=measure_number,
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
        )

        test_number = measure_number + 1
        test_env = _test_environment(base, shift_period=predicted_shift, practice_gain=gain)
        arms, reference, control, effect, sign = _paired_experiment(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            number=test_number,
            env=test_env,
            seeds=config.integration.seeds,
            policy=policy,
        )
        theta = _adjust_theta(theta, sign)
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
        experiments.append(
            _record_phase(
                number=test_number,
                focus="scaled_boundary",
                question="Does the phase-boundary ratio predict reputation's sign after the learning rate changes?",
                arms=arms,
                selected=_choose_selected(reference, control, sign),
                motivating_failure="boundary_scaling",
                observed_failure=sign,
                next_focus="second_learning_rate" if pair_index == 0 else "adaptive_disengagement",
                extras={
                    "practice_gain": gain,
                    "learning_timescale_cycles": tau_gain,
                    "timescale_ratio": test_env.shift_period / max(tau_gain, 1.0),
                    "reference_effect": effect,
                    "reference_sign": sign,
                    "updated_boundary_ratio": theta,
                },
            )
        )

    near_shift = _clamp_shift(config, 0.75 * theta * tau_learning)
    near_env = _test_environment(base, shift_period=near_shift, practice_gain=base.practice_gain)
    near_ratio = near_env.shift_period / max(tau_learning, 1.0)
    gated = _gated_policy(policy, near_ratio, theta)
    arms, selected, control = _run_experiment(
        connection,
        config=config.integration,
        config_hash=config_hash,
        number=50,
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
    experiments.append(
        _record_phase(
            number=50,
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
    )

    replication_gain = validation_gains[-1]
    replication_tau = float(validation_results[-1]["tau_learning"])
    replication_shift = _clamp_shift(config, theta * replication_tau)
    replication_env = _test_environment(
        base,
        shift_period=replication_shift,
        practice_gain=replication_gain,
    )
    arms, reference, control, effect, sign = _paired_experiment(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=51,
        env=replication_env,
        seeds=config.replication_seeds,
        policy=chosen_policy,
        reference_label="candidate_policy",
    )
    candidate = reference
    candidate_effect = effect
    candidate_sign = sign
    experiments.append(
        _record_phase(
            number=51,
            focus="independent_replication",
            question="Does the candidate timescale policy replicate on independent seeds near the inferred boundary?",
            arms=arms,
            selected=_choose_selected(candidate, control, candidate_sign),
            motivating_failure="generalization",
            observed_failure=candidate_sign,
            next_focus="unseen_holdout",
            extras={
                "boundary_ratio": theta,
                "practice_gain": replication_gain,
                "learning_timescale_cycles": replication_tau,
                "shift_period": replication_shift,
                "candidate_effect": candidate_effect,
            },
        )
    )

    holdout_gain = base.practice_gain
    holdout_multiplier = 0.75 if candidate_sign == "positive" else 1.25
    holdout_shift = _clamp_shift(config, holdout_multiplier * theta * tau_learning)
    holdout_env = replace(
        _test_environment(base, shift_period=holdout_shift, practice_gain=holdout_gain),
        cycles=config.integration.holdout_cycles,
        shift_period=min(holdout_shift, config.integration.holdout_cycles - 1),
        candidate_count=config.integration.holdout_candidate_count,
    )
    holdout_ratio = holdout_env.shift_period / max(tau_learning, 1.0)
    holdout_policy = _gated_policy(policy, holdout_ratio, theta) if timescale_gate_selected else chosen_policy
    arms, _, control = _run_experiment(
        connection,
        config=config.integration,
        config_hash=config_hash,
        number=52,
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
    validated = (
        observed_reference_sign == predicted_reference_sign
        and bool(candidate["feasible"])
        and candidate_effect >= -config.integration.success_tolerance
        and all(bool(value) for value in candidate["invariants"].values())  # type: ignore[union-attr]
    )
    experiments.append(
        _record_phase(
            number=52,
            focus="unseen_holdout",
            question="Does the inferred timescale boundary predict reputation's sign on unseen seeds, and does the candidate policy remain feasible?",
            arms=arms,
            selected=candidate,
            motivating_failure="generalization",
            observed_failure=None if validated else "boundary_or_quality",
            next_focus=None,
            validated=validated,
            extras={
                "learning_timescale_cycles": tau_learning,
                "boundary_shift_cycles": boundary_shift,
                "boundary_ratio": theta,
                "boundary_bracketed": bracketed,
                "holdout_shift_period": holdout_env.shift_period,
                "holdout_ratio": holdout_ratio,
                "predicted_reference_sign": predicted_reference_sign,
                "observed_reference_sign": observed_reference_sign,
                "reference_effect": reference_effect,
                "candidate_effect": candidate_effect,
            },
        )
    )

    summary = {
        "campaign": config.integration.name,
        "code_sha": code_sha,
        "config_hash": config_hash,
        "experiments": experiments,
        "learning_timescale_cycles": tau_learning,
        "boundary_shift_cycles": boundary_shift,
        "boundary_ratio": theta,
        "boundary_bracketed": bracketed,
        "candidate_policy": holdout_policy.as_dict(),
        "candidate_label": holdout_policy.label,
        "validated": validated,
    }
    export_integration_campaign_artifacts(
        connection,
        config=config.integration,
        output_dir=output_dir,
        summary=summary,
    )
    return summary


def load_phase_boundary_config(path: str | Path) -> tuple[PhaseBoundaryConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    config = PhaseBoundaryConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()
