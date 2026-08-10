"""Formation, forgetting, and phase-model metrics for Experiments 053–062."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from psycopg import Connection

from .integration_campaign import IntegrationEnvironment
from .two_timescale_config import TwoTimescaleConfig

Observation = tuple[int, str, str, int]


def query_observations(connection: Connection[Any], run_id: str) -> list[Observation]:
    rows = connection.execute(
        """
        SELECT cycle, task_domain, required_skill, winner_slot
        FROM integration_campaign_outcomes
        WHERE run_id = %s
        ORDER BY cycle
        """,
        (UUID(str(run_id)),),
    ).fetchall()
    return [
        (
            int(row["cycle"]),
            str(row["task_domain"]),
            str(row["required_skill"]),
            int(row["winner_slot"]),
        )
        for row in rows
    ]


def formation_timescale_from_observations(
    observations: Sequence[Observation],
    *,
    base_success_probability: float,
    practice_gain: float,
    maximum_success_probability: float,
    target_fraction: float,
    window: int,
    persistence: int,
) -> float:
    if not observations:
        return 0.0
    practice: dict[tuple[int, str], int] = {}
    expected: list[float] = []
    for _, _, skill, winner in observations:
        practiced = practice.get((winner, skill), 0)
        expected.append(
            min(
                maximum_success_probability,
                base_success_probability + practice_gain * math.sqrt(practiced),
            )
        )
        practice[(winner, skill)] = practiced + 1
    if len(expected) < window:
        return float(len(expected))
    target = base_success_probability + target_fraction * (
        maximum_success_probability - base_success_probability
    )
    consecutive = 0
    first_endpoint = len(expected)
    for end in range(window, len(expected) + 1):
        rolling = statistics.mean(expected[end - window : end])
        if rolling >= target:
            consecutive += 1
            if consecutive == 1:
                first_endpoint = end
            if consecutive >= persistence:
                return float(first_endpoint)
        else:
            consecutive = 0
            first_endpoint = len(expected)
    return float(len(expected))


def formation_timescale(
    connection: Connection[Any],
    arm: Mapping[str, object],
    *,
    env: IntegrationEnvironment,
    config: TwoTimescaleConfig,
) -> float:
    run_ids = arm["run_ids"]
    assert isinstance(run_ids, Sequence)
    return statistics.mean(
        formation_timescale_from_observations(
            query_observations(connection, str(run_id)),
            base_success_probability=env.base_success_probability,
            practice_gain=env.practice_gain,
            maximum_success_probability=env.maximum_success_probability,
            target_fraction=config.formation_target_fraction,
            window=config.formation_window,
            persistence=config.persistence_windows,
        )
        for run_id in run_ids
    )


def forgetting_timescale_from_observations(
    observations: Sequence[Observation],
    *,
    shift_period: int,
    agents: int,
    reference_window: int,
    rolling_window: int,
    target_fraction: float,
    persistence: int,
) -> tuple[float, float, float]:
    pre = [item for item in observations if item[0] < shift_period]
    post = [item for item in observations if item[0] >= shift_period]
    if not pre or not post:
        return 0.0, 0.0, 0.0
    reference = pre[-min(reference_window, len(pre)) :]
    domain_winners: dict[str, Counter[int]] = {}
    for _, domain, _, winner in reference:
        domain_winners.setdefault(domain, Counter())[winner] += 1
    incumbents = {
        domain: min(counts, key=lambda winner: (-counts[winner], winner))
        for domain, counts in domain_winners.items()
    }

    def incumbent_share(rows: Sequence[Observation]) -> float:
        eligible = [item for item in rows if item[1] in incumbents]
        if not eligible:
            return 0.0
        return sum(item[3] == incumbents[item[1]] for item in eligible) / len(eligible)

    pre_share = incumbent_share(reference)
    chance = 1.0 / max(1, agents - 1)
    late_share = incumbent_share(post[-min(rolling_window, len(post)) :])
    if pre_share <= chance:
        return 0.0, pre_share, late_share
    threshold = chance + target_fraction * (pre_share - chance)
    if len(post) < rolling_window:
        return float(len(post)), pre_share, late_share
    consecutive = 0
    first_endpoint = len(post)
    for end in range(rolling_window, len(post) + 1):
        share = incumbent_share(post[end - rolling_window : end])
        if share <= threshold:
            consecutive += 1
            if consecutive == 1:
                first_endpoint = end
            if consecutive >= persistence:
                return float(first_endpoint), pre_share, late_share
        else:
            consecutive = 0
            first_endpoint = len(post)
    return float(len(post)), pre_share, late_share


def forgetting_metrics(
    connection: Connection[Any],
    arm: Mapping[str, object],
    *,
    env: IntegrationEnvironment,
    config: TwoTimescaleConfig,
) -> dict[str, float]:
    run_ids = arm["run_ids"]
    assert isinstance(run_ids, Sequence)
    values = [
        forgetting_timescale_from_observations(
            query_observations(connection, str(run_id)),
            shift_period=env.shift_period,
            agents=env.agents,
            reference_window=config.incumbent_reference_window,
            rolling_window=config.forgetting_window,
            target_fraction=config.forgetting_target_fraction,
            persistence=config.persistence_windows,
        )
        for run_id in run_ids
    ]
    return {
        "tau_d": statistics.mean(value[0] for value in values),
        "pre_incumbent_share": statistics.mean(value[1] for value in values),
        "late_incumbent_share": statistics.mean(value[2] for value in values),
    }


def _candidate_thresholds(values: Sequence[float]) -> list[float]:
    unique = sorted(set(float(value) for value in values))
    candidates = [1e-6]
    candidates.extend(unique)
    candidates.extend(
        (left + right) / 2
        for left, right in zip(unique, unique[1:], strict=False)
    )
    candidates.append(max(unique, default=1.0) + 1e-6)
    return sorted(set(candidates))


def fit_two_timescale_rule(points: Sequence[Mapping[str, object]]) -> dict[str, float]:
    if not points:
        raise ValueError("at least one measurement point is required")
    ratios_f = [float(point["ratio_f"]) for point in points]
    ratios_d = [float(point["ratio_d"]) for point in points]
    labels = [point["reference_sign"] == "positive" for point in points]
    best: tuple[int, float, float, float] | None = None
    for theta_f in _candidate_thresholds(ratios_f):
        for theta_d in _candidate_thresholds(ratios_d):
            predictions = [
                ratio_f >= theta_f and ratio_d >= theta_d
                for ratio_f, ratio_d in zip(ratios_f, ratios_d, strict=True)
            ]
            correct = sum(
                prediction == label
                for prediction, label in zip(predictions, labels, strict=True)
            )
            candidate = (correct, theta_f + theta_d, theta_f, theta_d)
            if best is None or candidate > best:
                best = candidate
    assert best is not None
    return {
        "theta_f": best[2],
        "theta_d": best[3],
        "accuracy": best[0] / len(points),
    }


def model_score(
    *,
    ratio_f: float,
    ratio_d: float,
    theta_f: float,
    theta_d: float,
) -> float:
    return min(
        ratio_f / max(theta_f, 1e-9),
        ratio_d / max(theta_d, 1e-9),
    )


def model_sign(score: float, *, neutral_band: float) -> str:
    if score >= 1.0 + neutral_band:
        return "positive"
    if score <= 1.0 - neutral_band:
        return "negative"
    return "neutral"


def interpolate_timescales(
    points: Sequence[Mapping[str, object]],
    gain: float,
) -> tuple[float, float]:
    ordered = sorted(points, key=lambda point: float(point["practice_gain"]))
    if gain <= float(ordered[0]["practice_gain"]):
        return float(ordered[0]["tau_f"]), float(ordered[0]["tau_d"])
    if gain >= float(ordered[-1]["practice_gain"]):
        return float(ordered[-1]["tau_f"]), float(ordered[-1]["tau_d"])
    for left, right in zip(ordered, ordered[1:], strict=False):
        left_gain = float(left["practice_gain"])
        right_gain = float(right["practice_gain"])
        if left_gain <= gain <= right_gain:
            weight = (gain - left_gain) / (right_gain - left_gain)
            tau_f = float(left["tau_f"]) + weight * (
                float(right["tau_f"]) - float(left["tau_f"])
            )
            tau_d = float(left["tau_d"]) + weight * (
                float(right["tau_d"]) - float(left["tau_d"])
            )
            return tau_f, tau_d
    raise RuntimeError("unable to interpolate timescales")


def gate_scale(
    *,
    ratio_f: float,
    ratio_d: float,
    theta_f: float,
    theta_d: float,
) -> float:
    return max(
        0.0,
        min(
            1.0,
            model_score(
                ratio_f=ratio_f,
                ratio_d=ratio_d,
                theta_f=theta_f,
                theta_d=theta_d,
            ),
        ),
    )
