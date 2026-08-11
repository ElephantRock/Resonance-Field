"""Delayed-onset phase-observability machinery for Experiments 111–116."""

from __future__ import annotations

import itertools
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from .adaptive_campaign import _mutual_information
from .delayed_phase_config import DelayedPhaseConfig, PhaseEnvironment
from .endogenous_demand_campaign import run_endogenous_cell
from .endogenous_demand_config import (
    EndogenousDemandConfig,
    EndogenousDemandSpec,
    endogenous_environment,
    load_endogenous_demand_config,
)
from .endogenous_demand_heterogeneity import (
    _balanced_accuracy,
    _fit_threshold,
    _loo_threshold,
    _predict,
    _spearman,
)

_EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class DelayedFeedbackSpec:
    """Frozen aligned feedback that activates only after a preregistered burn-in."""

    activation_cycle: int
    strength: float = 0.5
    mode: str = "closed_loop"

    def __post_init__(self) -> None:
        if self.activation_cycle <= 0:
            raise ValueError("activation_cycle must be positive")
        if self.strength != 0.5 or self.mode != "closed_loop":
            raise ValueError("delayed feedback is frozen to aligned closed-loop λ=0.5")

    def strength_for_cycle(self, cycle: int, cycles: int) -> float:
        del cycles
        return 0.0 if cycle < self.activation_cycle else self.strength

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "strength": self.strength,
            "activation_cycle": self.activation_cycle,
            "phase_strengths": [],
        }


def load_canonical_endogenous_config(protocol: DelayedPhaseConfig) -> EndogenousDemandConfig:
    base, _ = load_endogenous_demand_config(protocol.canonical_endogenous_config)
    integration = replace(
        base.integration,
        name=protocol.name,
        success_tolerance=protocol.success_tolerance,
    )
    return replace(
        base,
        integration=integration,
        knowledge_tolerance=protocol.knowledge_tolerance,
    )


def phase_environment(base: EndogenousDemandConfig, spec: PhaseEnvironment):
    return endogenous_environment(
        base,
        cycles=spec.cycles,
        shift_period=spec.shift_period,
        candidate_count=spec.candidate_count,
    )


