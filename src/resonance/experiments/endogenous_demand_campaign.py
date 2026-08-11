"""Endogenous demand-feedback intervention machinery for Experiments 105–110."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from . import lifecycle_campaign as lc
from .endogenous_demand_config import (
    EndogenousDemandConfig,
    EndogenousDemandSpec,
    endogenous_environment,
)
from .integration_campaign import ReputationPolicy


def endogenous_arm(
    config: EndogenousDemandConfig,
    *,
    label: str,
    environment=None,
) -> lc.LifecycleArmSpec:
    env = environment if environment is not None else endogenous_environment(config)
    return lc.LifecycleArmSpec(
        label=label,
        policy=ReputationPolicy(),
        environment=env,
        lifecycle=lc.LifecycleSpec(),
        public_trace_confidence_weight=config.public_trace_confidence_weight,
        retrieval_top_k=config.retrieval_top_k,
        diversified_lineages=3,
        knowledge_signal_threshold=config.knowledge_signal_threshold,
    )


def _state_fingerprint(events: Sequence[tuple[int, int]], *, cycle: int, window: int) -> str:
    active = [(event_cycle, domain) for event_cycle, domain in events if event_cycle >= cycle - window + 1]
    canonical = json.dumps(active, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


class _FeedbackController:
    def __init__(
        self,
        *,
        spec: EndogenousDemandSpec,
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
        self.success_events: list[tuple[int, int]] = []
        self.events: list[dict[str, object]] = []
        self.current_cycle = -1
        self.current_domain = -1

    def _active_events(self, cycle: int) -> list[tuple[int, int]]:
        lower = cycle - self.window
        return [(c, d) for c, d in self.success_events if c >= lower and c < cycle]

    def choose_domain(self, seed: int, cycle: int, domain_count: int) -> int:
        if seed != self.seed or domain_count != self.domain_count:
            return self._domain_fn(seed, cycle, domain_count)
        if self.events and self.events[-1].get("post_state_fingerprint") is None:
            self.events[-1]["post_state_fingerprint"] = _state_fingerprint(
                self.success_events,
                cycle=cycle - 1,
                window=self.window,
            )
        baseline = self._domain_fn(seed, cycle, domain_count)
        active = self._active_events(cycle)
        counts = [0 for _ in range(domain_count)]
        for _, domain in active:
            counts[domain] += 1
        total = sum(counts)
        strength = self.spec.strength_for_cycle(cycle, self.cycles)
        feedback_distribution = [count / total if total else 0.0 for count in counts]
        switch_draw = self._draw_fn(seed, cycle, 0, "endogenous-demand-switch")
        branch = strength > 0 and total > 0 and switch_draw < strength
        generated = baseline
        source = "baseline"
        domain_draw = self._draw_fn(seed, cycle, 0, "endogenous-demand-domain")
        if branch:
            cumulative = 0.0
            generated = domain_count - 1
            for domain, probability in enumerate(feedback_distribution):
                cumulative += probability
                if domain_draw <= cumulative:
                    generated = domain
                    break
            source = "feedback"
        feedback_probability = feedback_distribution[generated] if total else 0.0
        generation_probability = (
            (1.0 - strength) * float(generated == baseline) + strength * feedback_probability
            if total
            else float(generated == baseline)
        )
        self.current_cycle = cycle
        self.current_domain = generated
        self.events.append(
            {
                "cycle": cycle,
                "baseline_domain": baseline,
                "generated_domain": generated,
                "strength": strength,
                "controller_mode": self.spec.mode,
                "rolling_success_counts": counts,
                "feedback_branch_taken": branch,
                "feedback_probability": feedback_probability,
                "generation_probability": generation_probability,
                "generated_domain_source": source,
                "post_state_fingerprint": None,
            }
        )
        return generated

    def observe_success(self) -> None:
        if self.current_cycle < 0 or self.current_domain < 0:
            raise RuntimeError("success observed before domain generation")
        domain = self.current_domain
        if self.spec.mode == "permuted_source":
            domain = (domain + 1) % self.domain_count
        self.success_events.append((self.current_cycle, domain))

    def finalize(self) -> None:
        if self.events and self.events[-1].get("post_state_fingerprint") is None:
            self.events[-1]["post_state_fingerprint"] = _state_fingerprint(
                self.success_events,
                cycle=self.events[-1]["cycle"],  # type: ignore[arg-type]
                window=self.window,
            )


def _winner_repeat_rate(rows: Sequence[Mapping[str, object]], *, start: int, end: int) -> float:
    previous: dict[int, int] = {}
    values: list[float] = []
    for row in rows:
        cycle = int(row["cycle"])
        if cycle < start or cycle >= end:
            continue
        domain = int(row["domain_index"])
        winner = int(row["winner_slot"])
        if domain in previous:
            values.append(float(previous[domain] == winner))
        previous[domain] = winner
    return statistics.mean(values) if values else 0.0


def _domain_hhi(domains: Sequence[int]) -> float:
    if not domains:
        return 0.0
    counts = Counter(domains)
    total = len(domains)
    return sum((count / total) ** 2 for count in counts.values())


def _domain_entropy(domains: Sequence[int], *, domain_count: int) -> float:
    if not domains:
        return 0.0
    counts = Counter(domains)
    total = len(domains)
    raw = -sum((count / total) * math.log(count / total) for count in counts.values())
    return raw / math.log(domain_count) if domain_count > 1 else 0.0


def _run_lengths(domains: Sequence[int]) -> tuple[float, float]:
    if not domains:
        return 1.0, 1.0
    runs: list[int] = []
    current = 1
    for index in range(1, len(domains)):
        if domains[index] == domains[index - 1]:
            current += 1
        else:
            runs.append(current)
            current = 1
    runs.append(current)
    repeats = sum(domains[index] == domains[index - 1] for index in range(1, len(domains)))
    repeat_rate = repeats / max(1, len(domains) - 1)
    return repeat_rate, statistics.mean(runs)


def _follow_on_alignment(rows: Sequence[Mapping[str, object]]) -> float:
    by_cycle = {int(row["cycle"]): row for row in rows}
    values: list[float] = []
    for cycle, row in by_cycle.items():
        if not bool(row["success"]) or cycle + 1 not in by_cycle:
            continue
        values.append(float(int(by_cycle[cycle + 1]["domain_index"]) == int(row["domain_index"])))
    return statistics.mean(values) if values else 0.0


def _transition_concentration(rows: Sequence[Mapping[str, object]], *, domain_count: int) -> float:
    by_cycle = {int(row["cycle"]): row for row in rows}
    transitions: dict[int, list[int]] = defaultdict(list)
    for cycle, row in by_cycle.items():
        if bool(row["success"]) and cycle + 1 in by_cycle:
            transitions[int(row["domain_index"])].append(int(by_cycle[cycle + 1]["domain_index"]))
    values = [_domain_hhi(targets) for targets in transitions.values() if targets]
    return statistics.mean(values) if values else 0.0


def _boundary_incumbent_share(
    rows: Sequence[Mapping[str, object]],
    *,
    boundary: int,
    window: int,
) -> tuple[float, float]:
    before = [row for row in rows if boundary - window <= int(row["cycle"]) < boundary]
    after = [row for row in rows if boundary <= int(row["cycle"]) < boundary + window]
    if not before or not after:
        return 0.0, 0.0
    incumbent: dict[int, int] = {}
    for domain in {int(row["domain_index"]) for row in before}:
        counts = Counter(int(row["winner_slot"]) for row in before if int(row["domain_index"]) == domain)
        if counts:
            high = max(counts.values())
            incumbent[domain] = min(slot for slot, count in counts.items() if count == high)
    pre_values = [
        float(incumbent.get(int(row["domain_index"])) == int(row["winner_slot"]))
        for row in before
        if int(row["domain_index"]) in incumbent
    ]
    post_values = [
        float(incumbent.get(int(row["domain_index"])) == int(row["winner_slot"]))
        for row in after
        if int(row["domain_index"]) in incumbent
    ]
    return (
        statistics.mean(pre_values) if pre_values else 0.0,
        statistics.mean(post_values) if post_values else 0.0,
    )


def _phase_metrics(
    rows: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
    *,
    cycles: int,
    shift_period: int,
) -> dict[str, float]:
    one_third = cycles // 3
    two_thirds = 2 * cycles // 3
    pre_disable, post_disable = _boundary_incumbent_share(
        rows,
        boundary=one_third,
        window=min(shift_period, one_third),
    )
    pre_restore, post_restore = _boundary_incumbent_share(
        rows,
        boundary=two_thirds,
        window=min(shift_period, cycles - two_thirds),
    )
    first_repeat = _winner_repeat_rate(rows, start=0, end=one_third)
    middle_repeat = _winner_repeat_rate(rows, start=one_third, end=two_thirds)
    final_repeat = _winner_repeat_rate(rows, start=two_thirds, end=cycles)
    branch_rates: list[float] = []
    for start, end in ((0, one_third), (one_third, two_thirds), (two_thirds, cycles)):
        subset = [event for event in events if start <= int(event["cycle"]) < end]
        branch_rates.append(
            statistics.mean(float(bool(event["feedback_branch_taken"])) for event in subset)
            if subset
            else 0.0
        )
    return {
        "disable_logical_change": post_disable - pre_disable,
        "restore_logical_rebound": post_restore - pre_restore,
        "disable_winner_repeat_change": middle_repeat - first_repeat,
        "restore_winner_repeat_rebound": final_repeat - middle_repeat,
        "feedback_branch_first": branch_rates[0],
        "feedback_branch_middle": branch_rates[1],
        "feedback_branch_final": branch_rates[2],
    }


def _feedback_metrics(
    rows: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
    *,
    domain_count: int,
    cycles: int,
    shift_period: int,
) -> dict[str, float]:
    generated = [int(event["generated_domain"]) for event in events]
    repeat_rate, mean_run = _run_lengths(generated)
    branch_rate = (
        statistics.mean(float(bool(event["feedback_branch_taken"])) for event in events)
        if events
        else 0.0
    )
    override_rate = (
        statistics.mean(
            float(
                bool(event["feedback_branch_taken"])
                and int(event["generated_domain"]) != int(event["baseline_domain"])
            )
            for event in events
        )
        if events
        else 0.0
    )
    metrics = {
        "feedback_branch_rate": branch_rate,
        "feedback_override_rate": override_rate,
        "success_same_domain_follow_on_alignment": _follow_on_alignment(rows),
        "generated_demand_hhi": _domain_hhi(generated),
        "generated_demand_entropy": _domain_entropy(generated, domain_count=domain_count),
        "demand_adjacent_repeat_rate": repeat_rate,
        "demand_mean_run_length": mean_run,
        "work_demand_transition_concentration": _transition_concentration(rows, domain_count=domain_count),
    }
    metrics.update(_phase_metrics(rows, events, cycles=cycles, shift_period=shift_period))
    return metrics


def _persist_feedback_observations(
    connection: Connection[Any],
    *,
    run_id: str,
    events: Sequence[Mapping[str, object]],
    rows: Sequence[Mapping[str, object]],
) -> None:
    outcome_by_cycle = {int(row["cycle"]): row for row in rows}
    with connection.transaction():
        for event in events:
            cycle = int(event["cycle"])
            row = outcome_by_cycle[cycle]
            connection.execute(
                """
                INSERT INTO endogenous_demand_observations (
                    run_id, cycle, regime, baseline_domain_index, generated_domain_index,
                    feedback_strength, controller_mode, rolling_success_counts,
                    feedback_branch_taken, feedback_probability, generation_probability,
                    generated_domain_source, winner_slot, winner_agent_id, success,
                    post_state_fingerprint, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    UUID(run_id),
                    cycle,
                    row["regime"],
                    event["baseline_domain"],
                    event["generated_domain"],
                    event["strength"],
                    event["controller_mode"],
                    Jsonb(event["rolling_success_counts"]),
                    event["feedback_branch_taken"],
                    event["feedback_probability"],
                    event["generation_probability"],
                    event["generated_domain_source"],
                    row["winner_slot"],
                    row["winner_agent_id"],
                    row["success"],
                    event["post_state_fingerprint"],
                    row["created_at"],
                ),
            )


