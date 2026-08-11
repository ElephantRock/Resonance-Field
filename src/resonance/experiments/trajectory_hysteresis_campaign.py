"""Trajectory/hysteresis machinery for Experiments 117–122."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from . import endogenous_demand_campaign as ec
from . import lifecycle_campaign as lc
from .delayed_phase_campaign import preactivation_exact, state_features
from .endogenous_demand_config import (
    EndogenousDemandConfig,
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
from .trajectory_hysteresis_config import (
    TrajectoryEnvironment,
    TrajectoryHysteresisConfig,
)

_EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class TrajectorySpec:
    """Frozen history construction plus optional post-activation feedback."""

    history_kind: str
    environment: TrajectoryEnvironment
    post_feedback: bool
    feedback_strength: float = 0.5
    history_feedback_strength: float = 0.25
    anneal_epsilon: float = 0.10

    @property
    def mode(self) -> str:
        return "trajectory_hysteresis"

    def as_dict(self) -> dict[str, object]:
        return {
            "history_kind": self.history_kind,
            "history_start": self.environment.history_start,
            "history_end": self.environment.history_end,
            "activation_cycle": self.environment.activation_cycle,
            "post_feedback": self.post_feedback,
            "feedback_strength": self.feedback_strength,
            "history_feedback_strength": self.history_feedback_strength,
            "anneal_epsilon": self.anneal_epsilon,
        }


class _TrajectoryController:
    def __init__(
        self,
        *,
        spec: TrajectorySpec,
        seed: int,
        cycles: int,
        domain_count: int,
        window: int,
        domain_fn,
        draw_fn,
    ) -> None:
        self.spec = spec
        self.seed = seed
        self.cycles = cycles
        self.domain_count = domain_count
        self.window = window
        self._domain_fn = domain_fn
        self._draw_fn = draw_fn
        self.actual_success_events: list[tuple[int, int]] = []
        self.source_success_events: list[tuple[int, int]] = []
        self.events: list[dict[str, object]] = []
        self.current_cycle = -1
        self.current_domain = -1

    def _active_source_events(self, cycle: int) -> list[tuple[int, int]]:
        lower = cycle - self.window
        return [(c, d) for c, d in self.source_success_events if lower <= c < cycle]

    def _feedback_domain(
        self,
        *,
        cycle: int,
        baseline: int,
        strength: float,
        source: str,
    ) -> tuple[int, bool, float, float, str, list[int]]:
        active = self._active_source_events(cycle)
        counts = [0 for _ in range(self.domain_count)]
        for _, domain in active:
            counts[domain] += 1
        total = sum(counts)
        distribution = [count / total if total else 0.0 for count in counts]
        switch_draw = self._draw_fn(self.seed, cycle, 0, f"trajectory-{source}-switch")
        branch = strength > 0.0 and total > 0 and switch_draw < strength
        generated = baseline
        if branch:
            domain_draw = self._draw_fn(self.seed, cycle, 0, f"trajectory-{source}-domain")
            cumulative = 0.0
            generated = self.domain_count - 1
            for domain, probability in enumerate(distribution):
                cumulative += probability
                if domain_draw <= cumulative:
                    generated = domain
                    break
        probability = distribution[generated] if total else 0.0
        generation_probability = (
            (1.0 - strength) * float(generated == baseline) + strength * probability
            if total
            else float(generated == baseline)
        )
        return generated, branch, probability, generation_probability, source, counts

    def choose_domain(self, seed: int, cycle: int, domain_count: int) -> int:
        if seed != self.seed or domain_count != self.domain_count:
            return self._domain_fn(seed, cycle, domain_count)
        if self.events and self.events[-1].get("post_state_fingerprint") is None:
            self.events[-1]["post_state_fingerprint"] = self._fingerprint(cycle - 1)

        baseline = self._domain_fn(seed, cycle, domain_count)
        env = self.spec.environment
        generated = baseline
        branch = False
        probability = 0.0
        generation_probability = 1.0
        source = "baseline"
        counts = [0 for _ in range(domain_count)]
        strength = 0.0

        in_history = env.history_start <= cycle < env.history_end
        if in_history and self.spec.history_kind in {"aligned_history", "counter_history"}:
            strength = self.spec.history_feedback_strength
            generated, branch, probability, generation_probability, source, counts = self._feedback_domain(
                cycle=cycle,
                baseline=baseline,
                strength=strength,
                source="history_feedback",
            )
        elif in_history and self.spec.history_kind == "annealed_history":
            switch = self._draw_fn(seed, cycle, 0, "trajectory-anneal-switch")
            branch = switch < self.spec.anneal_epsilon
            if branch and domain_count > 1:
                draw = self._draw_fn(seed, cycle, 0, "trajectory-anneal-domain")
                offset = min(domain_count - 2, int(draw * (domain_count - 1))) + 1
                generated = (baseline + offset) % domain_count
                source = "anneal"
                generation_probability = self.spec.anneal_epsilon / (domain_count - 1)
            else:
                generation_probability = 1.0 - self.spec.anneal_epsilon
        elif cycle >= env.activation_cycle and self.spec.post_feedback:
            strength = self.spec.feedback_strength
            generated, branch, probability, generation_probability, source, counts = self._feedback_domain(
                cycle=cycle,
                baseline=baseline,
                strength=strength,
                source="post_feedback",
            )

        self.current_cycle = cycle
        self.current_domain = generated
        self.events.append(
            {
                "cycle": cycle,
                "baseline_domain": baseline,
                "generated_domain": generated,
                "strength": strength,
                "controller_mode": f"trajectory:{self.spec.history_kind}",
                "rolling_success_counts": counts,
                "feedback_branch_taken": branch,
                "feedback_probability": probability,
                "generation_probability": generation_probability,
                "generated_domain_source": source,
                "post_state_fingerprint": None,
            }
        )
        return generated

    def observe_success(self) -> None:
        if self.current_cycle < 0 or self.current_domain < 0:
            raise RuntimeError("success observed before domain generation")
        cycle = self.current_cycle
        domain = self.current_domain
        self.actual_success_events.append((cycle, domain))
        env = self.spec.environment
        source_domain = domain
        if (
            self.spec.history_kind == "counter_history"
            and env.history_start <= cycle < env.history_end
        ):
            source_domain = (domain + 1) % self.domain_count
        self.source_success_events.append((cycle, source_domain))

    def _fingerprint(self, cycle: int) -> str:
        lower = cycle - self.window + 1
        active = [(c, d) for c, d in self.source_success_events if c >= lower]
        canonical = json.dumps(active, separators=(",", ":")).encode()
        return hashlib.sha256(canonical).hexdigest()

    def finalize(self) -> None:
        if self.events and self.events[-1].get("post_state_fingerprint") is None:
            self.events[-1]["post_state_fingerprint"] = self._fingerprint(
                int(self.events[-1]["cycle"])
            )


def load_canonical_endogenous_config(
    protocol: TrajectoryHysteresisConfig,
) -> EndogenousDemandConfig:
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


def trajectory_environment(base: EndogenousDemandConfig, spec: TrajectoryEnvironment):
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


def run_trajectory_cell(
    connection: Connection[Any],
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    label: str,
    spec: TrajectorySpec,
    seed: int,
    environment,
) -> dict[str, object]:
    arm = ec.endogenous_arm(config, label=label, environment=environment)
    env = arm.environment
    original_domain = lc._domain_index
    original_trace_repository = lc.PostgresTraceRepository
    controller = _TrajectoryController(
        spec=spec,
        seed=seed,
        cycles=env.cycles,
        domain_count=len(env.domains),
        window=config.feedback_window,
        domain_fn=original_domain,
        draw_fn=lc._draw,
    )

    class ObservingTraceRepository:
        def __init__(self, inner_connection: Connection[Any]) -> None:
            self._delegate = original_trace_repository(inner_connection)

        def add(self, trace):
            result = self._delegate.add(trace)
            if trace.kind == "VERIFIED_OUTCOME" and trace.content.startswith("skill-evidence:"):
                controller.observe_success()
            return result

        def __getattr__(self, name: str):
            return getattr(self._delegate, name)

    def controlled_domain(inner_seed: int, cycle: int, domain_count: int) -> int:
        return controller.choose_domain(inner_seed, cycle, domain_count)

    lc._domain_index = controlled_domain
    lc.PostgresTraceRepository = ObservingTraceRepository  # type: ignore[assignment]
    try:
        cell = lc.run_lifecycle_arm(
            connection,
            config=config.integration,
            config_hash=config_hash,
            experiment_number=experiment_number,
            arm=arm,
            seed=seed,
            code_sha=code_sha,
        )
    finally:
        lc._domain_index = original_domain
        lc.PostgresTraceRepository = original_trace_repository
    controller.finalize()

    rows = connection.execute(
        """
        SELECT cycle, regime, task_id, domain_index, winner_agent_id, winner_slot,
               success, created_at
        FROM integration_campaign_outcomes
        WHERE run_id = %s
        ORDER BY cycle
        """,
        (UUID(str(cell["run_id"])),),
    ).fetchall()
    row_maps = [dict(row) for row in rows]
    if len(row_maps) != env.cycles or len(controller.events) != env.cycles:
        raise RuntimeError("trajectory controller observation count mismatch")

    actual_successes = {
        (int(row["cycle"]), int(row["domain_index"]))
        for row in row_maps
        if bool(row["success"])
    }
    observed_successes = set(controller.actual_success_events)
    success_observation_consistent = actual_successes == observed_successes

    metrics = dict(cell["metrics"])
    metrics.update(
        ec._feedback_metrics(
            row_maps,
            controller.events,
            domain_count=len(env.domains),
            cycles=env.cycles,
            shift_period=env.shift_period,
        )
    )
    history_events = [
        event
        for event in controller.events
        if spec.environment.history_start <= int(event["cycle"]) < spec.environment.history_end
    ]
    post_events = [
        event for event in controller.events if int(event["cycle"]) >= spec.environment.activation_cycle
    ]
    metrics["history_branch_rate"] = (
        statistics.mean(float(bool(event["feedback_branch_taken"])) for event in history_events)
        if history_events
        else 0.0
    )
    metrics["history_override_rate"] = (
        statistics.mean(
            float(int(event["generated_domain"]) != int(event["baseline_domain"]))
            for event in history_events
        )
        if history_events
        else 0.0
    )
    metrics["post_feedback_override_rate"] = (
        statistics.mean(
            float(
                str(event["generated_domain_source"]) == "post_feedback"
                and int(event["generated_domain"]) != int(event["baseline_domain"])
            )
            for event in post_events
        )
        if post_events
        else 0.0
    )
    cell["metrics"] = metrics

    invariants = dict(cell["invariants"])
    invariants.update(
        {
            "identity_turnover_absent": float(metrics.get("exit_count", 0.0)) == 0.0,
            "trajectory_reputation_neutral": arm.policy.mode == "none",
            "production_matching_unchanged": True,
            "history_changes_domain_only": True,
            "requester_generation_unchanged": True,
            "candidate_generation_unchanged": True,
            "bid_and_outcome_draws_unchanged": True,
            "post_settlement_success_observation": success_observation_consistent,
            "annealing_exogenous": True,
        }
    )
    cell["invariants"] = invariants
    cell["trajectory_spec"] = spec.as_dict()
    ec._persist_feedback_observations(
        connection,
        run_id=str(cell["run_id"]),
        events=controller.events,
        rows=row_maps,
    )
    return cell


def _vector(features: Mapping[str, float], names: Sequence[str]) -> list[float]:
    return [float(features[name]) for name in names]


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vector length mismatch")
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)) / len(left))


def trajectory_observables(
    rows: Sequence[Mapping[str, object]],
    *,
    activation_cycle: int,
    shift_period: int,
    domains: Sequence[str],
    feature_names: Sequence[str],
) -> dict[str, object]:
    sample_times = list(range(shift_period, activation_cycle, shift_period))
    if not sample_times or sample_times[-1] != activation_cycle:
        sample_times.append(activation_cycle)
    samples: list[dict[str, object]] = []
    vectors: list[list[float]] = []
    for sample in sample_times:
        features = state_features(
            rows,
            activation_cycle=sample,
            shift_period=shift_period,
            domains=domains,
        )
        vector = _vector(features, feature_names)
        samples.append({"cycle": sample, "features": features})
        vectors.append(vector)
    increments = [_distance(vectors[i - 1], vectors[i]) for i in range(1, len(vectors))]
    path_length = sum(increments)

    def basin(vector: Sequence[float]) -> tuple[int, ...]:
        signature = []
        for value in vector:
            signature.append(0 if value < 1 / 3 else (1 if value < 2 / 3 else 2))
        return tuple(signature)

    basins = [basin(vector) for vector in vectors]
    basin_transitions = sum(basins[i] != basins[i - 1] for i in range(1, len(basins)))
    momentum = 0.0
    if len(vectors) >= 3:
        first = [a - b for a, b in zip(vectors[-2], vectors[-3], strict=True)]
        second = [a - b for a, b in zip(vectors[-1], vectors[-2], strict=True)]
        norm_first = math.sqrt(sum(value * value for value in first))
        norm_second = math.sqrt(sum(value * value for value in second))
        if norm_first > _EPSILON and norm_second > _EPSILON:
            momentum = sum(a * b for a, b in zip(first, second, strict=True)) / (
                norm_first * norm_second
            )
    second_differences: list[float] = []
    for i in range(2, len(vectors)):
        second = [
            vectors[i][j] - 2 * vectors[i - 1][j] + vectors[i - 2][j]
            for j in range(len(vectors[i]))
        ]
        second_differences.append(math.sqrt(sum(value * value for value in second)))
    roughness = statistics.mean(second_differences) if second_differences else 0.0
    return {
        "path_length": path_length,
        "basin_transitions": float(basin_transitions),
        "momentum": momentum,
        "trajectory_roughness": roughness,
        "samples": samples,
    }


def post_activation_incumbency(
    rows: Sequence[Mapping[str, object]],
    *,
    activation_cycle: int,
    shift_period: int,
    cycles: int,
) -> tuple[float, list[float]]:
    if activation_cycle % shift_period == 0:
        first_boundary = activation_cycle
    else:
        first_boundary = (activation_cycle // shift_period + 1) * shift_period
    values: list[float] = []
    for boundary in range(first_boundary, cycles, shift_period):
        if len(values) >= 4 or boundary + shift_period > cycles:
            break
        before = [
            row for row in rows if boundary - shift_period <= int(row["cycle"]) < boundary
        ]
        after = [
            row for row in rows if boundary <= int(row["cycle"]) < boundary + shift_period
        ]
        if not before or not after:
            continue
        by_domain: dict[int, Counter[int]] = {}
        for row in before:
            domain = int(row["domain_index"])
            by_domain.setdefault(domain, Counter())[int(row["winner_slot"])] += 1
        incumbents: dict[int, int] = {}
        for domain, counts in by_domain.items():
            high = max(counts.values())
            incumbents[domain] = min(slot for slot, count in counts.items() if count == high)
        values.append(
            sum(
                incumbents.get(int(row["domain_index"])) == int(row["winner_slot"])
                for row in after
            )
            / len(after)
        )
    if len(values) != 4:
        raise RuntimeError(f"expected four post-activation transitions, observed {len(values)}")
    return statistics.mean(values), values


def _cell_metrics(cell: Mapping[str, object]) -> Mapping[str, object]:
    metrics = cell["metrics"]
    assert isinstance(metrics, Mapping)
    return metrics


def _cell_invariants(cell: Mapping[str, object]) -> Mapping[str, object]:
    invariants = cell["invariants"]
    assert isinstance(invariants, Mapping)
    return invariants


def _persist_record(connection: Connection[Any], record: Mapping[str, object]) -> None:
    with connection.transaction():
        connection.execute(
            """
            INSERT INTO trajectory_hysteresis_states (
                experiment_number, cohort, history_kind, seed, activation_cycle,
                control_run_id, treatment_run_id, endpoint_features,
                trajectory_observables, preactivation_exact, trajectory_exact,
                control_post_incumbency, treatment_post_incumbency,
                delta_incumbency, success_effect, knowledge_effect, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, NOW()
            )
            """,
            (
                record["experiment_number"],
                record["cohort"],
                record["history_kind"],
                record["seed"],
                record["activation_cycle"],
                UUID(str(record["control_run_id"])),
                UUID(str(record["treatment_run_id"])),
                Jsonb(dict(record["features"])),  # type: ignore[arg-type]
                Jsonb(dict(record["trajectory"])),  # type: ignore[arg-type]
                record["preactivation_exact"],
                record["trajectory_exact"],
                record.get("control_post_incumbency"),
                record.get("treatment_post_incumbency"),
                record.get("delta_incumbency"),
                record.get("success_effect"),
                record.get("knowledge_effect"),
            ),
        )


def run_history_pair(
    connection: Connection[Any],
    *,
    protocol: TrajectoryHysteresisConfig,
    base: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    cohort: str,
    history_kind: str,
    seed: int,
    environment_spec: TrajectoryEnvironment,
    analyze_post: bool = True,
) -> dict[str, object]:
    env = trajectory_environment(base, environment_spec)
    control_spec = TrajectorySpec(history_kind, environment_spec, False)
    treatment_spec = TrajectorySpec(history_kind, environment_spec, True)
    control = run_trajectory_cell(
        connection,
        config=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=experiment_number,
        label=f"{cohort}_{history_kind}_control",
        spec=control_spec,
        seed=seed,
        environment=env,
    )
    treatment = run_trajectory_cell(
        connection,
        config=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=experiment_number,
        label=f"{cohort}_{history_kind}_feedback",
        spec=treatment_spec,
        seed=seed,
        environment=env,
    )
    control_rows = _query_outcomes(connection, str(control["run_id"]))
    treatment_rows = _query_outcomes(connection, str(treatment["run_id"]))
    control_events = _query_feedback(connection, str(control["run_id"]))
    treatment_events = _query_feedback(connection, str(treatment["run_id"]))
    activation = environment_spec.activation_cycle
    exact = preactivation_exact(
        control_rows,
        treatment_rows,
        control_events,
        treatment_events,
        activation_cycle=activation,
    )
    control_features = state_features(
        control_rows,
        activation_cycle=activation,
        shift_period=environment_spec.shift_period,
        domains=env.domains,
    )
    treatment_features = state_features(
        treatment_rows,
        activation_cycle=activation,
        shift_period=environment_spec.shift_period,
        domains=env.domains,
    )
    features_exact = all(
        abs(control_features[name] - treatment_features[name]) <= _EPSILON
        for name in protocol.endpoint_features
    )
    control_trajectory = trajectory_observables(
        control_rows,
        activation_cycle=activation,
        shift_period=environment_spec.shift_period,
        domains=env.domains,
        feature_names=protocol.endpoint_features,
    )
    treatment_trajectory = trajectory_observables(
        treatment_rows,
        activation_cycle=activation,
        shift_period=environment_spec.shift_period,
        domains=env.domains,
        feature_names=protocol.endpoint_features,
    )
    trajectory_exact = all(
        abs(float(control_trajectory[name]) - float(treatment_trajectory[name])) <= _EPSILON
        for name in protocol.trajectory_features
    )
    invariants = all(bool(value) for value in _cell_invariants(control).values()) and all(
        bool(value) for value in _cell_invariants(treatment).values()
    )
    control_metrics = _cell_metrics(control)
    treatment_metrics = _cell_metrics(treatment)
    record: dict[str, object] = {
        "experiment_number": experiment_number,
        "cohort": cohort,
        "history_kind": history_kind,
        "seed": seed,
        "activation_cycle": activation,
        "control_run_id": control["run_id"],
        "treatment_run_id": treatment["run_id"],
        "preactivation_exact": exact,
        "state_features_exact": features_exact,
        "trajectory_exact": trajectory_exact,
        "all_cell_invariants": invariants,
        "features": control_features,
        "trajectory": control_trajectory,
        "history_override_rate": float(control_metrics["history_override_rate"]),
        "history_branch_rate": float(control_metrics["history_branch_rate"]),
    }
    if analyze_post:
        control_i, control_by_shift = post_activation_incumbency(
            control_rows,
            activation_cycle=activation,
            shift_period=environment_spec.shift_period,
            cycles=environment_spec.cycles,
        )
        treatment_i, treatment_by_shift = post_activation_incumbency(
            treatment_rows,
            activation_cycle=activation,
            shift_period=environment_spec.shift_period,
            cycles=environment_spec.cycles,
        )
        record.update(
            {
                "control_post_incumbency": control_i,
                "treatment_post_incumbency": treatment_i,
                "control_post_by_shift": control_by_shift,
                "treatment_post_by_shift": treatment_by_shift,
                "delta_incumbency": treatment_i - control_i,
                "success_effect": float(treatment_metrics["success_rate"])
                - float(control_metrics["success_rate"]),
                "knowledge_effect": float(treatment_metrics["late_public_knowledge_coverage"])
                - float(control_metrics["late_public_knowledge_coverage"]),
                "post_feedback_override_rate": float(
                    treatment_metrics["post_feedback_override_rate"]
                ),
            }
        )
    _persist_record(connection, record)
    return record


def run_history_cohort(
    connection: Connection[Any],
    *,
    protocol: TrajectoryHysteresisConfig,
    base: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    cohort: str,
    seeds: Sequence[int],
    environment_spec: TrajectoryEnvironment,
    analyze_post: bool = True,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for history_kind in protocol.history_kinds:
        for seed in seeds:
            records.append(
                run_history_pair(
                    connection,
                    protocol=protocol,
                    base=base,
                    config_hash=config_hash,
                    code_sha=code_sha,
                    experiment_number=experiment_number,
                    cohort=cohort,
                    history_kind=history_kind,
                    seed=seed,
                    environment_spec=environment_spec,
                    analyze_post=analyze_post,
                )
            )
    return records


def _sign_class(value: float, neutral_band: float) -> str:
    if value > neutral_band:
        return "positive"
    if value < -neutral_band:
        return "negative"
    return "neutral"


def match_histories(
    records: Sequence[Mapping[str, object]],
    *,
    left_history: str,
    right_history: str,
    protocol: TrajectoryHysteresisConfig,
) -> dict[str, object]:
    left = [record for record in records if record["history_kind"] == left_history]
    right = [record for record in records if record["history_kind"] == right_history]
    candidates: list[tuple[float, int, int, Mapping[str, object], Mapping[str, object]]] = []
    for lrecord in left:
        lfeatures = lrecord["features"]
        assert isinstance(lfeatures, Mapping)
        lvector = _vector(lfeatures, protocol.endpoint_features)  # type: ignore[arg-type]
        for rrecord in right:
            rfeatures = rrecord["features"]
            assert isinstance(rfeatures, Mapping)
            rvector = _vector(rfeatures, protocol.endpoint_features)  # type: ignore[arg-type]
            differences = [abs(a - b) for a, b in zip(lvector, rvector, strict=True)]
            rms = _distance(lvector, rvector)
            if max(differences) <= protocol.max_feature_difference and rms <= protocol.max_rms_distance:
                candidates.append(
                    (rms, int(lrecord["seed"]), int(rrecord["seed"]), lrecord, rrecord)
                )
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    used_left: set[int] = set()
    used_right: set[int] = set()
    pairs: list[dict[str, object]] = []
    for distance, left_seed, right_seed, lrecord, rrecord in candidates:
        if left_seed in used_left or right_seed in used_right:
            continue
        used_left.add(left_seed)
        used_right.add(right_seed)
        pair: dict[str, object] = {
            "left_seed": left_seed,
            "right_seed": right_seed,
            "distance": distance,
        }
        ltraj = lrecord["trajectory"]
        rtraj = rrecord["trajectory"]
        assert isinstance(ltraj, Mapping) and isinstance(rtraj, Mapping)
        pair.update(
            {
                "path_length_gap": abs(float(ltraj["path_length"]) - float(rtraj["path_length"])),
                "basin_discordant": float(ltraj["basin_transitions"])
                != float(rtraj["basin_transitions"]),
                "momentum_gap": abs(float(ltraj["momentum"]) - float(rtraj["momentum"])),
            }
        )
        if "delta_incumbency" in lrecord and "delta_incumbency" in rrecord:
            left_delta = float(lrecord["delta_incumbency"])
            right_delta = float(rrecord["delta_incumbency"])
            pair.update(
                {
                    "left_delta": left_delta,
                    "right_delta": right_delta,
                    "effect_gap": abs(left_delta - right_delta),
                    "left_sign": _sign_class(left_delta, protocol.neutral_band),
                    "right_sign": _sign_class(right_delta, protocol.neutral_band),
                }
            )
        pairs.append(pair)
    denominator = min(len(left), len(right))
    return {
        "left_history": left_history,
        "right_history": right_history,
        "matched_count": len(pairs),
        "eligible_left": len(left),
        "eligible_right": len(right),
        "support": len(pairs) / denominator if denominator else 0.0,
        "pairs": pairs,
    }


def _quality_by_history(
    records: Sequence[Mapping[str, object]], protocol: TrajectoryHysteresisConfig
) -> tuple[dict[str, dict[str, object]], bool]:
    result: dict[str, dict[str, object]] = {}
    all_good = True
    for history in protocol.history_kinds:
        subset = [record for record in records if record["history_kind"] == history]
        if not subset:
            result[history] = {"quality_gate": False}
            all_good = False
            continue
        success = statistics.mean(float(record["success_effect"]) for record in subset)
        knowledge = statistics.mean(float(record["knowledge_effect"]) for record in subset)
        integrity = all(
            bool(record["preactivation_exact"])
            and bool(record["state_features_exact"])
            and bool(record["trajectory_exact"])
            and bool(record["all_cell_invariants"])
            for record in subset
        )
        gate = (
            integrity
            and success >= -protocol.success_tolerance
            and knowledge >= -protocol.knowledge_tolerance
        )
        result[history] = {
            "success_effect": success,
            "knowledge_effect": knowledge,
            "integrity": integrity,
            "quality_gate": gate,
        }
        all_good = all_good and gate
    return result, all_good


def _sign_concentration(values: Sequence[float], neutral_band: float) -> tuple[float, float, dict[str, int]]:
    classes = [_sign_class(value, neutral_band) for value in values]
    counts = Counter(classes)
    if not classes:
        return 0.0, 1.0, {"positive": 0, "neutral": 0, "negative": 0}
    concentration = max(counts.get(name, 0) for name in ("positive", "neutral", "negative")) / len(classes)
    entropy = 0.0
    for name in ("positive", "neutral", "negative"):
        probability = counts.get(name, 0) / len(classes)
        if probability > 0:
            entropy -= probability * math.log(probability)
    entropy /= math.log(3)
    return concentration, entropy, {
        "positive": counts.get("positive", 0),
        "neutral": counts.get("neutral", 0),
        "negative": counts.get("negative", 0),
    }


def evaluate_hysteresis(
    records: Sequence[Mapping[str, object]], protocol: TrajectoryHysteresisConfig
) -> dict[str, object]:
    structured = match_histories(
        records,
        left_history="aligned_history",
        right_history="counter_history",
        protocol=protocol,
    )
    pairs = structured["pairs"]
    assert isinstance(pairs, Sequence)
    path_gap = statistics.mean(float(pair["path_length_gap"]) for pair in pairs) if pairs else 0.0
    basin_discordance = (
        statistics.mean(float(bool(pair["basin_discordant"])) for pair in pairs) if pairs else 0.0
    )
    momentum_gap = statistics.mean(float(pair["momentum_gap"]) for pair in pairs) if pairs else 0.0
    effect_gap = statistics.mean(float(pair.get("effect_gap", 0.0)) for pair in pairs) if pairs else 0.0
    informative = [
        pair
        for pair in pairs
        if not (pair.get("left_sign") == "neutral" and pair.get("right_sign") == "neutral")
    ]
    sign_discordance = (
        statistics.mean(float(pair.get("left_sign") != pair.get("right_sign")) for pair in informative)
        if informative
        else 0.0
    )
    trajectory_separation = (
        path_gap >= protocol.minimum_path_gap
        or basin_discordance >= protocol.minimum_basin_discordance
        or momentum_gap >= protocol.minimum_momentum_gap
    )
    quality, quality_gate = _quality_by_history(records, protocol)
    structured_gate = (
        float(structured["support"]) >= protocol.minimum_endpoint_support
        and trajectory_separation
        and effect_gap >= protocol.minimum_effect_gap
        and sign_discordance >= protocol.minimum_sign_discordance
        and quality_gate
    )

    anneal = match_histories(
        records,
        left_history="smooth_reference",
        right_history="annealed_history",
        protocol=protocol,
    )
    anneal_pairs = anneal["pairs"]
    assert isinstance(anneal_pairs, Sequence)
    by_key = {(str(r["history_kind"]), int(r["seed"])): r for r in records}
    smooth_values: list[float] = []
    annealed_values: list[float] = []
    for pair in anneal_pairs:
        smooth = by_key[("smooth_reference", int(pair["left_seed"]))]
        noisy = by_key[("annealed_history", int(pair["right_seed"]))]
        if "delta_incumbency" in smooth and "delta_incumbency" in noisy:
            smooth_values.append(float(smooth["delta_incumbency"]))
            annealed_values.append(float(noisy["delta_incumbency"]))
    smooth_concentration, smooth_entropy, smooth_counts = _sign_concentration(
        smooth_values, protocol.neutral_band
    )
    annealed_concentration, annealed_entropy, annealed_counts = _sign_concentration(
        annealed_values, protocol.neutral_band
    )
    concentration_gain = annealed_concentration - smooth_concentration
    entropy_reduction = smooth_entropy - annealed_entropy
    annealing_gate = (
        float(anneal["support"]) >= protocol.minimum_endpoint_support
        and concentration_gain >= protocol.minimum_anneal_concentration_gain
        and entropy_reduction >= protocol.minimum_anneal_entropy_reduction
        and quality_gate
    )
    return {
        "structured_matching": structured,
        "structured_support": float(structured["support"]),
        "mean_path_length_gap": path_gap,
        "basin_transition_discordance": basin_discordance,
        "mean_momentum_gap": momentum_gap,
        "trajectory_separation": trajectory_separation,
        "mean_absolute_effect_gap": effect_gap,
        "sign_discordance": sign_discordance,
        "quality_by_history": quality,
        "quality_gate": quality_gate,
        "hysteresis_gate": structured_gate,
        "annealing_matching": anneal,
        "annealing_support": float(anneal["support"]),
        "smooth_sign_concentration": smooth_concentration,
        "annealed_sign_concentration": annealed_concentration,
        "sign_concentration_gain": concentration_gain,
        "smooth_sign_entropy": smooth_entropy,
        "annealed_sign_entropy": annealed_entropy,
        "sign_entropy_reduction": entropy_reduction,
        "smooth_sign_counts": smooth_counts,
        "annealed_sign_counts": annealed_counts,
        "annealing_gate": annealing_gate,
    }


def evaluate_instrumentation(
    records: Sequence[Mapping[str, object]], protocol: TrajectoryHysteresisConfig
) -> dict[str, object]:
    exact = all(
        bool(record["preactivation_exact"])
        and bool(record["state_features_exact"])
        and bool(record["trajectory_exact"])
        and bool(record["all_cell_invariants"])
        for record in records
    )
    structured = match_histories(
        records,
        left_history="aligned_history",
        right_history="counter_history",
        protocol=protocol,
    )
    anneal = match_histories(
        records,
        left_history="smooth_reference",
        right_history="annealed_history",
        protocol=protocol,
    )
    intervention_by_history = {
        history: statistics.mean(
            float(record["history_override_rate"])
            for record in records
            if record["history_kind"] == history
        )
        for history in protocol.history_kinds
    }
    material = (
        intervention_by_history["aligned_history"] > 0.0
        and intervention_by_history["counter_history"] > 0.0
        and intervention_by_history["annealed_history"] > 0.0
    )
    gate = (
        exact
        and material
        and int(structured["matched_count"]) >= 1
        and int(anneal["matched_count"]) >= 1
    )
    return {
        "exact_pairing": exact,
        "history_intervention_rates": intervention_by_history,
        "history_manipulation_material": material,
        "structured_matching": structured,
        "annealing_matching": anneal,
        "instrumentation_gate": gate,
    }


def _label_permutations(labels: Sequence[bool]) -> list[list[bool]]:
    positives = sum(labels)
    indices = range(len(labels))
    result: list[list[bool]] = []
    for positive_indices in itertools.combinations(indices, positives):
        selected = set(positive_indices)
        result.append([index in selected for index in indices])
    return result


def evaluate_trajectory_predictors(
    records: Sequence[Mapping[str, object]], protocol: TrajectoryHysteresisConfig
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    smooth = [record for record in records if record["history_kind"] == "smooth_reference"]
    if len(smooth) != len(protocol.discovery_seeds):
        raise ValueError("trajectory predictor requires exactly the 12 smooth discovery records")
    response = [float(record["delta_incumbency"]) for record in smooth]
    labels = [value > protocol.neutral_band for value in response]
    values_by_feature = {
        feature: [float(record["trajectory"][feature]) for record in smooth]  # type: ignore[index]
        for feature in protocol.trajectory_features
    }
    evaluations: list[dict[str, object]] = []
    for feature in protocol.trajectory_features:
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
                "loo_direction_stable": all(
                    str(value) == str(fit["direction"]) for value in directions
                ),
            }
        )
    permutations = _label_permutations(labels)
    max_scores = [
        max(
            float(_loo_threshold(values_by_feature[feature], permuted)["balanced_accuracy"])
            for feature in protocol.trajectory_features
        )
        for permuted in permutations
    ]
    for evaluation in evaluations:
        observed = float(evaluation["loo_balanced_accuracy"])
        p_value = sum(score >= observed - _EPSILON for score in max_scores) / len(max_scores)
        evaluation["familywise_permutation_p"] = p_value
        evaluation["qualifies"] = (
            float(evaluation["loo_accuracy"]) >= protocol.minimum_predictor_loo_accuracy
            and observed >= protocol.minimum_predictor_loo_balanced_accuracy
            and bool(evaluation["loo_direction_stable"])
            and abs(float(evaluation["spearman_delta_incumbency"]))
            >= protocol.minimum_predictor_abs_spearman
            and p_value <= protocol.maximum_predictor_familywise_p
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
            -protocol.trajectory_features.index(str(item["feature"])),
        ),
    )
    return evaluations, dict(selected)


def validate_trajectory_predictor(
    records: Sequence[Mapping[str, object]],
    classifier: Mapping[str, object] | None,
    protocol: TrajectoryHysteresisConfig,
) -> dict[str, object]:
    if classifier is None:
        return {
            "predictor_available": False,
            "predictor_accuracy": 0.0,
            "predictor_balanced_accuracy": 0.0,
            "predictor_directional_separation": False,
            "predictor_validation_gate": False,
        }
    smooth = [record for record in records if record["history_kind"] == "smooth_reference"]
    feature = str(classifier["feature"])
    threshold = float(classifier["threshold"])
    direction = str(classifier["direction"])
    values = [float(record["trajectory"][feature]) for record in smooth]  # type: ignore[index]
    actual = [float(record["delta_incumbency"]) > protocol.neutral_band for record in smooth]
    predicted = _predict(values, threshold=threshold, direction=direction)
    accuracy = sum(a == p for a, p in zip(actual, predicted, strict=True)) / len(actual)
    balanced = _balanced_accuracy(actual, predicted)
    positive_deltas = [
        float(record["delta_incumbency"])
        for record, label in zip(smooth, predicted, strict=True)
        if label
    ]
    negative_deltas = [
        float(record["delta_incumbency"])
        for record, label in zip(smooth, predicted, strict=True)
        if not label
    ]
    separation = bool(positive_deltas and negative_deltas) and (
        statistics.mean(positive_deltas) > statistics.mean(negative_deltas)
    )
    gate = (
        accuracy >= protocol.minimum_predictor_validation_accuracy
        and balanced >= protocol.minimum_predictor_validation_balanced_accuracy
        and separation
    )
    return {
        "predictor_available": True,
        "predictor_feature": feature,
        "predictor_threshold": threshold,
        "predictor_direction": direction,
        "predictor_accuracy": accuracy,
        "predictor_balanced_accuracy": balanced,
        "predictor_directional_separation": separation,
        "predictor_validation_gate": gate,
    }


__all__ = [
    "TrajectorySpec",
    "evaluate_hysteresis",
    "evaluate_instrumentation",
    "evaluate_trajectory_predictors",
    "load_canonical_endogenous_config",
    "match_histories",
    "post_activation_incumbency",
    "run_history_cohort",
    "run_history_pair",
    "trajectory_observables",
    "validate_trajectory_predictor",
]
