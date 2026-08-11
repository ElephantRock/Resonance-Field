"""Post-hoc heterogeneity audit for the canonical Endogenous Demand 105–110 campaign.

The audit reconstructs only the seven historical seed-level control/treatment pairs and
extracts predictors exclusively from the common prefix before the first causal demand
override. It does not introduce a new seed, feedback strength, or mechanism.
"""

from __future__ import annotations

import csv
import itertools
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import Connection

from .adaptive_campaign import _mutual_information
from .endogenous_demand_campaign import run_endogenous_cell
from .endogenous_demand_config import (
    EndogenousDemandConfig,
    EndogenousDemandSpec,
    endogenous_environment,
)

_SELECTED_STRENGTH = 0.5
_CANONICAL_CAMPAIGN_SHA = "f701f829bf1783114febff0a74bcd019865fe9aa"
_EPSILON = 1e-12

_FEATURE_ORDER = (
    "common_prefix_cycles",
    "prefix_demand_entropy",
    "prefix_demand_hhi",
    "prefix_success_domain_entropy",
    "prefix_success_domain_hhi",
    "prefix_success_rate",
    "prefix_winner_hhi",
    "prefix_winner_domain_mi",
    "prefix_dominant_winner_share",
    "prefix_same_domain_winner_repeat",
    "prefix_practice_cell_hhi",
    "override_rolling_success_hhi",
    "override_rolling_success_total",
    "override_regime_age_fraction",
    "override_completed_regime_shifts",
    "prefix_next_regime_skill_alignment",
    "feedback_window_over_prefix",
)

_CANONICAL_AGGREGATES = {
    "discovery": {
        "control_incumbent": 0.046296296296296294,
        "feedback_incumbent": 0.10185185185185185,
        "control_success": 0.4444444444444444,
        "feedback_success": 0.4861111111111111,
    },
    "replication": {
        "control_incumbent": 0.1111111111111111,
        "feedback_incumbent": 0.09259259259259259,
        "control_success": 0.4305555555555556,
        "feedback_success": 0.4930555555555556,
    },
    "holdout": {
        "control_incumbent": 0.06518518518518518,
        "feedback_incumbent": 0.035555555555555556,
        "control_success": 0.4722222222222222,
        "feedback_success": 0.46825396825396826,
    },
}


def _domain_hhi(values: Sequence[int]) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    total = len(values)
    return sum((count / total) ** 2 for count in counts.values())


def _entropy(values: Sequence[int], *, categories: int) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    total = len(values)
    raw = -sum((count / total) * math.log(count / total) for count in counts.values())
    return raw / math.log(categories) if categories > 1 else 0.0


def _winner_hhi(rows: Sequence[Mapping[str, object]]) -> float:
    if not rows:
        return 0.0
    counts = Counter(int(row["winner_slot"]) for row in rows)
    total = len(rows)
    return sum((count / total) ** 2 for count in counts.values())


def _dominant_winner_share(rows: Sequence[Mapping[str, object]]) -> float:
    if not rows:
        return 0.0
    by_domain: dict[int, Counter[int]] = defaultdict(Counter)
    for row in rows:
        by_domain[int(row["domain_index"])][int(row["winner_slot"])] += 1
    return sum(max(counts.values()) for counts in by_domain.values()) / len(rows)


def _same_domain_winner_repeat(rows: Sequence[Mapping[str, object]]) -> float:
    previous: dict[int, int] = {}
    repeated: list[float] = []
    for row in rows:
        domain = int(row["domain_index"])
        winner = int(row["winner_slot"])
        if domain in previous:
            repeated.append(float(previous[domain] == winner))
        previous[domain] = winner
    return statistics.mean(repeated) if repeated else 0.0


def _practice_counts(rows: Sequence[Mapping[str, object]]) -> Counter[tuple[int, str]]:
    return Counter((int(row["winner_slot"]), str(row["required_skill"])) for row in rows)


def _practice_cell_hhi(rows: Sequence[Mapping[str, object]]) -> float:
    counts = _practice_counts(rows)
    total = sum(counts.values())
    if not total:
        return 0.0
    return sum((count / total) ** 2 for count in counts.values())