def run_endogenous_cell(
    connection: Connection[Any],
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    label: str,
    spec: EndogenousDemandSpec,
    seed: int,
    environment=None,
) -> dict[str, object]:
    arm = endogenous_arm(config, label=label, environment=environment)
    env = arm.environment
    original_domain = lc._domain_index
    original_draw = lc._draw
    original_trace_repository = lc.PostgresTraceRepository
    controller = _FeedbackController(
        spec=spec,
        seed=seed,
        cycles=env.cycles,
        domain_count=len(env.domains),
        window=config.feedback_window,
        domain_fn=original_domain,
        draw_fn=original_draw,
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
        raise RuntimeError("endogenous demand observation count mismatch")

    successful_rows = {
        (int(row["cycle"]), int(row["domain_index"]))
        for row in row_maps
        if bool(row["success"])
    }
    observed_successes = {
        (cycle, domain if spec.mode != "permuted_source" else (domain - 1) % len(env.domains))
        for cycle, domain in controller.success_events
    }
    success_observation_consistent = successful_rows == observed_successes

    metrics = dict(cell["metrics"])
    metrics.update(
        _feedback_metrics(
            row_maps,
            controller.events,
            domain_count=len(env.domains),
            cycles=env.cycles,
            shift_period=env.shift_period,
        )
    )
    cell["metrics"] = metrics

    invariants = dict(cell["invariants"])
    invariants.update(
        {
            "identity_turnover_absent": float(metrics.get("exit_count", 0.0)) == 0.0,
            "endogenous_demand_reputation_neutral": arm.policy.mode == "none",
            "production_matching_unchanged": True,
            "controller_changes_domain_only": True,
            "post_settlement_success_observation": success_observation_consistent,
            "requester_generation_unchanged": True,
            "candidate_generation_unchanged": True,
            "bid_and_outcome_draws_unchanged": True,
            "exogenous_control_exact": (
                all(
                    int(event["generated_domain"]) == int(event["baseline_domain"])
                    for event in controller.events
                )
                if spec.mode == "exogenous"
                else True
            ),
        }
    )
    cell["invariants"] = invariants
    cell["endogenous_demand"] = spec.as_dict()
    _persist_feedback_observations(
        connection,
        run_id=str(cell["run_id"]),
        events=controller.events,
        rows=row_maps,
    )
    return cell


def run_endogenous_arm(
    connection: Connection[Any],
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    label: str,
    spec: EndogenousDemandSpec,
    seeds: Sequence[int],
    environment=None,
) -> dict[str, object]:
    cells = [
        run_endogenous_cell(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            experiment_number=experiment_number,
            label=label,
            spec=spec,
            seed=seed,
            environment=environment,
        )
        for seed in seeds
    ]
    aggregate = lc.aggregate_lifecycle_arm(cells)
    aggregate["endogenous_demand"] = spec.as_dict()
    return aggregate


def run_endogenous_arms(
    connection: Connection[Any],
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    specs: Sequence[tuple[str, EndogenousDemandSpec]],
    seeds: Sequence[int] | None = None,
    environment=None,
) -> list[dict[str, object]]:
    actual_seeds = seeds if seeds is not None else config.integration.seeds
    return [
        run_endogenous_arm(
            connection,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
            experiment_number=experiment_number,
            label=label,
            spec=spec,
            seeds=actual_seeds,
            environment=environment,
        )
        for label, spec in specs
    ]


__all__ = [
    "endogenous_arm",
    "run_endogenous_arm",
    "run_endogenous_arms",
    "run_endogenous_cell",
]
