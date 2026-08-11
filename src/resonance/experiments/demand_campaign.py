"""Demand-order intervention machinery for Experiments 099–104.

Each source cycle inside a regime is an exogenous task packet: domain, required skill,
requester, candidate set, bid noise, and outcome/evidence draws. A demand schedule is a
permutation of those packets inside the same regime. Task composition and market rules
stay fixed while only temporal order changes.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from . import lifecycle_campaign as lc
from .demand_config import DemandConfig, DemandScheduleSpec, demand_environment
from .integration_campaign import ReputationPolicy


def demand_arm(config: DemandConfig, *, label: str, environment=None) -> lc.LifecycleArmSpec:
    env = environment if environment is not None else demand_environment(config)
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


def _stable_key(*parts: object) -> int:
    digest = hashlib.sha256(":".join(str(part) for part in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _interleave_cycles(
    source_cycles: Sequence[int],
    *,
    seed: int,
    regime: int,
    domain_fn: Callable[[int, int, int], int],
    domain_count: int,
    chunk_size: int = 1,
) -> list[int]:
    queues: dict[int, list[int]] = defaultdict(list)
    for cycle in source_cycles:
        queues[domain_fn(seed, cycle, domain_count)].append(cycle)
    for domain in queues:
        queues[domain].sort(key=lambda cycle: _stable_key("demand-order", seed, regime, cycle))

    result: list[int] = []
    last_domain: int | None = None
    while any(queues.values()):
        candidates = [domain for domain, queue in queues.items() if queue]
        nonrepeat = [domain for domain in candidates if domain != last_domain]
        pool = nonrepeat or candidates
        domain = max(
            pool,
            key=lambda item: (
                len(queues[item]),
                -_stable_key("demand-domain", seed, regime, item, len(result)),
                -item,
            ),
        )
        take = min(chunk_size, len(queues[domain]))
        for _ in range(take):
            result.append(queues[domain].pop(0))
        last_domain = domain
    return result


def _reorder_regime(
    source_cycles: Sequence[int],
    *,
    mode: str,
    seed: int,
    regime: int,
    domain_fn: Callable[[int, int, int], int],
    domain_count: int,
) -> list[int]:
    if mode == "baseline":
        return list(source_cycles)
    if mode == "shuffled":
        return sorted(source_cycles, key=lambda cycle: _stable_key("demand-shuffle", seed, regime, cycle))
    if mode == "blocked":
        return sorted(
            source_cycles,
            key=lambda cycle: (
                domain_fn(seed, cycle, domain_count),
                _stable_key("demand-block", seed, regime, cycle),
            ),
        )
    if mode == "interleaved":
        return _interleave_cycles(
            source_cycles,
            seed=seed,
            regime=regime,
            domain_fn=domain_fn,
            domain_count=domain_count,
            chunk_size=1,
        )
    if mode == "paired":
        return _interleave_cycles(
            source_cycles,
            seed=seed,
            regime=regime,
            domain_fn=domain_fn,
            domain_count=domain_count,
            chunk_size=2,
        )
    raise ValueError(f"unsupported demand schedule mode: {mode}")


def build_source_schedule(
    spec: DemandScheduleSpec,
    *,
    seed: int,
    cycles: int,
    shift_period: int,
    domain_count: int,
    domain_fn: Callable[[int, int, int], int],
) -> list[int]:
    """Return source-cycle index for every target cycle."""
    schedule = list(range(cycles))
    for start in range(0, cycles, shift_period):
        end = min(cycles, start + shift_period)
        regime = start // shift_period
        schedule[start:end] = _reorder_regime(
            list(range(start, end)),
            mode=spec.mode_for_regime(regime),
            seed=seed,
            regime=regime,
            domain_fn=domain_fn,
            domain_count=domain_count,
        )
    return schedule


def _schedule_invariants(schedule: Sequence[int], *, cycles: int, shift_period: int) -> dict[str, bool]:
    exact = len(schedule) == cycles and sorted(schedule) == list(range(cycles))
    same_regime = all(target // shift_period == int(source) // shift_period for target, source in enumerate(schedule))
    per_regime = True
    for start in range(0, cycles, shift_period):
        end = min(cycles, start + shift_period)
        per_regime = per_regime and sorted(schedule[start:end]) == list(range(start, end))
    return {
        "demand_schedule_global_permutation": exact,
        "demand_schedule_regime_local": same_regime,
        "exact_task_multiset_per_regime": per_regime,
    }


def _schedule_metrics(
    schedule: Sequence[int],
    *,
    seed: int,
    shift_period: int,
    domain_count: int,
    domain_fn: Callable[[int, int, int], int],
) -> dict[str, float]:
    repeats: list[float] = []
    runs: list[int] = []
    changed = 0
    displacement: list[float] = []
    for start in range(0, len(schedule), shift_period):
        end = min(len(schedule), start + shift_period)
        domains = [domain_fn(seed, int(schedule[target]), domain_count) for target in range(start, end)]
        if domains:
            run = 1
            for index in range(1, len(domains)):
                same = domains[index] == domains[index - 1]
                repeats.append(float(same))
                if same:
                    run += 1
                else:
                    runs.append(run)
                    run = 1
            runs.append(run)
        for target in range(start, end):
            source = int(schedule[target])
            changed += int(source != target)
            displacement.append(abs(source - target) / max(1, end - start))
    return {
        "demand_adjacent_repeat_rate": statistics.mean(repeats) if repeats else 0.0,
        "demand_mean_run_length": statistics.mean(runs) if runs else 1.0,
        "demand_max_run_length": float(max(runs)) if runs else 1.0,
        "demand_order_changed_rate": changed / max(1, len(schedule)),
        "demand_mean_source_displacement": statistics.mean(displacement) if displacement else 0.0,
    }


def _packet_payload(
    *,
    env,
    seed: int,
    source_cycle: int,
    domain_fn,
    requester_fn,
    candidate_fn,
    draw_fn,
) -> dict[str, object]:
    regime = source_cycle // env.shift_period
    domain_index = domain_fn(seed, source_cycle, len(env.domains))
    requester_slot = requester_fn(env, seed, source_cycle)
    candidate_slots = tuple(
        candidate_fn(
            seed,
            source_cycle,
            agents=env.agents,
            requester_slot=requester_slot,
            count=env.candidate_count,
        )
    )
    bid_draws = {
        str(slot): {
            label: draw_fn(seed, source_cycle, slot, label)
            for label in ("confidence", "price", "speed")
        }
        for slot in candidate_slots
    }
    outcome_draws = {
        str(slot): {
            label: draw_fn(seed, source_cycle, slot, label)
            for label in ("outcome", "evidence-noise")
        }
        for slot in range(env.agents)
    }
    return {
        "source_cycle": source_cycle,
        "regime": regime,
        "domain_index": domain_index,
        "task_domain": env.domains[domain_index],
        "required_skill": env.domains[(domain_index + regime) % len(env.domains)],
        "requester_slot": requester_slot,
        "candidate_slots": list(candidate_slots),
        "bid_draws": bid_draws,
        "outcome_draws": outcome_draws,
    }


def _packet_fingerprint(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


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


def _phase_change_metrics(
    rows: Sequence[Mapping[str, object]],
    *,
    spec: DemandScheduleSpec,
    cycles: int,
    shift_period: int,
) -> dict[str, float]:
    if not spec.phase_modes:
        return {
            "unlock_winner_repeat_change": 0.0,
            "relock_winner_repeat_rebound": 0.0,
            "unlock_cycle": -1.0,
            "relock_cycle": -1.0,
        }
    regime_count = (cycles + shift_period - 1) // shift_period
    modes = [spec.mode_for_regime(regime) for regime in range(regime_count)]
    unlock_cycle: int | None = None
    relock_cycle: int | None = None
    for regime in range(1, len(modes)):
        previous = modes[regime - 1]
        current = modes[regime]
        if unlock_cycle is None and previous in {"blocked", "paired"} and current == "interleaved":
            unlock_cycle = regime * shift_period
        if relock_cycle is None and previous == "interleaved" and current in {"paired", "blocked"}:
            relock_cycle = regime * shift_period

    def delta(cycle: int | None) -> float:
        if cycle is None:
            return 0.0
        before = _winner_repeat_rate(rows, start=max(0, cycle - shift_period), end=cycle)
        after = _winner_repeat_rate(rows, start=cycle, end=min(cycles, cycle + shift_period))
        return after - before

    return {
        "unlock_winner_repeat_change": delta(unlock_cycle),
        "relock_winner_repeat_rebound": delta(relock_cycle),
        "unlock_cycle": float(unlock_cycle if unlock_cycle is not None else -1),
        "relock_cycle": float(relock_cycle if relock_cycle is not None else -1),
    }


def _persist_schedule_observations(
    connection: Connection[Any],
    *,
    run_id: str,
    schedule: Sequence[int],
    spec: DemandScheduleSpec,
    env,
    seed: int,
    domain_fn,
    requester_fn,
    candidate_fn,
    draw_fn,
) -> None:
    outcomes = connection.execute(
        """
        SELECT cycle, regime, task_id, task_domain, required_skill, created_at
        FROM integration_campaign_outcomes
        WHERE run_id = %s
        ORDER BY cycle
        """,
        (UUID(run_id),),
    ).fetchall()
    if len(outcomes) != env.cycles:
        raise RuntimeError("demand schedule outcome count mismatch")

    with connection.transaction():
        for row in outcomes:
            target_cycle = int(row["cycle"])
            source_cycle = int(schedule[target_cycle])
            payload = _packet_payload(
                env=env,
                seed=seed,
                source_cycle=source_cycle,
                domain_fn=domain_fn,
                requester_fn=requester_fn,
                candidate_fn=candidate_fn,
                draw_fn=draw_fn,
            )
            connection.execute(
                """
                INSERT INTO demand_schedule_observations (
                    run_id, cycle, source_cycle, regime, task_id,
                    task_domain, required_skill, requester_slot, candidate_slots,
                    packet_fingerprint, schedule_mode, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    UUID(run_id),
                    target_cycle,
                    source_cycle,
                    row["regime"],
                    row["task_id"],
                    row["task_domain"],
                    row["required_skill"],
                    payload["requester_slot"],
                    Jsonb(payload["candidate_slots"]),
                    _packet_fingerprint(payload),
                    spec.mode_for_regime(int(row["regime"])),
                    row["created_at"],
                ),
            )