def _incumbents(rows: Sequence[Mapping[str, object]]) -> dict[int, int]:
    by_domain: dict[int, Counter[int]] = defaultdict(Counter)
    for row in rows:
        by_domain[int(row["domain_index"])][int(row["winner_slot"])] += 1
    result: dict[int, int] = {}
    for domain, counts in by_domain.items():
        high = max(counts.values())
        result[domain] = min(slot for slot, count in counts.items() if count == high)
    return result


def _next_regime_skill_alignment(
    rows: Sequence[Mapping[str, object]],
    *,
    first_override: int,
    shift_period: int,
    domains: Sequence[str],
) -> float:
    if not rows:
        return 0.0
    incumbents = _incumbents(rows)
    practice = _practice_counts(rows)
    total_by_winner = Counter()
    for (winner, _skill), count in practice.items():
        total_by_winner[winner] += count
    next_regime = first_override // shift_period + 1
    values: list[float] = []
    for domain, winner in incumbents.items():
        target_skill = domains[(domain + next_regime) % len(domains)]
        denominator = total_by_winner[winner]
        values.append(practice[(winner, target_skill)] / denominator if denominator else 0.0)
    return statistics.mean(values) if values else 0.0


def _rolling_success_features(counts: Sequence[int]) -> dict[str, float]:
    total = sum(int(value) for value in counts)
    if total <= 0:
        return {
            "override_rolling_success_hhi": 0.0,
            "override_rolling_success_total": 0.0,
        }
    shares = [int(value) / total for value in counts if int(value) > 0]
    return {
        "override_rolling_success_hhi": sum(share**2 for share in shares),
        "override_rolling_success_total": float(total),
    }