def _query_outcomes(connection: Connection[Any], run_id: str) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT cycle, regime, task_domain, domain_index, required_skill,
               winner_slot, success, recorded_positive, reputation_score,
               winning_price, task_budget
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
               feedback_strength, rolling_success_counts, feedback_branch_taken,
               generated_domain_source
        FROM endogenous_demand_observations
        WHERE run_id = %s
        ORDER BY cycle
        """,
        (UUID(run_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def _domain_hhi(values: Sequence[int]) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    total = len(values)
    return sum((count / total) ** 2 for count in counts.values())


def _practice_counts(rows: Sequence[Mapping[str, object]]) -> Counter[tuple[int, str]]:
    return Counter((int(row["winner_slot"]), str(row["required_skill"])) for row in rows)


def _practice_hhi(rows: Sequence[Mapping[str, object]]) -> float:
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


def _incumbent_share(rows: Sequence[Mapping[str, object]]) -> float:
    by_domain: dict[int, Counter[int]] = defaultdict(Counter)
    for row in rows:
        by_domain[int(row["domain_index"])][int(row["winner_slot"])] += 1
    shares = [max(counts.values()) / sum(counts.values()) for counts in by_domain.values() if counts]
    return statistics.mean(shares) if shares else 0.0


def _activation_alignment(
    all_prefix: Sequence[Mapping[str, object]],
    previous_regime: Sequence[Mapping[str, object]],
    *,
    activation_regime: int,
    domains: Sequence[str],
) -> float:
    incumbents = _incumbents(previous_regime)
    practice = _practice_counts(all_prefix)
    totals_by_skill = Counter()
    for (_slot, skill), count in practice.items():
        totals_by_skill[skill] += count
    values: list[float] = []
    for domain, slot in incumbents.items():
        skill = domains[(domain + activation_regime) % len(domains)]
        denominator = totals_by_skill[skill]
        if denominator:
            values.append(practice[(slot, skill)] / denominator)
    return statistics.mean(values) if values else 0.0


def state_features(
    rows: Sequence[Mapping[str, object]],
    *,
    activation_cycle: int,
    shift_period: int,
    domains: Sequence[str],
) -> dict[str, float]:
    prefix = [row for row in rows if int(row["cycle"]) < activation_cycle]
    previous = [
        row
        for row in prefix
        if activation_cycle - shift_period <= int(row["cycle"]) < activation_cycle
    ]
    pairs = [(int(row["winner_slot"]), int(row["domain_index"])) for row in previous]
    normalized_mi = _mutual_information(pairs) / math.log(len(domains)) if len(domains) > 1 else 0.0
    success_domains = [int(row["domain_index"]) for row in previous if bool(row["success"])]
    return {
        "winner_domain_mi": normalized_mi,
        "success_domain_hhi": _domain_hhi(success_domains),
        "practice_concentration": _practice_hhi(prefix),
        "incumbent_share": _incumbent_share(previous),
        "activation_regime_alignment": _activation_alignment(
            prefix,
            previous,
            activation_regime=activation_cycle // shift_period,
            domains=domains,
        ),
    }


def _normalized_prefix(
    rows: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
    *,
    activation_cycle: int,
) -> tuple[tuple[object, ...], ...]:
    by_cycle = {int(event["cycle"]): event for event in events}
    result: list[tuple[object, ...]] = []
    fields = (
        "regime",
        "task_domain",
        "domain_index",
        "required_skill",
        "winner_slot",
        "success",
        "recorded_positive",
        "reputation_score",
        "winning_price",
        "task_budget",
    )
    for row in rows:
        cycle = int(row["cycle"])
        if cycle >= activation_cycle:
            break
        event = by_cycle[cycle]
        rolling = event["rolling_success_counts"]
        rolling_tuple = tuple(int(value) for value in rolling) if isinstance(rolling, Sequence) else ()
        result.append(
            (
                cycle,
                *(row[field] for field in fields),
                event["baseline_domain_index"],
                event["generated_domain_index"],
                float(event["feedback_strength"]),
                rolling_tuple,
                bool(event["feedback_branch_taken"]),
            )
        )
    return tuple(result)


def preactivation_exact(
    control_rows: Sequence[Mapping[str, object]],
    treatment_rows: Sequence[Mapping[str, object]],
    control_events: Sequence[Mapping[str, object]],
    treatment_events: Sequence[Mapping[str, object]],
    *,
    activation_cycle: int,
) -> bool:
    return _normalized_prefix(
        control_rows, control_events, activation_cycle=activation_cycle
    ) == _normalized_prefix(
        treatment_rows, treatment_events, activation_cycle=activation_cycle
    )


def post_activation_incumbency(
    rows: Sequence[Mapping[str, object]],
    *,
    activation_cycle: int,
    shift_period: int,
    cycles: int,
) -> tuple[float, list[float]]:
    values: list[float] = []
    for shift in range(activation_cycle, cycles, shift_period):
        if len(values) >= 4 or shift + shift_period > cycles:
            break
        before = [
            row
            for row in rows
            if shift - shift_period <= int(row["cycle"]) < shift
        ]
        after = [row for row in rows if shift <= int(row["cycle"]) < shift + shift_period]
        if not before or not after:
            continue
        incumbents = _incumbents(before)
        share = sum(
            incumbents.get(int(row["domain_index"])) == int(row["winner_slot"])
            for row in after
        ) / len(after)
        values.append(share)
    if len(values) != 4:
        raise RuntimeError(f"expected four post-activation regime transitions, observed {len(values)}")
    return statistics.mean(values), values


def _cell_metrics(cell: Mapping[str, object]) -> Mapping[str, object]:
    metrics = cell["metrics"]
    assert isinstance(metrics, Mapping)
    return metrics


def _cell_invariants(cell: Mapping[str, object]) -> Mapping[str, object]:
    invariants = cell["invariants"]
    assert isinstance(invariants, Mapping)
    return invariants


def _persist_pair(connection: Connection[Any], record: Mapping[str, object]) -> None:
    features = record["features"]
    assert isinstance(features, Mapping)
    with connection.transaction():
        connection.execute(
            """
            INSERT INTO phase_observability_states (
                experiment_number, cohort, seed, activation_cycle,
                control_run_id, treatment_run_id, state_features,
                preactivation_exact, control_post_incumbency,
                treatment_post_incumbency, delta_incumbency,
                success_effect, knowledge_effect, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, NOW()
            )
            """,
            (
                record["experiment_number"],
                record["cohort"],
                record["seed"],
                record["activation_cycle"],
                UUID(str(record["control_run_id"])),
                UUID(str(record["treatment_run_id"])),
                Jsonb(dict(features)),
                record["preactivation_exact"],
                record.get("control_post_incumbency"),
                record.get("treatment_post_incumbency"),
                record.get("delta_incumbency"),
                record.get("success_effect"),
                record.get("knowledge_effect"),
            ),
        )


def run_delayed_pair(
    connection: Connection[Any],
    *,
    protocol: DelayedPhaseConfig,
    base: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    cohort: str,
    seed: int,
    environment_spec: PhaseEnvironment,
    analyze_post: bool = True,
) -> dict[str, object]:
    env = phase_environment(base, environment_spec)
    control = run_endogenous_cell(
        connection,
        config=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=experiment_number,
        label=f"{cohort}_control",
        spec=EndogenousDemandSpec(),
        seed=seed,
        environment=env,
    )
    delayed = run_endogenous_cell(
        connection,
        config=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=experiment_number,
        label=f"{cohort}_delayed_feedback",
        spec=DelayedFeedbackSpec(activation_cycle=environment_spec.burn_in_cycles),  # type: ignore[arg-type]
        seed=seed,
        environment=env,
    )
    control_rows = _query_outcomes(connection, str(control["run_id"]))
    delayed_rows = _query_outcomes(connection, str(delayed["run_id"]))
    control_events = _query_feedback(connection, str(control["run_id"]))
    delayed_events = _query_feedback(connection, str(delayed["run_id"]))
    activation = environment_spec.burn_in_cycles
    exact = preactivation_exact(
        control_rows,
        delayed_rows,
        control_events,
        delayed_events,
        activation_cycle=activation,
    )
    control_features = state_features(
        control_rows,
        activation_cycle=activation,
        shift_period=environment_spec.shift_period,
        domains=env.domains,
    )
    delayed_features = state_features(
        delayed_rows,
        activation_cycle=activation,
        shift_period=environment_spec.shift_period,
        domains=env.domains,
    )
    features_exact = all(
        abs(control_features[name] - delayed_features[name]) <= _EPSILON
        for name in protocol.state_features
    )
    invariants = (
        all(bool(value) for value in _cell_invariants(control).values())
        and all(bool(value) for value in _cell_invariants(delayed).values())
    )
    record: dict[str, object] = {
        "experiment_number": experiment_number,
        "cohort": cohort,
        "seed": seed,
        "activation_cycle": activation,
        "control_run_id": control["run_id"],
        "treatment_run_id": delayed["run_id"],
        "preactivation_exact": exact,
        "state_features_exact": features_exact,
        "all_cell_invariants": invariants,
        "features": control_features,
    }
    if analyze_post:
        control_i, control_by_shift = post_activation_incumbency(
            control_rows,
            activation_cycle=activation,
            shift_period=environment_spec.shift_period,
            cycles=environment_spec.cycles,
        )
        delayed_i, delayed_by_shift = post_activation_incumbency(
            delayed_rows,
            activation_cycle=activation,
            shift_period=environment_spec.shift_period,
            cycles=environment_spec.cycles,
        )
        control_metrics = _cell_metrics(control)
        delayed_metrics = _cell_metrics(delayed)
        knowledge_key = "late_public_knowledge_coverage"
        record.update(
            {
                "control_post_incumbency": control_i,
                "treatment_post_incumbency": delayed_i,
                "control_post_by_shift": control_by_shift,
                "treatment_post_by_shift": delayed_by_shift,
                "delta_incumbency": delayed_i - control_i,
                "control_success": float(control_metrics["success_rate"]),
                "treatment_success": float(delayed_metrics["success_rate"]),
                "success_effect": float(delayed_metrics["success_rate"])
                - float(control_metrics["success_rate"]),
                "control_knowledge": float(control_metrics[knowledge_key]),
                "treatment_knowledge": float(delayed_metrics[knowledge_key]),
                "knowledge_effect": float(delayed_metrics[knowledge_key])
                - float(control_metrics[knowledge_key]),
                "feedback_override_rate": float(delayed_metrics["feedback_override_rate"]),
            }
        )
    _persist_pair(connection, record)
    return record


def run_cohort(
    connection: Connection[Any],
    *,
    protocol: DelayedPhaseConfig,
    base: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    cohort: str,
    seeds: Sequence[int],
    environment_spec: PhaseEnvironment,
    analyze_post: bool = True,
) -> list[dict[str, object]]:
    return [
        run_delayed_pair(
            connection,
            protocol=protocol,
            base=base,
            config_hash=config_hash,
            code_sha=code_sha,
            experiment_number=experiment_number,
            cohort=cohort,
            seed=seed,
            environment_spec=environment_spec,
            analyze_post=analyze_post,
        )
        for seed in seeds
    ]


def cohort_quality(records: Sequence[Mapping[str, object]], protocol: DelayedPhaseConfig) -> dict[str, object]:
    success_effect = statistics.mean(float(record["success_effect"]) for record in records)
    knowledge_effect = statistics.mean(float(record["knowledge_effect"]) for record in records)
    integrity = all(
        bool(record["preactivation_exact"])
        and bool(record["state_features_exact"])
        and bool(record["all_cell_invariants"])
        for record in records
    )
    return {
        "success_effect": success_effect,
        "knowledge_effect": knowledge_effect,
        "integrity": integrity,
        "quality_gate": integrity
        and success_effect >= -protocol.success_tolerance
        and knowledge_effect >= -protocol.knowledge_tolerance,
    }


def sign_heterogeneity(records: Sequence[Mapping[str, object]], protocol: DelayedPhaseConfig) -> dict[str, object]:
    deltas = [float(record["delta_incumbency"]) for record in records]
    positive = sum(value > _EPSILON for value in deltas)
    negative = sum(value < -_EPSILON for value in deltas)
    neutral = len(deltas) - positive - negative
    return {
        "positive_signs": positive,
        "negative_signs": negative,
        "neutral_signs": neutral,
        "delta_min": min(deltas),
        "delta_max": max(deltas),
        "delta_mean": statistics.mean(deltas),
        "heterogeneity_gate": positive >= protocol.minimum_positive_signs
        and negative >= protocol.minimum_negative_signs,
    }


def _label_permutations(labels: Sequence[bool]) -> list[list[bool]]:
    positives = sum(labels)
    indices = range(len(labels))
    permutations: list[list[bool]] = []
    for positive_indices in itertools.combinations(indices, positives):
        selected = set(positive_indices)
        permutations.append([index in selected for index in indices])
    return permutations


def evaluate_discovery_features(
    records: Sequence[Mapping[str, object]], protocol: DelayedPhaseConfig
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    response = [float(record["delta_incumbency"]) for record in records]
    labels = [value > 0.0 for value in response]
    values_by_feature = {
        feature: [float(record["features"][feature]) for record in records]  # type: ignore[index]
        for feature in protocol.state_features
    }
    evaluations: list[dict[str, object]] = []
    for feature in protocol.state_features:
        values = values_by_feature[feature]
        fit = _fit_threshold(values, labels)
        loo = _loo_threshold(values, labels)
        directions = list(loo["directions"])  # type: ignore[arg-type]
        evaluations.append(
            {
                "feature": feature,
                "spearman_delta_incumbency": _spearman(values, response),
                "threshold": float(fit["threshold"]),
                "direction": str(fit["direction"]),
                "fit_accuracy": float(fit["accuracy"]),
                "fit_balanced_accuracy": float(fit["balanced_accuracy"]),
                "loo_accuracy": float(loo["accuracy"]),
                "loo_balanced_accuracy": float(loo["balanced_accuracy"]),
                "loo_direction_stable": all(str(value) == str(fit["direction"]) for value in directions),
            }
        )

    permutations = _label_permutations(labels)
    max_scores = [
        max(
            float(_loo_threshold(values_by_feature[feature], permuted)["balanced_accuracy"])
            for feature in protocol.state_features
        )
        for permuted in permutations
    ]
    for evaluation in evaluations:
        observed = float(evaluation["loo_balanced_accuracy"])
        p_value = sum(score >= observed - _EPSILON for score in max_scores) / len(max_scores)
        evaluation["familywise_permutation_p"] = p_value
        evaluation["qualifies"] = (
            observed >= protocol.minimum_loo_balanced_accuracy
            and float(evaluation["loo_accuracy"]) >= protocol.minimum_loo_accuracy
            and bool(evaluation["loo_direction_stable"])
            and abs(float(evaluation["spearman_delta_incumbency"])) >= protocol.minimum_abs_spearman
            and p_value <= protocol.maximum_familywise_p
        )
    qualified = [item for item in evaluations if bool(item["qualifies"])]
    if not qualified:
        return evaluations, None
    selected = max(
        qualified,
        key=lambda item: (
            float(item["loo_balanced_accuracy"]),
            float(item["loo_accuracy"]),
            abs(float(item["spearman_delta_incumbency"])),
            -float(item["familywise_permutation_p"]),
            -protocol.state_features.index(str(item["feature"])),
        ),
    )
    return evaluations, dict(selected)


def validate_classifier(
    records: Sequence[Mapping[str, object]],
    classifier: Mapping[str, object] | None,
    protocol: DelayedPhaseConfig,
) -> dict[str, object]:
    if classifier is None:
        return {
            "classifier_available": False,
            "accuracy": 0.0,
            "balanced_accuracy": 0.0,
            "directional_separation": False,
            "validation_gate": False,
        }
    feature = str(classifier["feature"])
    threshold = float(classifier["threshold"])
    direction = str(classifier["direction"])
    values = [float(record["features"][feature]) for record in records]  # type: ignore[index]
    actual = [float(record["delta_incumbency"]) > 0.0 for record in records]
    predicted = _predict(values, threshold=threshold, direction=direction)
    accuracy = sum(a == p for a, p in zip(actual, predicted, strict=True)) / len(actual)
    balanced = _balanced_accuracy(actual, predicted)
    positive_deltas = [
        float(record["delta_incumbency"])
        for record, label in zip(records, predicted, strict=True)
        if label
    ]
    negative_deltas = [
        float(record["delta_incumbency"])
        for record, label in zip(records, predicted, strict=True)
        if not label
    ]
    separation = bool(positive_deltas and negative_deltas) and (
        statistics.mean(positive_deltas) > statistics.mean(negative_deltas)
    )
    quality = cohort_quality(records, protocol)
    return {
        "classifier_available": True,
        "feature": feature,
        "threshold": threshold,
        "direction": direction,
        "accuracy": accuracy,
        "balanced_accuracy": balanced,
        "predicted_lock_in_count": sum(predicted),
        "observed_lock_in_count": sum(actual),
        "predicted_lock_in_mean_delta": statistics.mean(positive_deltas) if positive_deltas else None,
        "predicted_plasticity_mean_delta": statistics.mean(negative_deltas) if negative_deltas else None,
        "directional_separation": separation,
        **quality,
        "validation_gate": (
            accuracy >= protocol.minimum_validation_accuracy
            and balanced >= protocol.minimum_validation_balanced_accuracy
            and separation
            and bool(quality["quality_gate"])
        ),
    }


__all__ = [
    "DelayedFeedbackSpec",
    "cohort_quality",
    "evaluate_discovery_features",
    "load_canonical_endogenous_config",
    "phase_environment",
    "post_activation_incumbency",
    "preactivation_exact",
    "run_cohort",
    "run_delayed_pair",
    "sign_heterogeneity",
    "state_features",
    "validate_classifier",
]
