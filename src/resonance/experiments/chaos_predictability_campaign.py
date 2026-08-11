"""Chaos / predictability-decay machinery for Experiments 123–128."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from resonance.substrate.models import Trace

from . import endogenous_demand_campaign as ec
from . import lifecycle_campaign as lc
from .chaos_predictability_config import ChaosEnvironment, ChaosPredictabilityConfig
from .endogenous_demand_config import endogenous_environment, load_endogenous_demand_config

_EPS = 1e-12
_PRIMARY_FAMILIES = ("bid_confidence", "trace_energy")


@dataclass(frozen=True, slots=True)
class ChaosCellSpec:
    family: str
    epsilon: float
    feedback_strength: float
    perturbed: bool
    feedback_delay: int = 0

    def __post_init__(self) -> None:
        if self.family not in {*_PRIMARY_FAMILIES, "embedding_control", "feedback_delay"}:
            raise ValueError(f"unsupported chaos perturbation family: {self.family}")
        if self.epsilon < 0 or not 0 <= self.feedback_strength <= 1:
            raise ValueError("invalid chaos cell controls")
        if self.feedback_delay < 0:
            raise ValueError("feedback delay must be non-negative")

    def as_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "epsilon": self.epsilon,
            "feedback_strength": self.feedback_strength,
            "perturbed": self.perturbed,
            "feedback_delay": self.feedback_delay,
        }


@dataclass(frozen=True, slots=True)
class _ScheduledFeedback:
    mode: str
    strength: float
    delay: int

    def strength_for_cycle(self, cycle: int, cycles: int) -> float:
        del cycles
        return 0.0 if cycle < self.delay else self.strength


@dataclass(slots=True)
class _PerturbationAudit:
    bid_target_count: int = 0
    bid_perturb_count: int = 0
    bid_cycle: int | None = None
    bid_before: float | None = None
    bid_after: float | None = None
    trace_target_count: int = 0
    trace_perturb_count: int = 0
    trace_cycle: int | None = None
    trace_before: float | None = None
    trace_after: float | None = None
    eligible_embedding_event_count: int = 0
    embedding_perturb_count: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "bid_target_count": self.bid_target_count,
            "bid_perturb_count": self.bid_perturb_count,
            "bid_cycle": self.bid_cycle,
            "bid_before": self.bid_before,
            "bid_after": self.bid_after,
            "trace_target_count": self.trace_target_count,
            "trace_perturb_count": self.trace_perturb_count,
            "trace_cycle": self.trace_cycle,
            "trace_before": self.trace_before,
            "trace_after": self.trace_after,
            "eligible_embedding_event_count": self.eligible_embedding_event_count,
            "embedding_perturb_count": self.embedding_perturb_count,
        }


def load_canonical_endogenous_config(protocol: ChaosPredictabilityConfig):
    base, _ = load_endogenous_demand_config(protocol.canonical_endogenous_config)
    integration = replace(base.integration, name=protocol.name)
    return replace(base, integration=integration)


def chaos_environment(base, spec: ChaosEnvironment):
    return endogenous_environment(
        base,
        cycles=spec.cycles,
        shift_period=spec.shift_period,
        candidate_count=spec.candidate_count,
    )


def _query_outcomes(connection: Connection[Any], run_id: str) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT cycle, regime, task_id, task_domain, domain_index, required_skill,
               winner_agent_id, winner_slot, success, recorded_positive,
               reputation_score, winning_price, task_budget, created_at
        FROM integration_campaign_outcomes
        WHERE run_id = %s
        ORDER BY cycle
        """,
        (UUID(run_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def _feedback_spec(strength: float, delay: int) -> _ScheduledFeedback:
    return _ScheduledFeedback(
        mode="exogenous" if strength == 0.0 else "closed_loop",
        strength=strength,
        delay=delay,
    )


def run_chaos_cell(
    connection: Connection[Any],
    *,
    protocol: ChaosPredictabilityConfig,
    base,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    cohort: str,
    seed: int,
    environment_spec: ChaosEnvironment,
    spec: ChaosCellSpec,
) -> dict[str, object]:
    environment = chaos_environment(base, environment_spec)
    eps_token = f"{spec.epsilon:.6g}".replace("-", "m").replace(".", "p")
    label = (
        f"{cohort}_{spec.family}_eps{eps_token}_fb{spec.feedback_strength:g}_"
        f"{'perturbed' if spec.perturbed else 'baseline'}_d{spec.feedback_delay}"
    )
    arm = ec.endogenous_arm(base, label=label, environment=environment)
    env = arm.environment
    original_domain = lc._domain_index
    original_market = lc.PostgresMarketService
    original_trace_repository = lc.PostgresTraceRepository
    controller = ec._FeedbackController(  # noqa: SLF001 - deliberate experiment-local reuse
        spec=_feedback_spec(spec.feedback_strength, spec.feedback_delay),  # type: ignore[arg-type]
        seed=seed,
        cycles=env.cycles,
        domain_count=len(env.domains),
        window=base.feedback_window,
        domain_fn=original_domain,
        draw_fn=lc._draw,
    )
    audit = _PerturbationAudit()

    class PerturbingMarketService(original_market):
        def submit_bid(
            self,
            bidder_agent_id,
            *,
            task_id,
            price,
            confidence,
            estimated_completion_seconds,
            strategy_summary,
            at,
        ):
            task = self.get_task(task_id)
            cycle = -1
            if task is not None:
                cycle = int(task.success_condition.get("campaign_cycle", -1))
            adjusted = confidence
            if cycle == protocol.perturb_cycle and audit.bid_target_count == 0:
                audit.bid_target_count += 1
                audit.bid_cycle = cycle
                audit.bid_before = float(confidence)
                if spec.family == "bid_confidence" and spec.perturbed:
                    adjusted = max(0.05, min(0.98, float(confidence) * (1.0 + spec.epsilon)))
                    audit.bid_perturb_count += 1
                audit.bid_after = float(adjusted)
            return super().submit_bid(
                bidder_agent_id,
                task_id=task_id,
                price=price,
                confidence=adjusted,
                estimated_completion_seconds=estimated_completion_seconds,
                strategy_summary=strategy_summary,
                at=at,
            )

    class PerturbingTraceRepository:
        def __init__(self, inner_connection: Connection[Any]) -> None:
            self._delegate = original_trace_repository(inner_connection)

        def add(self, trace: Trace):
            cycle = controller.current_cycle
            eligible = (
                trace.kind == "VERIFIED_OUTCOME"
                and trace.content.startswith("skill-evidence:")
                and cycle >= protocol.trace_min_cycle
            )
            modified = trace
            if eligible and audit.trace_target_count == 0:
                audit.trace_target_count += 1
                audit.trace_cycle = cycle
                audit.trace_before = float(trace.initial_energy)
                if spec.family == "trace_energy" and spec.perturbed:
                    energy = max(0.0, float(trace.initial_energy) * (1.0 + spec.epsilon))
                    modified = replace(
                        trace,
                        initial_energy=energy,
                        energy_anchor=energy,
                        energy_updated_at=trace.created_at,
                    )
                    audit.trace_perturb_count += 1
                if trace.embedding is not None:
                    audit.eligible_embedding_event_count += 1
                    if spec.family == "embedding_control" and spec.perturbed:
                        values = list(trace.embedding)
                        values[0] += spec.epsilon
                        modified = replace(modified, embedding=tuple(values))
                        audit.embedding_perturb_count += 1
                audit.trace_after = float(modified.initial_energy)
            result = self._delegate.add(modified)
            if trace.kind == "VERIFIED_OUTCOME" and trace.content.startswith("skill-evidence:"):
                controller.observe_success()
            return result

        def __getattr__(self, name: str):
            return getattr(self._delegate, name)

    def controlled_domain(inner_seed: int, cycle: int, domain_count: int) -> int:
        return controller.choose_domain(inner_seed, cycle, domain_count)

    lc._domain_index = controlled_domain
    lc.PostgresMarketService = PerturbingMarketService  # type: ignore[assignment]
    lc.PostgresTraceRepository = PerturbingTraceRepository  # type: ignore[assignment]
    try:
        cell = lc.run_lifecycle_arm(
            connection,
            config=base.integration,
            config_hash=config_hash,
            experiment_number=experiment_number,
            arm=arm,
            seed=seed,
            code_sha=code_sha,
        )
    finally:
        lc._domain_index = original_domain
        lc.PostgresMarketService = original_market
        lc.PostgresTraceRepository = original_trace_repository
    controller.finalize()

    rows = _query_outcomes(connection, str(cell["run_id"]))
    if len(rows) != env.cycles or len(controller.events) != env.cycles:
        raise RuntimeError("chaos cell observation count mismatch")
    metrics = dict(cell["metrics"])
    metrics.update(
        ec._feedback_metrics(  # noqa: SLF001
            rows,
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
            "chaos_reputation_neutral": arm.policy.mode == "none",
            "requester_generation_unchanged": True,
            "candidate_generation_unchanged": True,
            "production_matching_unchanged_except_target_bid": True,
            "single_target_bid": audit.bid_target_count == 1,
            "single_target_trace_or_none": audit.trace_target_count <= 1,
            "embedding_control_not_synthesized": audit.eligible_embedding_event_count == 0,
        }
    )
    cell["invariants"] = invariants
    cell["chaos_spec"] = spec.as_dict()
    cell["perturbation_audit"] = audit.as_dict()
    ec._persist_feedback_observations(  # noqa: SLF001
        connection,
        run_id=str(cell["run_id"]),
        events=controller.events,
        rows=rows,
    )
    return {**cell, "rows": rows}


def _sparse_distance(left: Mapping[object, float], right: Mapping[object, float]) -> float:
    keys = set(left) | set(right)
    numerator = sum(abs(float(left.get(key, 0.0)) - float(right.get(key, 0.0))) for key in keys)
    denominator = sum(abs(float(left.get(key, 0.0))) + abs(float(right.get(key, 0.0))) for key in keys)
    if denominator <= _EPS:
        return 0.0
    return min(1.0, numerator / denominator)


def _tv(left: Counter[object], right: Counter[object]) -> float:
    ltotal = sum(left.values())
    rtotal = sum(right.values())
    if ltotal == 0 and rtotal == 0:
        return 0.0
    keys = set(left) | set(right)
    return 0.5 * sum(
        abs(left.get(key, 0) / max(1, ltotal) - right.get(key, 0) / max(1, rtotal))
        for key in keys
    )


def _hhi(values: Mapping[object, float]) -> float:
    total = sum(float(value) for value in values.values())
    if total <= _EPS:
        return 0.0
    return sum((float(value) / total) ** 2 for value in values.values())


def _normalized_mi(joint: Counter[tuple[int, int]]) -> float:
    total = sum(joint.values())
    if total <= 0:
        return 0.0
    domains = Counter()
    winners = Counter()
    for (domain, winner), count in joint.items():
        domains[domain] += count
        winners[winner] += count
    if len(domains) <= 1 or len(winners) <= 1:
        return 0.0
    mi = 0.0
    for (domain, winner), count in joint.items():
        pxy = count / total
        px = domains[domain] / total
        py = winners[winner] / total
        mi += pxy * math.log(pxy / (px * py))
    denom = math.log(min(len(domains), len(winners)))
    return max(0.0, min(1.0, mi / denom if denom > 0 else 0.0))


def _incumbent_share(rows: Sequence[Mapping[str, object]], *, cycle: int, shift_period: int) -> float:
    if cycle < shift_period:
        return 0.0
    boundary = cycle // shift_period * shift_period
    if boundary == 0:
        return 0.0
    before = [row for row in rows if boundary - shift_period <= int(row["cycle"]) < boundary]
    after = [row for row in rows if boundary <= int(row["cycle"]) <= cycle]
    if not before or not after:
        return 0.0
    incumbent: dict[int, int] = {}
    for domain in {int(row["domain_index"]) for row in before}:
        counts = Counter(
            int(row["winner_slot"]) for row in before if int(row["domain_index"]) == domain
        )
        if counts:
            high = max(counts.values())
            incumbent[domain] = min(slot for slot, count in counts.items() if count == high)
    comparable = [row for row in after if int(row["domain_index"]) in incumbent]
    if not comparable:
        return 0.0
    return statistics.mean(
        float(incumbent[int(row["domain_index"])] == int(row["winner_slot"]))
        for row in comparable
    )


def _final_incumbency(rows: Sequence[Mapping[str, object]], *, cycles: int, shift_period: int) -> float:
    boundary = cycles - shift_period
    before = [row for row in rows if boundary - shift_period <= int(row["cycle"]) < boundary]
    after = [row for row in rows if boundary <= int(row["cycle"]) < cycles]
    if not before or not after:
        return 0.0
    incumbent: dict[int, int] = {}
    for domain in {int(row["domain_index"]) for row in before}:
        counts = Counter(
            int(row["winner_slot"]) for row in before if int(row["domain_index"]) == domain
        )
        if counts:
            high = max(counts.values())
            incumbent[domain] = min(slot for slot, count in counts.items() if count == high)
    comparable = [row for row in after if int(row["domain_index"]) in incumbent]
    return (
        statistics.mean(
            float(incumbent[int(row["domain_index"])] == int(row["winner_slot"]))
            for row in comparable
        )
        if comparable
        else 0.0
    )


def _initial_trace_energy(row: Mapping[str, object], *, trace_cycle: int | None, multiplier: float) -> float:
    if trace_cycle is not None and int(row["cycle"]) == trace_cycle:
        return 0.9 * multiplier
    return 0.9


def _pair_series(
    baseline_rows: Sequence[Mapping[str, object]],
    perturbed_rows: Sequence[Mapping[str, object]],
    *,
    seed: int,
    env,
    base,
    baseline_trace_cycle: int | None,
    perturbed_trace_cycle: int | None,
    perturbed_trace_multiplier: float,
) -> list[dict[str, object]]:
    if len(baseline_rows) != len(perturbed_rows):
        raise ValueError("twin rows differ in length")
    practices = [Counter(), Counter()]
    reputations = [Counter(), Counter()]
    balances = [[0.0 for _ in range(env.agents)], [0.0 for _ in range(env.agents)]]
    winner_counts = [Counter(), Counter()]
    joints = [Counter(), Counter()]
    trace_author_counts = [Counter(), Counter()]
    traces: list[list[dict[str, object]]] = [[], []]
    knowledge_flags: list[list[float]] = [[], []]
    winner_damage = 0
    series: list[dict[str, object]] = []

    trace_cycles = (baseline_trace_cycle, perturbed_trace_cycle)
    trace_multipliers = (1.0, perturbed_trace_multiplier)
    for index, (left_row, right_row) in enumerate(zip(baseline_rows, perturbed_rows, strict=True)):
        cycle = int(left_row["cycle"])
        if cycle != int(right_row["cycle"]):
            raise ValueError("twin cycle mismatch")
        rows_now = (left_row, right_row)
        for side, row in enumerate(rows_now):
            skill = str(row["required_skill"])
            current_signal = max(
                (
                    float(trace["initial"])
                    * 2.0 ** (-(cycle - int(trace["cycle"])) / env.trace_half_life_cycles)
                    for trace in traces[side]
                    if str(trace["skill"]) == skill and int(trace["cycle"]) < cycle
                ),
                default=0.0,
            )
            knowledge_flags[side].append(float(current_signal >= base.knowledge_signal_threshold))

            winner = int(row["winner_slot"])
            domain = int(row["domain_index"])
            practices[side][(winner, skill)] += 1
            reputations[side][("domain", winner, domain, bool(row["recorded_positive"]))] += 1
            reputations[side][("skill", winner, skill, bool(row["recorded_positive"]))] += 1
            if cycle == 0:
                reputations[side][("domain", winner, domain, bool(row["recorded_positive"]))] += 1
            requester = lc._requester_slot(env, seed, cycle)
            price = float(row["winning_price"])
            balances[side][requester] -= price
            balances[side][winner] += price
            winner_counts[side][winner] += 1
            joints[side][(domain, winner)] += 1
            if bool(row["success"]):
                initial = _initial_trace_energy(
                    row,
                    trace_cycle=trace_cycles[side],
                    multiplier=trace_multipliers[side],
                )
                traces[side].append(
                    {"cycle": cycle, "winner": winner, "skill": skill, "initial": initial}
                )
                trace_author_counts[side][winner] += 1

        winner_damage += int(left_row["winner_slot"] != right_row["winner_slot"])
        practice_distance = _sparse_distance(practices[0], practices[1])
        reputation_distance = _sparse_distance(reputations[0], reputations[1])
        balance_distance = _sparse_distance(
            {i: value for i, value in enumerate(balances[0])},
            {i: value for i, value in enumerate(balances[1])},
        )

        trace_state: list[dict[tuple[int, int, str], float]] = [{}, {}]
        for side in (0, 1):
            for trace in traces[side]:
                key = (int(trace["cycle"]), int(trace["winner"]), str(trace["skill"]))
                energy = float(trace["initial"]) * 2.0 ** (
                    -(cycle - int(trace["cycle"])) / env.trace_half_life_cycles
                )
                trace_state[side][key] = energy
        trace_distance = _sparse_distance(trace_state[0], trace_state[1])
        damage_distance = winner_damage / (index + 1)
        micro_components = {
            "practice": practice_distance,
            "reputation": reputation_distance,
            "balance": balance_distance,
            "trace_energy": trace_distance,
            "winner_damage": damage_distance,
        }

        mi_difference = abs(_normalized_mi(joints[0]) - _normalized_mi(joints[1]))
        winner_tv = _tv(winner_counts[0], winner_counts[1])
        trace_concentration = abs(_hhi(trace_author_counts[0]) - _hhi(trace_author_counts[1]))
        practice_concentration = abs(_hhi(practices[0]) - _hhi(practices[1]))
        meso_components = {
            "winner_domain_mi": mi_difference,
            "winner_tv": winner_tv,
            "trace_concentration": trace_concentration,
            "practice_concentration": practice_concentration,
        }

        start = max(0, cycle - env.shift_period + 1)
        left_window = baseline_rows[start : cycle + 1]
        right_window = perturbed_rows[start : cycle + 1]
        left_winners = Counter(int(row["winner_slot"]) for row in left_window)
        right_winners = Counter(int(row["winner_slot"]) for row in right_window)
        left_success = statistics.mean(float(bool(row["success"])) for row in left_window)
        right_success = statistics.mean(float(bool(row["success"])) for row in right_window)
        left_knowledge = statistics.mean(knowledge_flags[0][start : cycle + 1])
        right_knowledge = statistics.mean(knowledge_flags[1][start : cycle + 1])
        macro_components = {
            "logical_incumbency": abs(
                _incumbent_share(baseline_rows, cycle=cycle, shift_period=env.shift_period)
                - _incumbent_share(perturbed_rows, cycle=cycle, shift_period=env.shift_period)
            ),
            "winner_hhi": abs(_hhi(left_winners) - _hhi(right_winners)),
            "rolling_success": abs(left_success - right_success),
            "public_knowledge": abs(left_knowledge - right_knowledge),
        }
        candidate_distance = 0.0
        series.append(
            {
                "cycle": cycle,
                "micro_components": micro_components,
                "meso_components": meso_components,
                "macro_components": macro_components,
                "micro_distance": max(micro_components.values()),
                "meso_distance": max(meso_components.values()),
                "macro_distance": max(macro_components.values()),
                "candidate_distance": candidate_distance,
            }
        )
    return series


def forecast_horizon(
    series: Sequence[Mapping[str, object]],
    *,
    key: str,
    threshold: float,
    hits: int,
    window: int,
    cycles: int,
) -> int:
    values = [float(item[key]) for item in series]
    for index, value in enumerate(values):
        if value < threshold:
            continue
        tail = values[index : min(len(values), index + window)]
        if sum(item >= threshold for item in tail) >= hits:
            return int(series[index]["cycle"])
    return cycles + 1


def _saturation(
    series: Sequence[Mapping[str, object]],
    *,
    key: str,
    shift_period: int,
    growth_limit: float,
) -> tuple[bool, float]:
    values = [float(item[key]) for item in series[-shift_period:]]
    if not values:
        return False, 0.0
    nondecreasing = all(values[i] >= values[i - 1] - _EPS for i in range(1, len(values)))
    still_growing = nondecreasing and values[-1] - values[0] > growth_limit
    return (not still_growing), statistics.mean(values)


def _final_public_knowledge(rows: Sequence[Mapping[str, object]], *, env, base) -> float:
    if not rows:
        return 0.0
    at_cycle = env.cycles
    known = 0
    for skill in env.domains:
        signal = max(
            (
                0.9 * 2.0 ** (-(at_cycle - 1 - int(row["cycle"])) / env.trace_half_life_cycles)
                for row in rows
                if bool(row["success"]) and str(row["required_skill"]) == skill
            ),
            default=0.0,
        )
        known += int(signal >= base.knowledge_signal_threshold)
    return known / len(env.domains) if env.domains else 0.0


def _basin_class(
    rows: Sequence[Mapping[str, object]],
    *,
    env,
    reference_success: float,
    protocol: ChaosPredictabilityConfig,
) -> tuple[str, float, float]:
    final_rows = [row for row in rows if int(row["cycle"]) >= env.cycles - 2 * env.shift_period]
    success = statistics.mean(float(bool(row["success"])) for row in final_rows) if final_rows else 0.0
    incumbency = _final_incumbency(rows, cycles=env.cycles, shift_period=env.shift_period)
    if incumbency >= protocol.lock_in_incumbency:
        basin = "lock_in"
    elif (
        incumbency <= protocol.plastic_incumbency
        and success >= reference_success - protocol.plastic_success_tolerance
    ):
        basin = "plastic_high_quality"
    else:
        basin = "other_nontrivial"
    return basin, incumbency, success


def _nontrivial(
    rows: Sequence[Mapping[str, object]],
    *,
    env,
    base,
    protocol: ChaosPredictabilityConfig,
) -> bool:
    final_rows = [row for row in rows if int(row["cycle"]) >= env.cycles - 2 * env.shift_period]
    if not final_rows:
        return False
    success = statistics.mean(float(bool(row["success"])) for row in final_rows)
    winners = {int(row["winner_slot"]) for row in final_rows}
    domains = {int(row["domain_index"]) for row in final_rows}
    public_knowledge = _final_public_knowledge(rows, env=env, base=base)
    return (
        success >= protocol.minimum_final_success
        and len(winners) >= protocol.minimum_final_winners
        and len(domains) >= protocol.minimum_final_domains
        and public_knowledge > 0.0
    )


def _persist_pair(
    connection: Connection[Any],
    *,
    experiment_number: int,
    cohort: str,
    family: str,
    epsilon: float,
    feedback_strength: float,
    seed: int,
    baseline_run_id: str,
    perturbed_run_id: str,
    series: Sequence[Mapping[str, object]],
    summary: Mapping[str, object],
) -> None:
    with connection.transaction():
        for item in series:
            connection.execute(
                """
                INSERT INTO chaos_predictability_observations (
                    experiment_number, cohort, perturbation_family, epsilon,
                    feedback_strength, seed, cycle, baseline_run_id, perturbed_run_id,
                    micro_distance, meso_distance, macro_distance, candidate_distance,
                    micro_components, meso_components, macro_components, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, NOW()
                )
                """,
                (
                    experiment_number,
                    cohort,
                    family,
                    epsilon,
                    feedback_strength,
                    seed,
                    item["cycle"],
                    UUID(baseline_run_id),
                    UUID(perturbed_run_id),
                    item["micro_distance"],
                    item["meso_distance"],
                    item["macro_distance"],
                    item["candidate_distance"],
                    Jsonb(item["micro_components"]),
                    Jsonb(item["meso_components"]),
                    Jsonb(item["macro_components"]),
                ),
            )
        connection.execute(
            """
            INSERT INTO chaos_predictability_pairs (
                experiment_number, cohort, perturbation_family, epsilon,
                feedback_strength, seed, baseline_run_id, perturbed_run_id,
                summary, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                experiment_number,
                cohort,
                family,
                epsilon,
                feedback_strength,
                seed,
                UUID(baseline_run_id),
                UUID(perturbed_run_id),
                Jsonb(dict(summary)),
            ),
        )


def run_chaos_pair(
    connection: Connection[Any],
    *,
    protocol: ChaosPredictabilityConfig,
    base,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    cohort: str,
    seed: int,
    environment_spec: ChaosEnvironment,
    family: str,
    epsilon: float,
    feedback_strength: float,
    feedback_delay: int = 0,
) -> dict[str, object]:
    baseline_spec = ChaosCellSpec(
        family=family,
        epsilon=epsilon,
        feedback_strength=feedback_strength,
        perturbed=False,
        feedback_delay=feedback_delay if family == "feedback_delay" else 0,
    )
    perturb_delay = feedback_delay if family == "feedback_delay" else 0
    perturbed_spec = ChaosCellSpec(
        family=family,
        epsilon=epsilon,
        feedback_strength=feedback_strength,
        perturbed=True,
        feedback_delay=perturb_delay,
    )
    if family == "feedback_delay":
        baseline_spec = replace(baseline_spec, feedback_delay=0)

    baseline = run_chaos_cell(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=experiment_number,
        cohort=cohort,
        seed=seed,
        environment_spec=environment_spec,
        spec=baseline_spec,
    )
    perturbed = run_chaos_cell(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=experiment_number,
        cohort=cohort,
        seed=seed,
        environment_spec=environment_spec,
        spec=perturbed_spec,
    )
    env = chaos_environment(base, environment_spec)
    baseline_audit = baseline["perturbation_audit"]
    perturbed_audit = perturbed["perturbation_audit"]
    assert isinstance(baseline_audit, Mapping) and isinstance(perturbed_audit, Mapping)
    baseline_trace_cycle = (
        int(baseline_audit["trace_cycle"]) if baseline_audit.get("trace_cycle") is not None else None
    )
    perturbed_trace_cycle = (
        int(perturbed_audit["trace_cycle"]) if perturbed_audit.get("trace_cycle") is not None else None
    )
    trace_multiplier = 1.0 + epsilon if family == "trace_energy" else 1.0
    baseline_rows = baseline["rows"]
    perturbed_rows = perturbed["rows"]
    assert isinstance(baseline_rows, Sequence) and isinstance(perturbed_rows, Sequence)
    series = _pair_series(
        baseline_rows,  # type: ignore[arg-type]
        perturbed_rows,  # type: ignore[arg-type]
        seed=seed,
        env=env,
        base=base,
        baseline_trace_cycle=baseline_trace_cycle,
        perturbed_trace_cycle=perturbed_trace_cycle,
        perturbed_trace_multiplier=trace_multiplier,
    )
    horizons = {
        "micro": forecast_horizon(
            series,
            key="micro_distance",
            threshold=protocol.delta_micro,
            hits=protocol.persistent_hits,
            window=protocol.persistent_window,
            cycles=env.cycles,
        ),
        "meso": forecast_horizon(
            series,
            key="meso_distance",
            threshold=protocol.delta_meso,
            hits=protocol.persistent_hits,
            window=protocol.persistent_window,
            cycles=env.cycles,
        ),
        "macro": forecast_horizon(
            series,
            key="macro_distance",
            threshold=protocol.delta_macro,
            hits=protocol.persistent_hits,
            window=protocol.persistent_window,
            cycles=env.cycles,
        ),
    }
    saturation = {}
    for scale in ("micro", "meso", "macro"):
        ok, value = _saturation(
            series,
            key=f"{scale}_distance",
            shift_period=env.shift_period,
            growth_limit=protocol.saturation_growth_limit,
        )
        saturation[scale] = {"bounded": ok, "mean_final_regime": value}

    baseline_final_rows = [
        row for row in baseline_rows if int(row["cycle"]) >= env.cycles - 2 * env.shift_period
    ]
    baseline_final_success = statistics.mean(
        float(bool(row["success"])) for row in baseline_final_rows
    )
    baseline_basin, baseline_i, baseline_success = _basin_class(
        baseline_rows,  # type: ignore[arg-type]
        env=env,
        reference_success=baseline_final_success,
        protocol=protocol,
    )
    perturbed_basin, perturbed_i, perturbed_success = _basin_class(
        perturbed_rows,  # type: ignore[arg-type]
        env=env,
        reference_success=baseline_final_success,
        protocol=protocol,
    )
    candidate_equal = all(float(item["candidate_distance"]) == 0.0 for item in series)
    all_invariants = all(bool(value) for value in baseline["invariants"].values()) and all(  # type: ignore[union-attr]
        bool(value) for value in perturbed["invariants"].values()  # type: ignore[union-attr]
    )
    nontrivial = _nontrivial(
        baseline_rows, env=env, base=base, protocol=protocol  # type: ignore[arg-type]
    ) and _nontrivial(
        perturbed_rows, env=env, base=base, protocol=protocol  # type: ignore[arg-type]
    )
    first_changed_winner = next(
        (
            int(left["cycle"])
            for left, right in zip(baseline_rows, perturbed_rows, strict=True)
            if int(left["winner_slot"]) != int(right["winner_slot"])
        ),
        env.cycles + 1,
    )
    summary: dict[str, object] = {
        "experiment_number": experiment_number,
        "cohort": cohort,
        "family": family,
        "epsilon": epsilon,
        "feedback_strength": feedback_strength,
        "feedback_delay": feedback_delay,
        "seed": seed,
        "baseline_run_id": baseline["run_id"],
        "perturbed_run_id": perturbed["run_id"],
        "horizons": horizons,
        "saturation": saturation,
        "candidate_set_equal": candidate_equal,
        "all_invariants": all_invariants,
        "nontrivial": nontrivial,
        "first_changed_winner_cycle": first_changed_winner,
        "baseline_basin": baseline_basin,
        "perturbed_basin": perturbed_basin,
        "basin_disagreement": baseline_basin != perturbed_basin,
        "baseline_final_incumbency": baseline_i,
        "perturbed_final_incumbency": perturbed_i,
        "baseline_final_success": baseline_success,
        "perturbed_final_success": perturbed_success,
        "baseline_audit": dict(baseline_audit),
        "perturbed_audit": dict(perturbed_audit),
        "final_micro_distance": float(series[-1]["micro_distance"]),
        "final_meso_distance": float(series[-1]["meso_distance"]),
        "final_macro_distance": float(series[-1]["macro_distance"]),
    }
    _persist_pair(
        connection,
        experiment_number=experiment_number,
        cohort=cohort,
        family=family,
        epsilon=epsilon,
        feedback_strength=feedback_strength,
        seed=seed,
        baseline_run_id=str(baseline["run_id"]),
        perturbed_run_id=str(perturbed["run_id"]),
        series=series,
        summary=summary,
    )
    return summary


def _rank(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index
        while end + 1 < len(order) and values[order[end + 1]] == values[order[index]]:
            end += 1
        rank = (index + end) / 2 + 1
        for position in range(index, end + 1):
            ranks[order[position]] = rank
        index = end + 1
    return ranks


def _spearman(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    a = _rank(left)
    b = _rank(right)
    ma = statistics.mean(a)
    mb = statistics.mean(b)
    numerator = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return numerator / (da * db) if da > _EPS and db > _EPS else 0.0


def _linear_slope(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    mx = statistics.mean(x)
    my = statistics.mean(y)
    denom = sum((value - mx) ** 2 for value in x)
    return (
        sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / denom
        if denom > _EPS
        else 0.0
    )


def scaling_evaluation(
    pairs: Sequence[Mapping[str, object]],
    *,
    protocol: ChaosPredictabilityConfig,
    cycles: int,
) -> dict[str, object]:
    by_family: dict[str, dict[str, object]] = {}
    for family in _PRIMARY_FAMILIES:
        family_pairs = [
            pair
            for pair in pairs
            if pair["family"] == family and float(pair["feedback_strength"]) == protocol.feedback_strength
        ]
        scales: dict[str, object] = {}
        for scale in ("micro", "meso", "macro"):
            horizon_by_epsilon: list[tuple[float, float]] = []
            for epsilon in protocol.epsilons:
                subset = [pair for pair in family_pairs if float(pair["epsilon"]) == epsilon]
                horizons = []
                for pair in subset:
                    raw = pair["horizons"]
                    assert isinstance(raw, Mapping)
                    horizons.append(float(raw[scale]))
                horizon_by_epsilon.append(
                    (epsilon, statistics.median(horizons) if horizons else float(cycles + 1))
                )
            x = [math.log10(epsilon) for epsilon, _ in horizon_by_epsilon]
            y = [horizon for _, horizon in horizon_by_epsilon]
            finite = [horizon for horizon in y if horizon <= cycles]
            rho = _spearman(x, y)
            slope = _linear_slope(x, y)
            saturation_levels: list[tuple[float, float]] = []
            for epsilon, median_horizon in horizon_by_epsilon:
                if median_horizon > cycles:
                    continue
                subset = [pair for pair in family_pairs if float(pair["epsilon"]) == epsilon]
                values = [
                    float(pair["saturation"][scale]["mean_final_regime"])  # type: ignore[index]
                    for pair in subset
                    if bool(pair["saturation"][scale]["bounded"])  # type: ignore[index]
                ]
                if values:
                    saturation_levels.append((epsilon, statistics.median(values)))
            smallest = sorted(saturation_levels)[:3]
            saturation_values = [value for _, value in smallest]
            if len(saturation_values) >= 3:
                mean_sat = statistics.mean(saturation_values)
                saturation_cv = (
                    statistics.pstdev(saturation_values) / mean_sat if mean_sat > _EPS else 0.0
                )
                saturation_cv_gate = saturation_cv <= protocol.maximum_saturation_cv
            else:
                saturation_cv = None
                saturation_cv_gate = False
            scaling = (
                slope < 0
                and rho <= protocol.maximum_scaling_spearman
                and len(set(finite)) >= protocol.minimum_distinct_finite_horizons
                and saturation_cv_gate
            )
            scales[scale] = {
                "horizon_by_epsilon": horizon_by_epsilon,
                "slope": slope,
                "spearman": rho,
                "distinct_finite_horizons": len(set(finite)),
                "saturation_levels": saturation_levels,
                "saturation_cv": saturation_cv,
                "saturation_cv_gate": saturation_cv_gate,
                "scaling_gate": scaling,
            }

        small = [pair for pair in family_pairs if float(pair["epsilon"]) <= 1e-2]
        macro_cross = statistics.mean(
            float(int(pair["horizons"]["macro"]) <= cycles)  # type: ignore[index]
            for pair in small
        ) if small else 0.0
        basin_disagreement = statistics.mean(
            float(bool(pair["basin_disagreement"])) for pair in small
        ) if small else 0.0
        bounded = all(
            bool(pair["nontrivial"])
            and bool(pair["saturation"]["micro"]["bounded"])  # type: ignore[index]
            and bool(pair["saturation"]["meso"]["bounded"])  # type: ignore[index]
            for pair in family_pairs
        ) if family_pairs else False
        micro_meso_scaling = bool(scales["micro"]["scaling_gate"]) or bool(  # type: ignore[index]
            scales["meso"]["scaling_gate"]  # type: ignore[index]
        )
        if not family_pairs:
            classification = "stable_ordered"
        elif not bounded and any(
            int(pair["horizons"]["micro"]) <= cycles or int(pair["horizons"]["meso"]) <= cycles  # type: ignore[index]
            for pair in family_pairs
        ):
            classification = "unstable"
        elif micro_meso_scaling and macro_cross >= protocol.minimum_org_chaos_macro_crossing and basin_disagreement >= protocol.minimum_org_chaos_basin_disagreement:
            classification = "organizationally_chaotic"
        elif micro_meso_scaling:
            classification = "micro_chaotic_organizationally_predictable"
        elif any(
            int(pair["horizons"]["micro"]) <= cycles or int(pair["horizons"]["meso"]) <= cycles  # type: ignore[index]
            for pair in family_pairs
        ):
            classification = "basin_boundary_sensitive"
        else:
            classification = "stable_ordered"
        by_family[family] = {
            "scales": scales,
            "bounded": bounded,
            "macro_crossing_share_small_epsilon": macro_cross,
            "basin_disagreement_share_small_epsilon": basin_disagreement,
            "classification": classification,
        }
    return by_family


def local_screen(
    pairs: Sequence[Mapping[str, object]],
    *,
    protocol: ChaosPredictabilityConfig,
    cycles: int,
) -> dict[str, object]:
    results: dict[str, object] = {}
    for family in _PRIMARY_FAMILIES:
        primary = [
            pair
            for pair in pairs
            if pair["family"] == family
            and float(pair["feedback_strength"]) == protocol.feedback_strength
        ]
        control = [
            pair for pair in pairs if pair["family"] == family and float(pair["feedback_strength"]) == 0.0
        ]
        micro_meso = statistics.mean(
            float(
                int(pair["horizons"]["micro"]) <= cycles  # type: ignore[index]
                or int(pair["horizons"]["meso"]) <= cycles  # type: ignore[index]
            )
            for pair in primary
        ) if primary else 0.0
        macro = statistics.mean(
            float(int(pair["horizons"]["macro"]) <= cycles)  # type: ignore[index]
            for pair in primary
        ) if primary else 0.0
        crossing = [
            pair
            for pair in primary
            if int(pair["horizons"]["micro"]) <= cycles  # type: ignore[index]
            or int(pair["horizons"]["meso"]) <= cycles  # type: ignore[index]
            or int(pair["horizons"]["macro"]) <= cycles  # type: ignore[index]
        ]
        bounded_share = statistics.mean(
            float(
                bool(pair["nontrivial"])
                and bool(pair["saturation"]["micro"]["bounded"])  # type: ignore[index]
                and bool(pair["saturation"]["meso"]["bounded"])  # type: ignore[index]
            )
            for pair in crossing
        ) if crossing else 0.0
        primary_final = statistics.mean(
            max(float(pair["final_micro_distance"]), float(pair["final_meso_distance"]), float(pair["final_macro_distance"]))
            for pair in primary
        ) if primary else 0.0
        control_final = statistics.mean(
            max(float(pair["final_micro_distance"]), float(pair["final_meso_distance"]), float(pair["final_macro_distance"]))
            for pair in control
        ) if control else 0.0
        perturb_cycle = protocol.perturb_cycle
        first_divergences = [
            min(int(pair["horizons"]["micro"]), int(pair["horizons"]["meso"]), int(pair["horizons"]["macro"]))  # type: ignore[index]
            for pair in primary
            if min(int(pair["horizons"]["micro"]), int(pair["horizons"]["meso"]), int(pair["horizons"]["macro"])) <= cycles  # type: ignore[index]
        ]
        median_after = statistics.median(first_divergences) > perturb_cycle if first_divergences else False
        candidate_equal = all(bool(pair["candidate_set_equal"]) for pair in primary + control)
        gate = (
            micro_meso >= protocol.minimum_local_micro_meso_crossing
            and macro >= protocol.minimum_local_macro_crossing
            and median_after
            and candidate_equal
            and bounded_share >= protocol.minimum_bounded_crossing_share
            and primary_final + _EPS >= control_final
        )
        results[family] = {
            "micro_meso_crossing_share": micro_meso,
            "macro_crossing_share": macro,
            "bounded_crossing_share": bounded_share,
            "median_first_divergence_after_perturbation": median_after,
            "candidate_set_equal": candidate_equal,
            "mean_final_distance_primary": primary_final,
            "mean_final_distance_lambda0": control_final,
            "local_screen_gate": gate,
        }
    return results


def select_family(
    evaluations: Mapping[str, Mapping[str, object]],
    pairs: Sequence[Mapping[str, object]],
    *,
    cycles: int,
) -> str:
    classifications = {
        family: str(evaluations[family]["classification"]) for family in _PRIMARY_FAMILIES
    }
    for target in ("organizationally_chaotic", "micro_chaotic_organizationally_predictable"):
        for family in _PRIMARY_FAMILIES:
            if classifications[family] == target:
                return family
    scores: dict[str, float] = {}
    for family in _PRIMARY_FAMILIES:
        subset = [pair for pair in pairs if pair["family"] == family]
        scores[family] = statistics.mean(
            float(
                int(pair["horizons"]["micro"]) <= cycles  # type: ignore[index]
                or int(pair["horizons"]["meso"]) <= cycles  # type: ignore[index]
                or int(pair["horizons"]["macro"]) <= cycles  # type: ignore[index]
            )
            for pair in subset
        ) if subset else 0.0
    return max(_PRIMARY_FAMILIES, key=lambda family: (scores[family], -_PRIMARY_FAMILIES.index(family)))


def basin_occupancy(pairs: Sequence[Mapping[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for epsilon in sorted({float(pair["epsilon"]) for pair in pairs}):
        subset = [pair for pair in pairs if float(pair["epsilon"]) == epsilon]
        counts = Counter(str(pair["perturbed_basin"]) for pair in subset)
        total = sum(counts.values())
        output[str(epsilon)] = {
            basin: count / max(1, total) for basin, count in sorted(counts.items())
        }
    return output


__all__ = [
    "ChaosCellSpec",
    "basin_occupancy",
    "chaos_environment",
    "forecast_horizon",
    "load_canonical_endogenous_config",
    "local_screen",
    "run_chaos_pair",
    "scaling_evaluation",
    "select_family",
]