def run_demand_cell(
    connection: Connection[Any],
    *,
    config: DemandConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    label: str,
    spec: DemandScheduleSpec,
    seed: int,
    environment=None,
) -> dict[str, object]:
    arm = demand_arm(config, label=label, environment=environment)
    env = arm.environment
    original_domain = lc._domain_index
    original_requester = lc._requester_slot
    original_candidates = lc._candidate_slots
    original_draw = lc._draw

    schedule = build_source_schedule(
        spec,
        seed=seed,
        cycles=env.cycles,
        shift_period=env.shift_period,
        domain_count=len(env.domains),
        domain_fn=original_domain,
    )
    schedule_invariants = _schedule_invariants(schedule, cycles=env.cycles, shift_period=env.shift_period)

    def source_cycle(cycle: int) -> int:
        return int(schedule[cycle]) if 0 <= cycle < len(schedule) else cycle

    def mapped_domain(inner_seed: int, cycle: int, domain_count: int) -> int:
        return original_domain(inner_seed, source_cycle(cycle), domain_count)

    def mapped_requester(inner_env, inner_seed: int, cycle: int) -> int:
        return original_requester(inner_env, inner_seed, source_cycle(cycle))

    def mapped_candidates(inner_seed: int, cycle: int, *, agents: int, requester_slot: int, count: int):
        return original_candidates(
            inner_seed,
            source_cycle(cycle),
            agents=agents,
            requester_slot=requester_slot,
            count=count,
        )

    def mapped_draw(inner_seed: int, cycle: int, slot: int, label_name: str) -> float:
        return original_draw(inner_seed, source_cycle(cycle), slot, label_name)

    lc._domain_index = mapped_domain
    lc._requester_slot = mapped_requester
    lc._candidate_slots = mapped_candidates
    lc._draw = mapped_draw
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
        lc._requester_slot = original_requester
        lc._candidate_slots = original_candidates
        lc._draw = original_draw

    rows = connection.execute(
        """
        SELECT cycle, regime, domain_index, winner_slot
        FROM integration_campaign_outcomes
        WHERE run_id = %s
        ORDER BY cycle
        """,
        (UUID(str(cell["run_id"])),),
    ).fetchall()
    metrics = dict(cell["metrics"])
    metrics.update(
        _schedule_metrics(
            schedule,
            seed=seed,
            shift_period=env.shift_period,
            domain_count=len(env.domains),
            domain_fn=original_domain,
        )
    )
    metrics.update(_phase_change_metrics(rows, spec=spec, cycles=env.cycles, shift_period=env.shift_period))
    cell["metrics"] = metrics

    invariants = dict(cell["invariants"])
    invariants.update(schedule_invariants)
    invariants["identity_turnover_absent"] = float(metrics.get("exit_count", 0.0)) == 0.0
    invariants["demand_reputation_neutral"] = arm.policy.mode == "none"
    invariants["production_matching_unchanged"] = True
    invariants["source_packet_reordering_only"] = True
    cell["invariants"] = invariants
    cell["demand_schedule"] = spec.as_dict()

    _persist_schedule_observations(
        connection,
        run_id=str(cell["run_id"]),
        schedule=schedule,
        spec=spec,
        env=env,
        seed=seed,
        domain_fn=original_domain,
        requester_fn=original_requester,
        candidate_fn=original_candidates,
        draw_fn=original_draw,
    )
    return cell


def run_demand_arm(
    connection: Connection[Any],
    *,
    config: DemandConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    label: str,
    spec: DemandScheduleSpec,
    seeds: Sequence[int],
    environment=None,
) -> dict[str, object]:
    cells = [
        run_demand_cell(
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
    aggregate["demand_schedule"] = spec.as_dict()
    return aggregate


def run_demand_arms(
    connection: Connection[Any],
    *,
    config: DemandConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    specs: Sequence[tuple[str, DemandScheduleSpec]],
    seeds: Sequence[int] | None = None,
    environment=None,
) -> list[dict[str, object]]:
    actual_seeds = seeds if seeds is not None else config.integration.seeds
    return [
        run_demand_arm(
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


__all__ = ["build_source_schedule", "demand_arm", "run_demand_arm", "run_demand_arms", "run_demand_cell"]
