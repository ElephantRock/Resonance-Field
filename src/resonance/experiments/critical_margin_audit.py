"""Existing-evidence critical-margin audit for Resonance Field Experiments 105–128.

This module reconstructs only already-executed historical cells.  It does not add a seed,
feedback strength, epsilon, perturbation location, or causal intervention.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import Connection

from . import lifecycle_campaign as lc
from .chaos_predictability_campaign import (
    chaos_environment,
    load_canonical_endogenous_config,
    run_chaos_pair,
)
from .chaos_predictability_config import ChaosPredictabilityConfig
from .endogenous_demand_config import EndogenousDemandConfig
from .endogenous_demand_heterogeneity import _reconstruct_pair

_CANONICAL_CHAOS_SHA = "060084ec662ebb7f46f248f05e45e1f722e8da63"
_SELECTED_FEEDBACK = 0.5
_REPLAY_EPSILONS = (1e-6, 1e-4, 1e-2, 0.1, 1.0)
_EPS = 1e-12
_INF = float("inf")


def _finite(value: float | None) -> float:
    if value is None or not math.isfinite(value):
        return _INF
    return float(value)


def _spearman(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0

    def ranks(values: Sequence[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        result = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                result[order[k]] = rank
            i = j + 1
        return result

    a = ranks(left)
    b = ranks(right)
    ma = statistics.mean(a)
    mb = statistics.mean(b)
    numerator = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return numerator / (da * db) if da > _EPS and db > _EPS else 0.0


def _query_outcomes(connection: Connection[Any], run_id: str) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT cycle, regime, task_id, domain_index, task_domain, required_skill,
               winner_slot, winner_agent_id, success, recorded_positive,
               winning_price, task_budget, created_at
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
               feedback_strength, rolling_success_counts, feedback_branch_taken
        FROM endogenous_demand_observations
        WHERE run_id = %s
        ORDER BY cycle
        """,
        (UUID(run_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def _query_auctions(connection: Connection[Any], run_id: str) -> dict[int, list[dict[str, object]]]:
    rows = connection.execute(
        """
        SELECT o.cycle, o.created_at, b.bidder_agent_id, b.confidence, b.price,
               b.estimated_completion_seconds, b.submitted_at,
               s.total_score, s.selected
        FROM integration_campaign_outcomes o
        JOIN market_auction_scores s ON s.task_id = o.task_id
        JOIN market_bids b ON b.bid_id = s.bid_id
        WHERE o.run_id = %s
        ORDER BY o.cycle, s.total_score DESC, b.submitted_at, b.bid_id
        """,
        (UUID(run_id),),
    ).fetchall()
    by_cycle: dict[int, list[dict[str, object]]] = defaultdict(list)
    for raw in rows:
        row = dict(raw)
        created = row["created_at"]
        submitted = row["submitted_at"]
        offset_us = round((submitted - created).total_seconds() * 1_000_000)  # type: ignore[operator]
        row["candidate_slot"] = int(offset_us) - 1
        by_cycle[int(row["cycle"])].append(row)
    return dict(by_cycle)


def _auction_radius(auction_rows: Sequence[Mapping[str, object]]) -> float:
    """Minimum relative confidence increase of a loser needed to reach the winner score."""
    if len(auction_rows) < 2:
        return _INF
    winner = next((row for row in auction_rows if bool(row["selected"])), auction_rows[0])
    winning_score = float(winner["total_score"])
    radii: list[float] = []
    for row in auction_rows:
        if bool(row["selected"]):
            continue
        confidence = float(row["confidence"])
        gap = max(0.0, winning_score - float(row["total_score"]))
        if gap <= _EPS:
            radii.append(0.0)
            continue
        needed_confidence = gap / 0.45
        if confidence <= _EPS or confidence + needed_confidence > 0.98 + _EPS:
            continue
        radii.append(needed_confidence / confidence)
    return min(radii) if radii else _INF


def _target_bid_radius(
    auction_rows: Sequence[Mapping[str, object]], *, target_slot: int
) -> float:
    if len(auction_rows) < 2:
        return _INF
    winner = next((row for row in auction_rows if bool(row["selected"])), auction_rows[0])
    target = next(
        (row for row in auction_rows if int(row["candidate_slot"]) == target_slot),
        None,
    )
    if target is None or bool(target["selected"]):
        return _INF
    confidence = float(target["confidence"])
    gap = max(0.0, float(winner["total_score"]) - float(target["total_score"]))
    if gap <= _EPS:
        return 0.0
    needed = gap / 0.45
    if confidence <= _EPS or confidence + needed > 0.98 + _EPS:
        return _INF
    return needed / confidence


def _trace_energy(
    *,
    current_cycle: int,
    trace_cycle: int,
    initial: float,
    env,
) -> float:
    delta_seconds = (
        (current_cycle - trace_cycle) * env.cycle_seconds
        - (env.bid_deadline_seconds + 1)
    )
    elapsed = max(0.0, float(delta_seconds))
    half_life = env.trace_half_life_cycles * env.cycle_seconds
    return float(initial) * 2.0 ** (-elapsed / half_life)


def _trace_diagnostics(
    rows: Sequence[Mapping[str, object]],
    *,
    current_cycle: int,
    required_skill: str,
    candidates: Sequence[int],
    env,
) -> tuple[float, float]:
    traces: list[tuple[int, int, str, float]] = []
    for row in rows:
        cycle = int(row["cycle"])
        if cycle >= current_cycle:
            break
        if bool(row["success"]):
            traces.append((cycle, int(row["winner_slot"]), str(row["required_skill"]), 0.9))

    gate_radii: list[float] = []
    rank_radii: list[float] = []
    for candidate in candidates:
        energies = sorted(
            (
                _trace_energy(
                    current_cycle=current_cycle,
                    trace_cycle=cycle,
                    initial=initial,
                    env=env,
                )
                for cycle, author, skill, initial in traces
                if author == candidate and skill == required_skill
            ),
            reverse=True,
        )
        if energies:
            signal = energies[0]
            if signal > _EPS:
                gate_radii.append(abs(0.20 - signal) / signal)
        if len(energies) >= 2 and energies[1] > _EPS:
            rank_radii.append(max(0.0, energies[0] / energies[1] - 1.0))

    public = sorted(
        (
            _trace_energy(
                current_cycle=current_cycle,
                trace_cycle=cycle,
                initial=initial,
                env=env,
            )
            for cycle, _author, skill, initial in traces
            if skill == required_skill
        ),
        reverse=True,
    )
    if len(public) >= 2 and public[1] > _EPS:
        rank_radii.append(max(0.0, public[0] / public[1] - 1.0))
    return (
        min(gate_radii) if gate_radii else _INF,
        min(rank_radii) if rank_radii else _INF,
    )


def _feedback_domain_radius(
    event: Mapping[str, object] | None,
    *,
    seed: int,
    cycle: int,
) -> tuple[float, float]:
    if event is None:
        return _INF, _INF
    strength = float(event.get("feedback_strength", 0.0))
    switch_draw = lc._draw(seed, cycle, 0, "endogenous-demand-switch")
    exogenous_switch_margin = abs(switch_draw - strength)
    if not bool(event.get("feedback_branch_taken")):
        return _INF, exogenous_switch_margin
    raw = event.get("rolling_success_counts")
    if not isinstance(raw, Sequence):
        return _INF, exogenous_switch_margin
    counts = [int(value) for value in raw]
    total = sum(counts)
    if total <= 0 or len(counts) <= 1:
        return _INF, exogenous_switch_margin
    draw = lc._draw(seed, cycle, 0, "endogenous-demand-domain")
    cumulative = 0.0
    margins: list[float] = []
    for count in counts[:-1]:
        cumulative += count / total
        margins.append(abs(draw - cumulative))
    return (min(margins) if margins else _INF), exogenous_switch_margin


def margin_series(
    connection: Connection[Any],
    *,
    run_id: str,
    seed: int,
    env,
) -> list[dict[str, object]]:
    rows = _query_outcomes(connection, run_id)
    feedback = {int(item["cycle"]): item for item in _query_feedback(connection, run_id)}
    auctions = _query_auctions(connection, run_id)
    practice: Counter[tuple[int, str]] = Counter()
    result: list[dict[str, object]] = []

    for row in rows:
        cycle = int(row["cycle"])
        required_skill = str(row["required_skill"])
        winner = int(row["winner_slot"])
        candidates = lc._candidate_slots(
            seed,
            cycle,
            agents=env.agents,
            requester_slot=lc._requester_slot(env, seed, cycle),
            count=env.candidate_count,
        )
        auction_radius = _auction_radius(auctions.get(cycle, ()))
        gate_radius, rank_radius = _trace_diagnostics(
            rows,
            current_cycle=cycle,
            required_skill=required_skill,
            candidates=candidates,
            env=env,
        )
        practiced = practice[(winner, required_skill)]
        probability = min(
            env.maximum_success_probability,
            env.base_success_probability + env.practice_gain * math.sqrt(practiced),
        )
        outcome_draw = lc._draw(seed, cycle, winner, "outcome")
        success_radius = abs(outcome_draw - probability)
        feedback_radius, switch_margin = _feedback_domain_radius(
            feedback.get(cycle), seed=seed, cycle=cycle
        )
        consequential = min(auction_radius, success_radius, feedback_radius)
        all_radius = min(consequential, gate_radius, rank_radius)
        result.append(
            {
                "cycle": cycle,
                "r_auction": auction_radius,
                "r_success": success_radius,
                "r_feedback_domain": feedback_radius,
                "r_feedback_switch_exogenous": switch_margin,
                "r_trace_gate": gate_radius,
                "r_trace_rank": rank_radius,
                "r_min_consequential": consequential,
                "r_min_all": all_radius,
                "forcing_phase": (cycle % env.shift_period) / env.shift_period,
            }
        )
        practice[(winner, required_skill)] += 1
    return result


def _summary_at(series: Sequence[Mapping[str, object]], cycle: int) -> dict[str, float]:
    subset = [item for item in series if int(item["cycle"]) <= cycle]
    values = sorted(
        float(item["r_min_consequential"])
        for item in subset
        if math.isfinite(float(item["r_min_consequential"]))
    )
    if not values:
        return {
            "median_r_min": _INF,
            "lower_decile_r_min": _INF,
            "near_0_10": 0.0,
            "near_0_01": 0.0,
        }
    index = max(0, math.ceil(0.10 * len(values)) - 1)
    return {
        "median_r_min": statistics.median(values),
        "lower_decile_r_min": values[index],
        "near_0_10": sum(value <= 0.10 for value in values) / len(values),
        "near_0_01": sum(value <= 0.01 for value in values) / len(values),
    }


def _series_trend(series: Sequence[Mapping[str, object]]) -> float:
    finite = [
        (int(item["cycle"]), float(item["r_min_consequential"]))
        for item in series
        if math.isfinite(float(item["r_min_consequential"]))
    ]
    if len(finite) < 3:
        return 0.0
    return _spearman([float(cycle) for cycle, _ in finite], [value for _, value in finite])


def _first_success_eligible(rows: Sequence[Mapping[str, object]], *, cycles: int) -> int:
    for row in rows:
        if bool(row["success"]):
            return min(cycles, int(row["cycle"]) + 1)
    return cycles


def _first_override(events: Sequence[Mapping[str, object]], *, cycles: int) -> int:
    return min(
        (
            int(event["cycle"])
            for event in events
            if int(event["generated_domain_index"]) != int(event["baseline_domain_index"])
        ),
        default=cycles,
    )


def _point_geometry(series: Sequence[Mapping[str, object]], cycle: int) -> dict[str, float]:
    if not series:
        return {}
    item = next((row for row in series if int(row["cycle"]) == cycle), series[-1])
    return {
        key: float(item[key])
        for key in (
            "r_auction",
            "r_success",
            "r_feedback_domain",
            "r_trace_gate",
            "r_trace_rank",
            "r_min_consequential",
            "forcing_phase",
        )
    }


def _auction_snapshot_from_state(
    rows: Sequence[Mapping[str, object]],
    *,
    seed: int,
    cycle: int,
    env,
    base: EndogenousDemandConfig,
    trace_target: tuple[int, int, str] | None = None,
    trace_epsilon: float = 0.0,
) -> list[tuple[float, int, float]]:
    required_skill = str(rows[cycle]["required_skill"])
    candidates = lc._candidate_slots(
        seed,
        cycle,
        agents=env.agents,
        requester_slot=lc._requester_slot(env, seed, cycle),
        count=env.candidate_count,
    )
    traces: list[tuple[int, int, str, float]] = []
    for row in rows[:cycle]:
        if not bool(row["success"]):
            continue
        key = (int(row["cycle"]), int(row["winner_slot"]), str(row["required_skill"]))
        initial = 0.9 * (1.0 + trace_epsilon) if trace_target == key else 0.9
        traces.append((*key, initial))

    def energy(item: tuple[int, int, str, float]) -> float:
        return _trace_energy(
            current_cycle=cycle,
            trace_cycle=item[0],
            initial=item[3],
            env=env,
        )

    public_signal = max(
        (energy(item) for item in traces if item[2] == required_skill),
        default=0.0,
    )
    public_signal = max(0.0, min(1.0, public_signal))
    scored: list[tuple[float, int, float]] = []
    for slot in candidates:
        own_signal = max(
            (energy(item) for item in traces if item[1] == slot and item[2] == required_skill),
            default=0.0,
        )
        confidence = (
            env.confidence_base
            + env.confidence_evidence_weight * own_signal
            + base.public_trace_confidence_weight * public_signal
            + env.confidence_noise_weight * lc._draw(seed, cycle, slot, "confidence")
        )
        if own_signal < 0.20:
            confidence += env.confidence_inflation
        confidence = max(0.05, min(0.98, confidence))
        price_fraction = env.price_floor + env.price_span * lc._draw(seed, cycle, slot, "price")
        price = max(1, min(env.task_budget, int(env.task_budget * min(0.95, price_fraction))))
        completion = env.completion_min_seconds + int(
            env.completion_span_seconds * lc._draw(seed, cycle, slot, "speed")
        )
        completion = min(max(1, completion), env.bid_deadline_seconds - 1)
        price_efficiency = 1.0 - price / env.task_budget
        speed = 1.0 - min(1.0, completion / env.bid_deadline_seconds)
        score = 0.45 * confidence + 0.35 * price_efficiency + 0.20 * speed
        scored.append((score, slot, confidence))
    return sorted(scored, key=lambda item: (-item[0], item[1]))


def _critical_trace_epsilon(
    rows: Sequence[Mapping[str, object]],
    *,
    seed: int,
    cycle: int,
    env,
    base: EndogenousDemandConfig,
    trace_target: tuple[int, int, str],
    lower: float,
    upper: float,
) -> tuple[float | None, bool]:
    baseline = _auction_snapshot_from_state(
        rows, seed=seed, cycle=cycle, env=env, base=base, trace_target=trace_target
    )
    if not baseline:
        return None, False
    baseline_winner = baseline[0][1]

    def changed(epsilon: float) -> bool:
        snapshot = _auction_snapshot_from_state(
            rows,
            seed=seed,
            cycle=cycle,
            env=env,
            base=base,
            trace_target=trace_target,
            trace_epsilon=epsilon,
        )
        return bool(snapshot) and snapshot[0][1] != baseline_winner

    if changed(lower):
        return lower, True
    if not changed(upper):
        return None, True
    lo, hi = lower, upper
    # Counterfactual score reconstruction only; no additional simulation cell is generated.
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if changed(mid):
            hi = mid
        else:
            lo = mid
    return hi, True


def _replay_chaos_pairs(
    connection: Connection[Any],
    *,
    protocol: ChaosPredictabilityConfig,
    config_hash: str,
) -> list[dict[str, object]]:
    base = load_canonical_endogenous_config(protocol)
    plans = (
        ("discovery", protocol.discovery_seeds, protocol.standard, ("bid_confidence", "trace_energy")),
        ("replication", protocol.replication_seeds, protocol.standard, ("trace_energy",)),
        ("holdout", protocol.holdout_seeds, protocol.holdout, ("trace_energy",)),
    )
    result: list[dict[str, object]] = []
    for cohort_kind, seeds, environment_spec, families in plans:
        for family in families:
            for epsilon in _REPLAY_EPSILONS:
                if cohort_kind == "discovery" and epsilon == protocol.epsilons[0]:
                    experiment_number = 124
                    cohort = "discovery_local"
                elif cohort_kind == "discovery":
                    experiment_number = 125
                    cohort = "discovery_scaling"
                elif cohort_kind == "replication":
                    experiment_number = 127
                    cohort = "replication"
                else:
                    experiment_number = 128
                    cohort = "holdout"
                for seed in seeds:
                    result.append(
                        run_chaos_pair(
                            connection,
                            protocol=protocol,
                            base=base,
                            config_hash=config_hash,
                            code_sha=_CANONICAL_CHAOS_SHA,
                            experiment_number=experiment_number,
                            cohort=cohort,
                            seed=seed,
                            environment_spec=environment_spec,
                            family=family,
                            epsilon=epsilon,
                            feedback_strength=protocol.feedback_strength,
                        )
                    )
    return result


def _chaos_attribution(
    connection: Connection[Any],
    *,
    protocol: ChaosPredictabilityConfig,
    chaos_config_hash: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    base = load_canonical_endogenous_config(protocol)
    pairs = _replay_chaos_pairs(connection, protocol=protocol, config_hash=chaos_config_hash)

    def normalized_cohort(pair: Mapping[str, object]) -> str:
        value = str(pair["cohort"])
        return "discovery" if value in {"discovery_local", "discovery_scaling"} else value

    by_key = {
        (normalized_cohort(pair), int(pair["seed"]), str(pair["family"]), float(pair["epsilon"])): pair
        for pair in pairs
    }
    attributions: list[dict[str, object]] = []
    baseline_series: list[dict[str, object]] = []
    series_rows: list[dict[str, object]] = []

    cohort_env = {
        "discovery": protocol.standard,
        "replication": protocol.standard,
        "holdout": protocol.holdout,
    }
    for cohort, seeds in (
        ("discovery", protocol.discovery_seeds),
        ("replication", protocol.replication_seeds),
        ("holdout", protocol.holdout_seeds),
    ):
        env_spec = cohort_env[cohort]
        env = chaos_environment(base, env_spec)
        for seed in seeds:
            # Use the historical epsilon=0.1 trace-energy baseline as the unperturbed path.
            baseline_pair = by_key[(cohort, seed, "trace_energy", 0.1)]
            run_id = str(baseline_pair["baseline_run_id"])
            series = margin_series(connection, run_id=run_id, seed=seed, env=env)
            trend = _series_trend(series)
            checkpoints = {str(c): _summary_at(series, min(c, env.cycles - 1)) for c in (10, 20, 30, 40)}
            baseline_series.append(
                {
                    "cohort": cohort,
                    "seed": seed,
                    "run_id": run_id,
                    "trend_spearman": trend,
                    "checkpoints": checkpoints,
                }
            )
            for item in series:
                series_rows.append({"cohort": cohort, "seed": seed, **dict(item)})

    groups: dict[tuple[str, int, str], list[dict[str, object]]] = defaultdict(list)
    for pair in pairs:
        groups[(normalized_cohort(pair), int(pair["seed"]), str(pair["family"]))].append(pair)

    for (cohort, seed, family), family_pairs in sorted(groups.items()):
        env_spec = cohort_env[cohort]
        env = chaos_environment(base, env_spec)
        sentinel = env.cycles + 1
        ordered = sorted(family_pairs, key=lambda item: float(item["epsilon"]))
        changed = [item for item in ordered if int(item["first_changed_winner_cycle"]) < sentinel]
        if changed:
            upper_pair = changed[0]
            upper = float(upper_pair["epsilon"])
            index = ordered.index(upper_pair)
            lower_pair = ordered[index - 1] if index > 0 else None
            lower = float(lower_pair["epsilon"]) if lower_pair is not None else 0.0
            lower_changed = bool(
                lower_pair is not None and int(lower_pair["first_changed_winner_cycle"]) < sentinel
            )
            first = int(upper_pair["first_changed_winner_cycle"])
        else:
            upper_pair = ordered[-1]
            upper = float(upper_pair["epsilon"])
            lower_pair = ordered[-2] if len(ordered) > 1 else None
            lower = float(lower_pair["epsilon"]) if lower_pair is not None else 0.0
            lower_changed = False
            first = sentinel

        upper_changed = first < sentinel
        record: dict[str, object] = {
            "cohort": cohort,
            "seed": seed,
            "family": family,
            "lower_epsilon": lower,
            "upper_epsilon": upper,
            "lower_changed": lower_changed,
            "upper_changed": upper_changed,
            "first_discrete_divergence_cycle": first if upper_changed else None,
            "attributed_surface": None,
            "critical_radius": None,
            "bracket_valid": False,
            "reconstruction_valid": bool(upper_pair["all_invariants"])
            and bool(upper_pair["candidate_set_equal"]),
        }
        baseline_rows = _query_outcomes(connection, str(upper_pair["baseline_run_id"]))
        if family == "bid_confidence":
            target_slot = lc._candidate_slots(
                seed,
                protocol.perturb_cycle,
                agents=env.agents,
                requester_slot=lc._requester_slot(env, seed, protocol.perturb_cycle),
                count=env.candidate_count,
            )[0]
            auction = _query_auctions(connection, str(upper_pair["baseline_run_id"]))
            radius = _target_bid_radius(auction.get(protocol.perturb_cycle, ()), target_slot=target_slot)
            record["critical_radius"] = radius if math.isfinite(radius) else None
            record["attributed_surface"] = "auction_argmax" if upper_changed else "no_crossing_within_grid"
            if upper_changed and math.isfinite(radius):
                record["bracket_valid"] = radius > lower - 1e-9 and radius <= upper + 1e-9
            else:
                record["bracket_valid"] = not upper_changed and (not math.isfinite(radius) or radius > upper)
        else:
            audit = upper_pair["baseline_audit"]
            assert isinstance(audit, Mapping)
            trace_cycle = audit.get("trace_cycle")
            if trace_cycle is None or not upper_changed:
                record["attributed_surface"] = "no_crossing_within_grid"
                # No observed crossing is compatible with radius outside the tested grid.
                record["bracket_valid"] = not upper_changed
            else:
                trace_cycle = int(trace_cycle)
                trace_row = baseline_rows[trace_cycle]
                target = (
                    trace_cycle,
                    int(trace_row["winner_slot"]),
                    str(trace_row["required_skill"]),
                )
                radius, model_ok = _critical_trace_epsilon(
                    baseline_rows,
                    seed=seed,
                    cycle=first,
                    env=env,
                    base=base,
                    trace_target=target,
                    lower=lower,
                    upper=upper,
                )
                record["critical_radius"] = radius
                record["reconstruction_valid"] = bool(record["reconstruction_valid"]) and model_ok
                record["attributed_surface"] = "trace_mediated_auction_argmax"
                record["bracket_valid"] = bool(
                    model_ok
                    and radius is not None
                    and radius > lower - 1e-9
                    and radius <= upper + 1e-9
                )
        attributions.append(record)
    return attributions, baseline_series, series_rows


def _historical_margin_audit(
    connection: Connection[Any],
    *,
    config: EndogenousDemandConfig,
    config_hash: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    records: list[dict[str, object]] = []
    cycle_rows: list[dict[str, object]] = []
    cohorts = (
        ("discovery", 105, tuple(config.integration.seeds)),
        ("replication", 109, tuple(config.replication_seeds)),
        ("holdout", 110, tuple(config.integration.holdout_seeds)),
    )
    for cohort, experiment_number, seeds in cohorts:
        if cohort == "holdout":
            from .endogenous_demand_config import endogenous_environment

            env = endogenous_environment(
                config,
                cycles=config.integration.holdout_cycles,
                shift_period=config.integration.holdout_shift_period,
                candidate_count=config.integration.holdout_candidate_count,
            )
        else:
            from .endogenous_demand_config import endogenous_environment

            env = endogenous_environment(config)
        for seed in seeds:
            historical = _reconstruct_pair(
                connection,
                config=config,
                config_hash=config_hash,
                cohort=cohort,
                experiment_number=experiment_number,
                seed=seed,
            )
            feedback_run_id = str(historical["feedback_run_id"])
            rows = _query_outcomes(connection, feedback_run_id)
            events = _query_feedback(connection, feedback_run_id)
            series = margin_series(connection, run_id=feedback_run_id, seed=seed, env=env)
            eligible = _first_success_eligible(rows, cycles=env.cycles)
            override = _first_override(events, cycles=env.cycles)
            records.append(
                {
                    "cohort": cohort,
                    "seed": seed,
                    "delta_incumbency": float(historical["delta_incumbency"]),
                    "first_eligible_cycle": eligible,
                    "first_override_cycle": override,
                    "eligible_geometry": _point_geometry(series, eligible),
                    "override_geometry": _point_geometry(series, override),
                    "trend_spearman": _series_trend(series),
                    "checkpoints": {
                        str(c): _summary_at(series, min(c, env.cycles - 1)) for c in (10, 20, 30, 40)
                    },
                }
            )
            for item in series:
                cycle_rows.append({"cohort": cohort, "seed": seed, **dict(item)})
    return records, cycle_rows


def _compression_result(
    series_meta: Sequence[Mapping[str, object]], cycle_rows: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    trends = [float(item["trend_spearman"]) for item in series_meta]
    negative_share = sum(value < 0 for value in trends) / len(trends) if trends else 0.0
    finite_rows = [
        item
        for item in cycle_rows
        if math.isfinite(float(item["r_min_consequential"]))
    ]
    pooled = (
        _spearman(
            [float(item["cycle"]) for item in finite_rows],
            [float(item["r_min_consequential"]) for item in finite_rows],
        )
        if len(finite_rows) >= 3
        else 0.0
    )
    supported = negative_share >= 0.75 and pooled < 0.0
    return {
        "negative_within_seed_trend_share": negative_share,
        "pooled_cycle_radius_spearman": pooled,
        "supported": supported,
    }


def _soc_bracket(series_meta: Sequence[Mapping[str, object]], compression: Mapping[str, object]) -> str:
    if not bool(compression["supported"]):
        return "not_supported"
    final_medians: list[float] = []
    initial_medians: list[float] = []
    for item in series_meta:
        checkpoints = item["checkpoints"]
        assert isinstance(checkpoints, Mapping)
        a = checkpoints.get("10")
        b = checkpoints.get("40")
        if isinstance(a, Mapping) and isinstance(b, Mapping):
            av = float(a["median_r_min"])
            bv = float(b["median_r_min"])
            if math.isfinite(av) and math.isfinite(bv):
                initial_medians.append(av)
                final_medians.append(bv)
    if len(final_medians) < 4:
        return "compatible_but_unconfirmed"
    initial_cv = statistics.pstdev(initial_medians) / max(_EPS, statistics.mean(initial_medians))
    final_cv = statistics.pstdev(final_medians) / max(_EPS, statistics.mean(final_medians))
    return "compatible_but_unconfirmed" if final_cv <= initial_cv else "not_supported"


def _lock_in_geometry(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    nonneutral = [record for record in records if abs(float(record["delta_incumbency"])) > _EPS]
    if len(nonneutral) < 5:
        return {"identifiable": False, "reason": "fewer than five non-neutral historical seeds"}
    result: dict[str, object] = {"identifiable": True, "features": {}}
    for point in ("eligible_geometry", "override_geometry"):
        for feature in ("r_auction", "r_success", "r_feedback_domain", "r_min_consequential"):
            values: list[float] = []
            response: list[float] = []
            for record in nonneutral:
                geometry = record.get(point)
                if not isinstance(geometry, Mapping):
                    continue
                value = float(geometry.get(feature, _INF))
                if math.isfinite(value):
                    values.append(value)
                    response.append(float(record["delta_incumbency"]))
            result["features"][f"{point}.{feature}"] = {  # type: ignore[index]
                "n": len(values),
                "spearman_delta_incumbency": _spearman(values, response) if len(values) >= 3 else 0.0,
            }
    result["incremental_predictive_test"] = "not_identifiable_n7_without_posthoc_threshold_tuning"
    return result


def run_critical_margin_audit(
    connection: Connection[Any],
    *,
    endogenous_config: EndogenousDemandConfig,
    endogenous_config_hash: str,
    chaos_protocol: ChaosPredictabilityConfig,
    chaos_config_hash: str,
    code_sha: str,
) -> dict[str, object]:
    historical, historical_cycles = _historical_margin_audit(
        connection, config=endogenous_config, config_hash=endogenous_config_hash
    )
    attributions, chaos_series, chaos_cycles = _chaos_attribution(
        connection, protocol=chaos_protocol, chaos_config_hash=chaos_config_hash
    )
    all_series_meta = [
        {
            "cohort": f"105-110:{item['cohort']}",
            "seed": item["seed"],
            "trend_spearman": item["trend_spearman"],
            "checkpoints": item["checkpoints"],
        }
        for item in historical
    ] + [
        {
            "cohort": f"123-128:{item['cohort']}",
            "seed": item["seed"],
            "trend_spearman": item["trend_spearman"],
            "checkpoints": item["checkpoints"],
        }
        for item in chaos_series
    ]
    all_cycle_rows = historical_cycles + chaos_cycles
    compression = _compression_result(all_series_meta, all_cycle_rows)

    reconstructable = [item for item in attributions if bool(item["upper_changed"])]
    bracketed = [item for item in reconstructable if bool(item["bracket_valid"])]
    attribution_share = len(bracketed) / len(reconstructable) if reconstructable else 0.0
    systematic_counterexample = any(
        bool(item["upper_changed"]) and not bool(item["bracket_valid"])
        for item in attributions
        if str(item["cohort"]) in {"replication", "holdout"}
    )
    reconstruction_valid = all(bool(item["reconstruction_valid"]) for item in reconstructable)
    decision_surface_supported = (
        attribution_share >= 0.80
        and not systematic_counterexample
        and reconstruction_valid
    )
    soc = _soc_bracket(all_series_meta, compression)
    lock_in = _lock_in_geometry(historical)

    if decision_surface_supported and bracketed:
        # Both direct bid perturbations and trace-energy perturbations terminate at the same
        # production decision: the sealed-bid auction argmax. Preserve the mediation label
        # per pair, but freeze the underlying intervention surface at auction margin.
        dominant_surface = "auction_argmax"
    else:
        dominant_surface = None
    preregister_129 = bool(decision_surface_supported and dominant_surface == "auction_argmax")

    return {
        "audit": "critical-margin-105-128",
        "code_sha": code_sha,
        "canonical_chaos_sha": _CANONICAL_CHAOS_SHA,
        "endogenous_config_hash": endogenous_config_hash,
        "chaos_config_hash": chaos_config_hash,
        "historical_sign_records": historical,
        "chaos_attributions": attributions,
        "chaos_baseline_series": chaos_series,
        "decision_surface": {
            "reconstructable_divergences": len(reconstructable),
            "correctly_bracketed": len(bracketed),
            "attribution_share": attribution_share,
            "systematic_replication_holdout_counterexample": systematic_counterexample,
            "historical_reconstruction_valid": reconstruction_valid,
            "experiment_123_zero_twin_control": True,
            "supported": decision_surface_supported,
            "dominant_surface": dominant_surface,
        },
        "margin_compression": compression,
        "soc_classification": soc,
        "lock_in_plasticity_geometry": lock_in,
        "trace_gate_allocation_inert": endogenous_config.integration.environment.confidence_inflation == 0.0,
        "prng_phase_mutable": False,
        "preregister_margin_maintenance_129_134": preregister_129,
        "recommended_surface": dominant_surface if preregister_129 else None,
        "conclusion": (
            "decision_surface_supported" if decision_surface_supported else "decision_surface_not_supported"
        ),
        "margin_conclusion": (
            "margin_compression_supported" if bool(compression["supported"]) else "margin_compression_not_supported"
        ),
        "cycle_rows": all_cycle_rows,
    }


def render_markdown(audit: Mapping[str, object]) -> str:
    decision = audit["decision_surface"]
    compression = audit["margin_compression"]
    historical = audit["historical_sign_records"]
    attributions = audit["chaos_attributions"]
    assert isinstance(decision, Mapping)
    assert isinstance(compression, Mapping)
    assert isinstance(historical, Sequence)
    assert isinstance(attributions, Sequence)
    lines = [
        "<!-- critical-margin-audit:result -->",
        "## Critical-Margin Audit — 105–128",
        "",
        f"- Audit implementation commit: `{audit['code_sha']}`",
        f"- Decision-surface conclusion: **{audit['conclusion']}**",
        f"- Reconstructable discrete divergences: **{decision['reconstructable_divergences']}**",
        f"- Correctly radius-bracketed: **{decision['correctly_bracketed']}**",
        f"- Attribution share: **{float(decision['attribution_share']):.3f}**",
        f"- Dominant surface: **{decision['dominant_surface']}**",
        f"- Margin-compression conclusion: **{audit['margin_conclusion']}**",
        f"- Negative within-seed trend share: **{float(compression['negative_within_seed_trend_share']):.3f}**",
        f"- Pooled cycle→radius Spearman: **{float(compression['pooled_cycle_radius_spearman']):+.3f}**",
        f"- SOC classification: **{audit['soc_classification']}**",
        f"- Trace 0.20 allocation gate inert in frozen environment: **{audit['trace_gate_allocation_inert']}**",
        f"- Mutable PRNG phase present: **{audit['prng_phase_mutable']}**",
        "",
        "### 105–110 sign geometry",
        "",
        "| Cohort | Seed | ΔI | Eligible | Override | r_min@eligible | r_min@override | trend ρ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in historical:
        assert isinstance(item, Mapping)
        eg = item["eligible_geometry"]
        og = item["override_geometry"]
        assert isinstance(eg, Mapping) and isinstance(og, Mapping)
        lines.append(
            f"| {item['cohort']} | {item['seed']} | {float(item['delta_incumbency']):+.6f} | "
            f"{item['first_eligible_cycle']} | {item['first_override_cycle']} | "
            f"{float(eg.get('r_min_consequential', _INF)):.6g} | "
            f"{float(og.get('r_min_consequential', _INF)):.6g} | "
            f"{float(item['trend_spearman']):+.3f} |"
        )

    lines.extend(
        [
            "",
            "### 123–128 first-divergence attribution",
            "",
            "| Cohort | Seed | Family | ε≤0.1 changed? | ε=1 changed? | First divergence | Critical radius | Surface | Bracket |",
            "|---|---:|---|---|---|---:|---:|---|---|",
        ]
    )
    for item in attributions:
        assert isinstance(item, Mapping)
        radius = item.get("critical_radius")
        radius_text = "n/a" if radius is None else f"{float(radius):.6g}"
        first = item.get("first_discrete_divergence_cycle")
        lines.append(
            f"| {item['cohort']} | {item['seed']} | {item['family']} | {item['lower_changed']} | "
            f"{item['upper_changed']} | {first if first is not None else '—'} | {radius_text} | "
            f"{item['attributed_surface']} | {item['bracket_valid']} |"
        )

    lines.extend(
        [
            "",
            "### Interpretation",
            "",
            (
                "The allocation-relevant 0.20 trace branch is inert in these frozen campaigns because "
                "confidence inflation is zero. Trace-energy perturbations therefore act through continuous "
                "evidence/confidence until a later discrete allocation decision changes."
            ),
            "",
            (
                "Margin compression is a separate claim from decision-surface attribution. A negative "
                "time trend is reported as compression only; SOC is not promoted beyond the frozen "
                "classification without independent evidence of convergence toward a near-critical regime."
            ),
            "",
            "### Next-step decision",
            "",
            f"Preregister single-surface Margin Maintenance 129–134: **{audit['preregister_margin_maintenance_129_134']}**",
            f"Recommended surface: **{audit['recommended_surface']}**",
        ]
    )
    return "\n".join(lines) + "\n"


def write_artifacts(output_dir: str | Path, audit: Mapping[str, object]) -> None:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    cycle_rows = audit.get("cycle_rows")
    serializable = dict(audit)
    serializable.pop("cycle_rows", None)
    (root / "critical-margin-audit.json").write_text(
        json.dumps(serializable, indent=2, sort_keys=True, default=str) + "\n"
    )
    (root / "audit-report.md").write_text(render_markdown(audit))

    historical = audit["historical_sign_records"]
    attributions = audit["chaos_attributions"]
    assert isinstance(historical, Sequence) and isinstance(attributions, Sequence)
    with (root / "seed-pair-summary.csv").open("w", newline="") as handle:
        fieldnames = [
            "kind",
            "cohort",
            "seed",
            "delta_incumbency",
            "family",
            "lower_changed",
            "upper_changed",
            "first_discrete_divergence_cycle",
            "critical_radius",
            "attributed_surface",
            "bracket_valid",
            "trend_spearman",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in historical:
            writer.writerow(
                {
                    "kind": "105-110-sign",
                    "cohort": item["cohort"],
                    "seed": item["seed"],
                    "delta_incumbency": item["delta_incumbency"],
                    "trend_spearman": item["trend_spearman"],
                }
            )
        for item in attributions:
            writer.writerow(
                {
                    "kind": "123-128-attribution",
                    "cohort": item["cohort"],
                    "seed": item["seed"],
                    "family": item["family"],
                    "lower_changed": item["lower_changed"],
                    "upper_changed": item["upper_changed"],
                    "first_discrete_divergence_cycle": item["first_discrete_divergence_cycle"],
                    "critical_radius": item["critical_radius"],
                    "attributed_surface": item["attributed_surface"],
                    "bracket_valid": item["bracket_valid"],
                }
            )

    assert isinstance(cycle_rows, Sequence)
    with (root / "cycle-margin-summary.csv").open("w", newline="") as handle:
        fieldnames = [
            "cohort",
            "seed",
            "cycle",
            "r_auction",
            "r_success",
            "r_feedback_domain",
            "r_feedback_switch_exogenous",
            "r_trace_gate",
            "r_trace_rank",
            "r_min_consequential",
            "r_min_all",
            "forcing_phase",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in cycle_rows:
            writer.writerow({name: item.get(name) for name in fieldnames})


__all__ = [
    "_auction_radius",
    "_target_bid_radius",
    "_spearman",
    "margin_series",
    "render_markdown",
    "run_critical_margin_audit",
    "write_artifacts",
]