def _query_outcomes(connection: Connection[Any], run_id: str) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT cycle, regime, domain_index, required_skill, winner_slot, success, created_at
        FROM integration_campaign_outcomes
        WHERE run_id = %s
        ORDER BY cycle
        """,
        (UUID(run_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def _query_feedback(connection: Connection[Any], run_id: str) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT cycle, baseline_domain_index, generated_domain_index,
               rolling_success_counts, feedback_branch_taken
        FROM endogenous_demand_observations
        WHERE run_id = %s
        ORDER BY cycle
        """,
        (UUID(run_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def _first_override(events: Sequence[Mapping[str, object]], *, cycles: int) -> int:
    return min(
        (
            int(event["cycle"])
            for event in events
            if int(event["generated_domain_index"]) != int(event["baseline_domain_index"])
        ),
        default=cycles,
    )


def _common_prefix_exact(
    control: Sequence[Mapping[str, object]],
    feedback: Sequence[Mapping[str, object]],
    *,
    end: int,
) -> bool:
    control_by_cycle = {int(row["cycle"]): row for row in control}
    feedback_by_cycle = {int(row["cycle"]): row for row in feedback}
    fields = ("domain_index", "required_skill", "winner_slot", "success")
    for cycle in range(end):
        if cycle not in control_by_cycle or cycle not in feedback_by_cycle:
            return False
        if any(
            control_by_cycle[cycle][field] != feedback_by_cycle[cycle][field]
            for field in fields
        ):
            return False
    return True


def _prefix_features(
    control_rows: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
    *,
    first_override: int,
    cycles: int,
    shift_period: int,
    feedback_window: int,
    domains: Sequence[str],
) -> dict[str, float]:
    prefix = [row for row in control_rows if int(row["cycle"]) < first_override]
    domain_values = [int(row["domain_index"]) for row in prefix]
    successes = [row for row in prefix if bool(row["success"])]
    successful_domains = [int(row["domain_index"]) for row in successes]
    pairs = [(int(row["winner_slot"]), int(row["domain_index"])) for row in prefix]

    if first_override < len(events):
        raw_counts = events[first_override]["rolling_success_counts"]
    elif events:
        raw_counts = events[-1]["rolling_success_counts"]
    else:
        raw_counts = []
    counts = [int(value) for value in raw_counts] if isinstance(raw_counts, Sequence) else []

    result = {
        "common_prefix_cycles": float(first_override),
        "prefix_demand_entropy": _entropy(domain_values, categories=len(domains)),
        "prefix_demand_hhi": _domain_hhi(domain_values),
        "prefix_success_domain_entropy": _entropy(successful_domains, categories=len(domains)),
        "prefix_success_domain_hhi": _domain_hhi(successful_domains),
        "prefix_success_rate": len(successes) / len(prefix) if prefix else 0.0,
        "prefix_winner_hhi": _winner_hhi(prefix),
        "prefix_winner_domain_mi": _mutual_information(pairs),
        "prefix_dominant_winner_share": _dominant_winner_share(prefix),
        "prefix_same_domain_winner_repeat": _same_domain_winner_repeat(prefix),
        "prefix_practice_cell_hhi": _practice_cell_hhi(prefix),
        "override_regime_age_fraction": (
            (first_override % shift_period) / shift_period if first_override < cycles else 1.0
        ),
        "override_completed_regime_shifts": float(first_override // shift_period),
        "prefix_next_regime_skill_alignment": _next_regime_skill_alignment(
            prefix,
            first_override=first_override,
            shift_period=shift_period,
            domains=domains,
        ),
        "feedback_window_over_prefix": feedback_window / max(1, first_override),
    }
    result.update(_rolling_success_features(counts))
    return result


def _rank(values: Sequence[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    result = [0.0 for _ in values]
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average = (index + 1 + end) / 2.0
        for position in range(index, end):
            result[ordered[position][0]] = average
        index = end
    return result


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    mean_left = statistics.mean(left)
    mean_right = statistics.mean(right)
    numerator = sum(
        (x - mean_left) * (y - mean_right)
        for x, y in zip(left, right, strict=True)
    )
    left_ss = sum((x - mean_left) ** 2 for x in left)
    right_ss = sum((y - mean_right) ** 2 for y in right)
    denominator = math.sqrt(left_ss * right_ss)
    return numerator / denominator if denominator else 0.0


def _spearman(values: Sequence[float], response: Sequence[float]) -> float:
    return _pearson(_rank(values), _rank(response))


def _balanced_accuracy(actual: Sequence[bool], predicted: Sequence[bool]) -> float:
    recalls: list[float] = []
    for label in (False, True):
        indices = [index for index, value in enumerate(actual) if value is label]
        if indices:
            recalls.append(sum(predicted[index] == label for index in indices) / len(indices))
    return statistics.mean(recalls) if recalls else 0.0


def _threshold_candidates(values: Sequence[float]) -> list[float]:
    unique = sorted(set(values))
    if not unique:
        return [0.0]
    if len(unique) == 1:
        return [unique[0]]
    mids = [
        (left + right) / 2.0
        for left, right in zip(unique, unique[1:], strict=False)
    ]
    span = max(1.0, abs(unique[-1] - unique[0]))
    return [unique[0] - span, *mids, unique[-1] + span]


def _predict(values: Sequence[float], *, threshold: float, direction: str) -> list[bool]:
    if direction == "positive_if_high":
        return [value >= threshold for value in values]
    if direction == "positive_if_low":
        return [value <= threshold for value in values]
    raise ValueError(f"unsupported direction {direction}")


def _fit_threshold(values: Sequence[float], labels: Sequence[bool]) -> dict[str, object]:
    candidates: list[tuple[float, float, str, float]] = []
    for direction in ("positive_if_high", "positive_if_low"):
        for threshold in _threshold_candidates(values):
            predicted = _predict(values, threshold=threshold, direction=direction)
            accuracy = sum(
                actual == prediction
                for actual, prediction in zip(labels, predicted, strict=True)
            ) / len(labels)
            balanced = _balanced_accuracy(labels, predicted)
            candidates.append((balanced, accuracy, direction, threshold))
    balanced, accuracy, direction, threshold = max(
        candidates,
        key=lambda item: (
            item[0],
            item[1],
            item[2] == "positive_if_high",
            -abs(item[3]),
        ),
    )
    return {
        "direction": direction,
        "threshold": threshold,
        "accuracy": accuracy,
        "balanced_accuracy": balanced,
    }


def _loo_threshold(values: Sequence[float], labels: Sequence[bool]) -> dict[str, object]:
    predictions: list[bool] = []
    directions: list[str] = []
    thresholds: list[float] = []
    for held_out in range(len(values)):
        train_values = [value for index, value in enumerate(values) if index != held_out]
        train_labels = [value for index, value in enumerate(labels) if index != held_out]
        fit = _fit_threshold(train_values, train_labels)
        directions.append(str(fit["direction"]))
        thresholds.append(float(fit["threshold"]))
        predictions.append(
            _predict(
                [values[held_out]],
                threshold=float(fit["threshold"]),
                direction=str(fit["direction"]),
            )[0]
        )
    accuracy = sum(
        actual == prediction
        for actual, prediction in zip(labels, predictions, strict=True)
    ) / len(labels)
    return {
        "accuracy": accuracy,
        "balanced_accuracy": _balanced_accuracy(labels, predictions),
        "predictions": predictions,
        "directions": directions,
        "thresholds": thresholds,
    }


def _label_permutations(labels: Sequence[bool]) -> list[list[bool]]:
    positives = sum(labels)
    indices = range(len(labels))
    result: list[list[bool]] = []
    for positive_indices in itertools.combinations(indices, positives):
        selected = set(positive_indices)
        result.append([index in selected for index in indices])
    return result


def _evaluate_features(records: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    response = [float(record["delta_incumbency"]) for record in records]
    labels = [value > 0.0 for value in response]
    feature_values = {
        name: [float(record["features"][name]) for record in records]  # type: ignore[index]
        for name in _FEATURE_ORDER
    }
    evaluations: list[dict[str, object]] = []
    for name in _FEATURE_ORDER:
        values = feature_values[name]
        fit = _fit_threshold(values, labels)
        loo = _loo_threshold(values, labels)
        directions = loo["directions"]
        thresholds = loo["thresholds"]
        assert isinstance(directions, Sequence) and isinstance(thresholds, Sequence)
        evaluations.append(
            {
                "feature": name,
                "spearman_delta_incumbency": _spearman(values, response),
                "threshold": fit["threshold"],
                "direction": fit["direction"],
                "fit_accuracy": fit["accuracy"],
                "fit_balanced_accuracy": fit["balanced_accuracy"],
                "loo_accuracy": loo["accuracy"],
                "loo_balanced_accuracy": loo["balanced_accuracy"],
                "loo_direction_stable": all(
                    str(direction) == fit["direction"] for direction in directions
                ),
                "loo_threshold_min": min(float(value) for value in thresholds),
                "loo_threshold_max": max(float(value) for value in thresholds),
            }
        )

    permutations = _label_permutations(labels)
    max_scores: list[float] = []
    for permuted in permutations:
        scores = [
            float(_loo_threshold(feature_values[name], permuted)["balanced_accuracy"])
            for name in _FEATURE_ORDER
        ]
        max_scores.append(max(scores))
    for evaluation in evaluations:
        observed = float(evaluation["loo_balanced_accuracy"])
        evaluation["familywise_permutation_p"] = (
            sum(score >= observed - _EPSILON for score in max_scores) / len(max_scores)
        )
        evaluation["qualifies_phase_candidate"] = bool(
            observed >= 0.75
            and float(evaluation["loo_accuracy"]) >= 5 / 7
            and bool(evaluation["loo_direction_stable"])
            and abs(float(evaluation["spearman_delta_incumbency"])) >= 0.50
            and float(evaluation["familywise_permutation_p"]) <= 0.10
        )
    return evaluations


def _select_phase_condition(
    evaluations: Sequence[Mapping[str, object]],
) -> dict[str, object] | None:
    qualified = [item for item in evaluations if bool(item["qualifies_phase_candidate"])]
    if not qualified:
        return None
    selected = max(
        qualified,
        key=lambda item: (
            float(item["loo_balanced_accuracy"]),
            float(item["loo_accuracy"]),
            abs(float(item["spearman_delta_incumbency"])),
            -float(item["familywise_permutation_p"]),
            -_FEATURE_ORDER.index(str(item["feature"])),
        ),
    )
    return dict(selected)


def _cohort_environment(config: EndogenousDemandConfig, cohort: str):
    if cohort != "holdout":
        return endogenous_environment(config)
    return endogenous_environment(
        config,
        cycles=config.integration.holdout_cycles,
        shift_period=config.integration.holdout_shift_period,
        candidate_count=config.integration.holdout_candidate_count,
    )


def _historical_cohorts(
    config: EndogenousDemandConfig,
) -> tuple[tuple[str, int, tuple[int, ...]], ...]:
    return (
        ("discovery", 105, tuple(config.integration.seeds)),
        ("replication", 109, tuple(config.replication_seeds)),
        ("holdout", 110, tuple(config.integration.holdout_seeds)),
    )


def _reconstruct_pair(
    connection: Connection[Any],
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
    cohort: str,
    experiment_number: int,
    seed: int,
) -> dict[str, object]:
    environment = _cohort_environment(config, cohort)
    control = run_endogenous_cell(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=_CANONICAL_CAMPAIGN_SHA,
        experiment_number=experiment_number,
        label="exogenous_control",
        spec=EndogenousDemandSpec(),
        seed=seed,
        environment=environment,
    )
    feedback = run_endogenous_cell(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=_CANONICAL_CAMPAIGN_SHA,
        experiment_number=experiment_number,
        label="feedback_0.5" if cohort == "discovery" else "selected_feedback",
        spec=EndogenousDemandSpec(mode="closed_loop", strength=_SELECTED_STRENGTH),
        seed=seed,
        environment=environment,
    )
    control_rows = _query_outcomes(connection, str(control["run_id"]))
    feedback_rows = _query_outcomes(connection, str(feedback["run_id"]))
    events = _query_feedback(connection, str(feedback["run_id"]))
    first_override = _first_override(events, cycles=environment.cycles)
    prefix_exact = _common_prefix_exact(control_rows, feedback_rows, end=first_override)

    control_metrics = control["metrics"]
    feedback_metrics = feedback["metrics"]
    assert isinstance(control_metrics, Mapping) and isinstance(feedback_metrics, Mapping)
    features = _prefix_features(
        control_rows,
        events,
        first_override=first_override,
        cycles=environment.cycles,
        shift_period=environment.shift_period,
        feedback_window=config.feedback_window,
        domains=environment.domains,
    )
    control_invariants = control["invariants"]
    feedback_invariants = feedback["invariants"]
    assert isinstance(control_invariants, Mapping) and isinstance(feedback_invariants, Mapping)
    return {
        "cohort": cohort,
        "experiment_number": experiment_number,
        "seed": seed,
        "control_run_id": control["run_id"],
        "feedback_run_id": feedback["run_id"],
        "common_prefix_exact": prefix_exact,
        "all_cell_invariants": all(bool(value) for value in control_invariants.values())
        and all(bool(value) for value in feedback_invariants.values()),
        "first_override_cycle": first_override,
        "control_incumbency": float(control_metrics["early_incumbent_share"]),
        "feedback_incumbency": float(feedback_metrics["early_incumbent_share"]),
        "delta_incumbency": float(feedback_metrics["early_incumbent_share"])
        - float(control_metrics["early_incumbent_share"]),
        "control_success": float(control_metrics["success_rate"]),
        "feedback_success": float(feedback_metrics["success_rate"]),
        "delta_success": float(feedback_metrics["success_rate"])
        - float(control_metrics["success_rate"]),
        "features": features,
    }


def _canonical_reconstruction_check(
    records: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    checks: dict[str, bool] = {}
    details: dict[str, dict[str, float]] = {}
    for cohort, expected in _CANONICAL_AGGREGATES.items():
        subset = [record for record in records if record["cohort"] == cohort]
        observed = {
            "control_incumbent": statistics.mean(
                float(row["control_incumbency"]) for row in subset
            ),
            "feedback_incumbent": statistics.mean(
                float(row["feedback_incumbency"]) for row in subset
            ),
            "control_success": statistics.mean(float(row["control_success"]) for row in subset),
            "feedback_success": statistics.mean(float(row["feedback_success"]) for row in subset),
        }
        details[cohort] = observed
        checks[cohort] = all(
            abs(observed[key] - expected[key]) <= _EPSILON for key in expected
        )
    return {
        "checks": checks,
        "observed": details,
        "all_match": all(checks.values()),
    }


def run_heterogeneity_audit(
    connection: Connection[Any],
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for cohort, experiment_number, seeds in _historical_cohorts(config):
        for seed in seeds:
            records.append(
                _reconstruct_pair(
                    connection,
                    config=config,
                    config_hash=config_hash,
                    cohort=cohort,
                    experiment_number=experiment_number,
                    seed=seed,
                )
            )

    reconstruction = _canonical_reconstruction_check(records)
    prefix_exact = all(bool(record["common_prefix_exact"]) for record in records)
    invariants = all(bool(record["all_cell_invariants"]) for record in records)
    if not bool(reconstruction["all_match"]) or not prefix_exact or not invariants:
        raise RuntimeError("heterogeneity reconstruction failed canonical validity checks")

    evaluations = _evaluate_features(records)
    selected = _select_phase_condition(evaluations)
    if selected is None:
        conclusion = "no phase predictor localized"
        future_prediction = None
    else:
        conclusion = "candidate phase condition localized"
        positive_side = (
            "at or above the threshold"
            if selected["direction"] == "positive_if_high"
            else "at or below the threshold"
        )
        future_prediction = (
            f"When {selected['feature']} is {positive_side} "
            f"{float(selected['threshold']):.6g}, aligned endogenous feedback λ=0.5 is "
            "predicted to increase logical incumbency; crossing to the opposite side is "
            "predicted to reverse or eliminate that effect."
        )

    return {
        "audit": "endogenous-demand-heterogeneity-105-110",
        "code_sha": code_sha,
        "campaign_code_sha": _CANONICAL_CAMPAIGN_SHA,
        "config_hash": config_hash,
        "selected_feedback_strength": _SELECTED_STRENGTH,
        "historical_seed_count": len(records),
        "feature_order": list(_FEATURE_ORDER),
        "selection_rule": {
            "minimum_loo_balanced_accuracy": 0.75,
            "minimum_loo_accuracy": 5 / 7,
            "minimum_absolute_spearman": 0.50,
            "maximum_familywise_permutation_p": 0.10,
            "loo_direction_must_be_stable": True,
            "no_composite_model": True,
        },
        "reconstruction": reconstruction,
        "common_prefix_exact": prefix_exact,
        "all_cell_invariants": invariants,
        "records": records,
        "feature_evaluations": evaluations,
        "phase_condition": selected,
        "conclusion": conclusion,
        "future_prediction": future_prediction,
        "validated": False,
        "interpretation": (
            "The audit is hypothesis-generating because all seven seeds were used to localize "
            "the candidate. Any phase condition requires prospective validation on unseen "
            "seeds before it can be treated as a discovery."
        ),
    }


def render_audit_markdown(audit: Mapping[str, object]) -> str:
    records = audit["records"]
    evaluations = audit["feature_evaluations"]
    reconstruction = audit["reconstruction"]
    assert isinstance(records, Sequence)
    assert isinstance(evaluations, Sequence)
    assert isinstance(reconstruction, Mapping)
    lines = [
        "<!-- endogenous-demand-heterogeneity-105-110:audit -->",
        "## Heterogeneity Audit — 105–110 Sign Flip",
        "",
        f"- Audit implementation commit: `{audit['code_sha']}`",
        f"- Reconstructed canonical campaign commit: `{audit['campaign_code_sha']}`",
        f"- Canonical config hash: `{audit['config_hash']}`",
        f"- Historical seeds reconstructed: **{audit['historical_seed_count']}**",
        f"- Canonical aggregate reproduction: **{reconstruction['all_match']}**",
        f"- Common-prefix exactness: **{audit['common_prefix_exact']}**",
        f"- All cell invariants: **{audit['all_cell_invariants']}**",
        f"- Conclusion: **{audit['conclusion']}**",
        "",
        "### Seed-level sign table",
        "",
        "| Cohort | Seed | First override | Control I | Feedback I | ΔI | Sign |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for record in records:
        assert isinstance(record, Mapping)
        delta = float(record["delta_incumbency"])
        sign = "lock-in" if delta > 0 else "plasticity" if delta < 0 else "neutral"
        lines.append(
            f"| {record['cohort']} | {record['seed']} | {record['first_override_cycle']} | "
            f"{float(record['control_incumbency']):.6f} | "
            f"{float(record['feedback_incumbency']):.6f} | {delta:+.6f} | {sign} |"
        )

    lines.extend(
        [
            "",
            "### Pre-divergence candidate features",
            "",
            "| Feature | Spearman ρ | LOO accuracy | LOO balanced | FWER p | Stable | Qualifies |",
            "|---|---:|---:|---:|---:|---|---|",
        ]
    )
    ranked = sorted(
        evaluations,
        key=lambda item: (
            float(item["loo_balanced_accuracy"]),
            abs(float(item["spearman_delta_incumbency"])),
        ),
        reverse=True,
    )
    for item in ranked:
        assert isinstance(item, Mapping)
        lines.append(
            f"| `{item['feature']}` | {float(item['spearman_delta_incumbency']):+.3f} | "
            f"{float(item['loo_accuracy']):.3f} | "
            f"{float(item['loo_balanced_accuracy']):.3f} | "
            f"{float(item['familywise_permutation_p']):.3f} | "
            f"{item['loo_direction_stable']} | {item['qualifies_phase_candidate']} |"
        )

    phase = audit.get("phase_condition")
    lines.extend(["", "### Phase-condition decision", ""])
    if isinstance(phase, Mapping):
        lines.extend(
            [
                f"Candidate variable: **`{phase['feature']}`**",
                "",
                f"- Frozen threshold: **{float(phase['threshold']):.6g}**",
                f"- Lock-in side: **{phase['direction']}**",
                f"- LOO balanced accuracy: **{float(phase['loo_balanced_accuracy']):.3f}**",
                f"- Family-wise permutation p: **{float(phase['familywise_permutation_p']):.3f}**",
                f"- Future prediction: {audit['future_prediction']}",
                "",
                (
                    "This is a candidate phase condition, not a validated discovery. It was "
                    "localized on the seven historical seeds and must be tested prospectively."
                ),
            ]
        )
    else:
        lines.append(
            "**No pre-divergence scalar phase predictor passed the frozen localization rule.** "
            "The sign flip remains real, but this audit cannot compress it into one observable "
            "phase condition without overfitting."
        )
    lines.extend(
        [
            "",
            "### Interpretation boundary",
            "",
            str(audit["interpretation"]),
            "No new seed, λ value, or treatment family was introduced in this audit.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_boundary_update(audit: Mapping[str, object]) -> str:
    phase = audit.get("phase_condition")
    lines = [
        "<!-- external-boundary:heterogeneity-audit -->",
        "## Heterogeneity-audit dependency resolution",
        "",
        f"Audit source: #41; conclusion: **{audit['conclusion']}**.",
        "",
    ]
    if isinstance(phase, Mapping):
        lines.extend(
            [
                f"Frozen candidate phase variable: **`{phase['feature']}`**",
                f"Frozen threshold: **{float(phase['threshold']):.6g}**",
                f"Lock-in classification direction: **{phase['direction']}**",
                f"LOO balanced accuracy: **{float(phase['loo_balanced_accuracy']):.3f}**",
                f"Family-wise permutation p: **{float(phase['familywise_permutation_p']):.3f}**",
                "",
                f"Prospective boundary prediction: {audit['future_prediction']}",
                "",
                (
                    "This threshold is frozen for future validation but remains unvalidated. "
                    "No 111+ experiment is launched by this update."
                ),
            ]
        )
    else:
        lines.extend(
            [
                (
                    "No observable pre-divergence scalar phase condition was localized under "
                    "the frozen audit rule."
                ),
                (
                    "The external-boundary design therefore remains architecture-only; "
                    "Experiment 111+ must not launch until a non-post-treatment phase observable "
                    "is specified and preregistered."
                ),
            ]
        )
    return "\n".join(lines) + "\n"


def write_audit_artifacts(destination: str | Path, audit: Mapping[str, object]) -> None:
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    (output / "heterogeneity-audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True, default=str)
    )
    records = audit["records"]
    assert isinstance(records, Sequence)
    feature_names = list(audit["feature_order"])
    with (output / "seed-level.csv").open("w", newline="") as handle:
        fieldnames = [
            "cohort",
            "seed",
            "first_override_cycle",
            "control_incumbency",
            "feedback_incumbency",
            "delta_incumbency",
            "control_success",
            "feedback_success",
            "delta_success",
            *feature_names,
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            assert isinstance(record, Mapping)
            features = record["features"]
            assert isinstance(features, Mapping)
            writer.writerow(
                {
                    **{key: record[key] for key in fieldnames if key in record},
                    **{name: features[name] for name in feature_names},
                }
            )
    (output / "audit-report.md").write_text(render_audit_markdown(audit))
    (output / "boundary-update.md").write_text(render_boundary_update(audit))


__all__ = [
    "run_heterogeneity_audit",
    "write_audit_artifacts",
]
