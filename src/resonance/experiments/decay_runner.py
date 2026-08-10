"""Controlled Experiment 002 runner for trace-decay ecology."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection
from psycopg.rows import dict_row

from resonance.agents import AgentObservation, AgentRuntime, DefaultPolicyGateway
from resonance.agents.actions import ActionType
from resonance.agents.postgres_events import PostgresDecisionEventStore
from resonance.economy import PostgresEconomyRepository
from resonance.substrate.models import RetrievedTrace, Trace
from resonance.substrate.postgres import PostgresTraceRepository

from .decay_metrics import summarize_decay_observations
from .decay_models import DecayExperimentConfig
from .decay_policy import DecayStressPolicy
from .metering import ExperimentComputeMeter
from .metrics import summarize_behavior
from .postgres import PostgresExperimentStore

_ALLOWED_ARMS = frozenset({"fast_decay", "slow_decay", "no_decay"})
_BASE_TIME = datetime(2026, 2, 1, tzinfo=UTC)


def _probe_embedding(neighborhood_index: int) -> tuple[float, ...]:
    values = [0.0] * 1536
    values[neighborhood_index] = 1.0
    values[64] = 0.25
    return tuple(values)


def _trace_embedding(neighborhood_index: int, key: str) -> tuple[float, ...]:
    values = list(_probe_embedding(neighborhood_index))
    digest = hashlib.sha256(key.encode()).digest()
    magnitude = 0.03 + (int.from_bytes(digest[:2], "big") / 65535) * 0.15
    sign = -1.0 if digest[2] % 2 else 1.0
    values[128 + neighborhood_index] = sign * magnitude
    return tuple(values)


def _stable_neighborhood(seed: int, cycle: int, slot: int, size: int) -> int:
    digest = hashlib.sha256(f"decay-neighborhood:{seed}:{cycle}:{slot}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % size


def _seed_initial_traces(
    traces: PostgresTraceRepository,
    *,
    run_id: UUID,
    config: DecayExperimentConfig,
    half_life_seconds: float,
    start: datetime,
) -> None:
    age_steps = (0, 1, 2, 4, 8)
    for neighborhood_index, neighborhood in enumerate(config.neighborhoods):
        for variant in range(config.traces_per_neighborhood):
            age_step = age_steps[variant % len(age_steps)]
            created_at = start - timedelta(
                seconds=age_step * config.fast_half_life_seconds
            )
            age_fraction = variant / max(1, config.traces_per_neighborhood - 1)
            initial_energy = 0.55 + 0.40 * age_fraction
            quality = 0.45 + 0.50 * age_fraction
            trace_id = uuid5(run_id, f"seed:{neighborhood}:{variant}")
            traces.add(
                Trace(
                    trace_id=trace_id,
                    kind="HYPOTHESIS",
                    content=f"seed:{neighborhood}:variant:{variant}",
                    embedding=_trace_embedding(
                        neighborhood_index,
                        f"seed:{neighborhood}:{variant}",
                    ),
                    created_at=created_at,
                    updated_at=created_at,
                    initial_energy=initial_energy,
                    half_life_seconds=half_life_seconds,
                    confidence=0.75,
                    quality_score=quality,
                )
            )


def _inject_novel_traces(
    traces: PostgresTraceRepository,
    *,
    run_id: UUID,
    config: DecayExperimentConfig,
    half_life_seconds: float,
    seed: int,
    cycle: int,
    at: datetime,
) -> None:
    if cycle <= 0 or cycle % config.novel_trace_every_cycles:
        return
    for neighborhood_index, neighborhood in enumerate(config.neighborhoods):
        digest = hashlib.sha256(f"novel:{seed}:{cycle}:{neighborhood}".encode()).digest()
        energy = 0.65 + (digest[0] / 255) * 0.25
        quality = 0.45 + (digest[1] / 255) * 0.35
        trace_id = uuid5(run_id, f"novel:{cycle}:{neighborhood}")
        traces.add(
            Trace(
                trace_id=trace_id,
                kind="HYPOTHESIS",
                content=f"novel:{neighborhood}:cycle:{cycle}",
                embedding=_trace_embedding(
                    neighborhood_index,
                    f"novel:{seed}:{cycle}:{neighborhood}",
                ),
                created_at=at,
                updated_at=at,
                initial_energy=energy,
                half_life_seconds=half_life_seconds,
                confidence=0.70,
                quality_score=quality,
            )
        )


def _record_probe(
    connection: Connection[Any],
    traces: PostgresTraceRepository,
    *,
    run_id: UUID,
    config: DecayExperimentConfig,
    cycle: int,
    phase: str,
    at: datetime,
) -> None:
    for neighborhood_index, neighborhood in enumerate(config.neighborhoods):
        retrieved = traces.search(
            _probe_embedding(neighborhood_index),
            at=at,
            limit=config.retrieval_limit,
        )
        for rank, item in enumerate(retrieved, start=1):
            observation_id = uuid5(
                run_id,
                f"probe:{cycle}:{phase}:{neighborhood}:{rank}",
            )
            age = max(0.0, (at - item.trace.created_at).total_seconds())
            connection.execute(
                """
                INSERT INTO decay_retrieval_observations (
                    observation_id, run_id, cycle, phase, neighborhood, rank,
                    trace_id, retrieval_score, current_energy, semantic_similarity,
                    trace_age_seconds, captured_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    observation_id,
                    run_id,
                    cycle,
                    phase,
                    neighborhood,
                    rank,
                    item.trace.trace_id,
                    item.retrieval_score,
                    item.energy,
                    item.semantic_similarity,
                    age,
                    at,
                ),
            )


def _record_resurrection(
    connection: Connection[Any],
    traces: PostgresTraceRepository,
    *,
    run_id: UUID,
    config: DecayExperimentConfig,
    cycle: int,
    slot: int,
    agent_id: UUID,
    neighborhood_index: int,
    neighborhood: str,
    target_id: UUID,
    before: Sequence[RetrievedTrace],
    at: datetime,
) -> None:
    rank_before: int | None = None
    energy_before = 0.0
    for rank, item in enumerate(before, start=1):
        if item.trace.trace_id == target_id:
            rank_before = rank
            energy_before = item.energy
            break
    if rank_before is None:
        return

    after = traces.search(
        _probe_embedding(neighborhood_index),
        at=at,
        limit=config.retrieval_limit,
    )
    rank_after: int | None = None
    energy_after = 0.0
    for rank, item in enumerate(after, start=1):
        if item.trace.trace_id == target_id:
            rank_after = rank
            energy_after = item.energy
            break
    confirmed = (
        energy_before <= config.resurrection_energy_threshold
        and rank_before > 1
        and rank_after is not None
        and rank_after <= 2
        and rank_after < rank_before
    )
    connection.execute(
        """
        INSERT INTO decay_resurrection_events (
            resurrection_id, run_id, cycle, neighborhood, agent_id, trace_id,
            rank_before, rank_after, energy_before, energy_after, confirmed, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            uuid5(run_id, f"resurrection:{cycle}:{slot}:{target_id}"),
            run_id,
            cycle,
            neighborhood,
            agent_id,
            target_id,
            rank_before,
            rank_after,
            energy_before,
            energy_after,
            confirmed,
            at,
        ),
    )


def _behavior_rows(
    connection: Connection[Any], run_id: UUID
) -> list[tuple[UUID, str, int]]:
    rows = connection.execute(
        """
        SELECT d.agent_id, d.proposed_action, COALESCE(c.credits, 0) AS credits
        FROM decision_events d
        JOIN experiment_agents ea ON ea.agent_id = d.agent_id
        LEFT JOIN experiment_action_costs c
          ON c.run_id = ea.run_id AND c.request_id = d.request_id
        WHERE ea.run_id = %s
        ORDER BY d.occurred_at, d.event_id
        """,
        (run_id,),
    ).fetchall()
    return [(row["agent_id"], row["proposed_action"], row["credits"]) for row in rows]


def _balances(connection: Connection[Any], run_id: UUID) -> dict[UUID, int]:
    rows = connection.execute(
        """
        SELECT ea.agent_id, ca.balance
        FROM experiment_agents ea
        JOIN compute_accounts ca ON ca.owner_agent_id = ea.agent_id
        WHERE ea.run_id = %s
        ORDER BY ea.agent_slot
        """,
        (run_id,),
    ).fetchall()
    return {row["agent_id"]: row["balance"] for row in rows}


def collect_decay_metrics(
    connection: Connection[Any],
    *,
    run_id: UUID,
    config: DecayExperimentConfig,
) -> dict[str, object]:
    behavior_rows = _behavior_rows(connection, run_id)
    metrics = summarize_behavior(behavior_rows, _balances(connection, run_id))
    retrieval_rows = connection.execute(
        """
        SELECT cycle, phase, neighborhood, rank, trace_id,
               retrieval_score, current_energy, semantic_similarity,
               trace_age_seconds, captured_at
        FROM decay_retrieval_observations
        WHERE run_id = %s
        ORDER BY cycle, phase, neighborhood, rank
        """,
        (run_id,),
    ).fetchall()
    resurrection_rows = connection.execute(
        """
        SELECT confirmed FROM decay_resurrection_events
        WHERE run_id = %s ORDER BY cycle, neighborhood, resurrection_id
        """,
        (run_id,),
    ).fetchall()
    metrics.update(
        summarize_decay_observations(
            retrieval_rows,
            old_age_seconds=2 * config.fast_half_life_seconds,
            resurrection_rows=resurrection_rows,
        )
    )
    action_counts: dict[str, int] = {}
    for _, action, _ in behavior_rows:
        action_counts[action] = action_counts.get(action, 0) + 1
    metrics.update(
        {
            "query_actions": action_counts.get(ActionType.QUERY_SUBSTRATE.value, 0),
            "reinforcement_actions": action_counts.get(ActionType.REINFORCE_TRACE.value, 0),
            "retrieval_observations": len(retrieval_rows),
        }
    )
    return metrics


def _json_default(value: object) -> str:
    if isinstance(value, (UUID, datetime)):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: _json_default(value)
                    if isinstance(value, (UUID, datetime))
                    else value
                    for key, value in row.items()
                }
            )


def export_decay_artifacts(
    connection: Connection[Any],
    *,
    run_id: UUID,
    output_dir: str | Path,
    summary: Mapping[str, object],
) -> None:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "experiment.json").write_text(
        json.dumps(dict(summary), indent=2, sort_keys=True, default=_json_default) + "\n"
    )

    retrieval_rows = connection.execute(
        """
        SELECT cycle, phase, neighborhood, rank, trace_id, retrieval_score,
               current_energy, semantic_similarity, trace_age_seconds, captured_at
        FROM decay_retrieval_observations
        WHERE run_id = %s
        ORDER BY cycle, phase, neighborhood, rank
        """,
        (run_id,),
    ).fetchall()
    _write_csv(destination / "retrieval.csv", [dict(row) for row in retrieval_rows])

    resurrection_rows = connection.execute(
        """
        SELECT cycle, neighborhood, agent_id, trace_id, rank_before, rank_after,
               energy_before, energy_after, confirmed, created_at
        FROM decay_resurrection_events
        WHERE run_id = %s
        ORDER BY cycle, neighborhood, resurrection_id
        """,
        (run_id,),
    ).fetchall()
    _write_csv(destination / "resurrections.csv", [dict(row) for row in resurrection_rows])

    event_rows = connection.execute(
        """
        SELECT d.event_id, d.agent_id, d.occurred_at, d.proposed_action,
               d.policy_result, d.outcome_status, d.request_id, d.correlation_id,
               d.retrieved_trace_ids, d.output_trace_ids, COALESCE(c.credits, 0) AS compute_spent
        FROM decision_events d
        JOIN experiment_agents ea ON ea.agent_id = d.agent_id
        LEFT JOIN experiment_action_costs c
          ON c.run_id = ea.run_id AND c.request_id = d.request_id
        WHERE ea.run_id = %s
        ORDER BY d.occurred_at, d.event_id
        """,
        (run_id,),
    ).fetchall()
    with (destination / "events.jsonl").open("w") as handle:
        for row in event_rows:
            handle.write(json.dumps(dict(row), default=_json_default, sort_keys=True) + "\n")

    trace_rows = connection.execute(
        """
        SELECT trace_id, author_agent_id, kind, content, created_at, updated_at,
               initial_energy, energy_anchor, energy_updated_at, half_life_seconds,
               confidence, quality_score, adoption_score
        FROM traces
        WHERE trace_id IN (
            SELECT trace_id FROM decay_retrieval_observations WHERE run_id = %s
            UNION
            SELECT trace_id FROM decay_resurrection_events WHERE run_id = %s
        )
        ORDER BY created_at, trace_id
        """,
        (run_id, run_id),
    ).fetchall()
    _write_csv(destination / "traces.csv", [dict(row) for row in trace_rows])


def run_decay_experiment(
    connection: Connection[Any],
    *,
    config: DecayExperimentConfig,
    config_hash: str,
    seed: int,
    arm: str,
    code_sha: str,
    output_dir: str | Path,
) -> dict[str, object]:
    if arm not in _ALLOWED_ARMS:
        raise ValueError(f"unsupported decay arm: {arm}")
    if not connection.autocommit:
        raise ValueError("decay experiment runner requires an autocommit connection")
    connection.row_factory = dict_row

    run_id = uuid5(NAMESPACE_URL, f"decay:{code_sha}:{config_hash}:{arm}:{seed}")
    start = _BASE_TIME
    half_life = config.half_life_for(arm)
    experiment_store = PostgresExperimentStore(connection)
    experiment_store.start_run(
        run_id=run_id,
        name=config.name,
        ablation=arm,
        seed=seed,
        config_hash=config_hash,
        config=config.as_dict(),
        code_sha=code_sha,
        cycles_requested=config.cycles,
        started_at=start,
    )

    economy = PostgresEconomyRepository(connection)
    traces = PostgresTraceRepository(connection)
    events = PostgresDecisionEventStore(connection)
    sink = economy.create_system_account(
        "experiment_compute_sink", at=start, reference_id=run_id
    )
    meter = ExperimentComputeMeter(
        economy=economy,
        store=experiment_store,
        run_id=run_id,
        sink_account_id=sink.account_id,
        costs=config.action_costs,
    )
    policy = DecayStressPolicy(seed=seed, action_costs=config.action_costs)
    runtime = AgentRuntime(
        traces=traces,
        events=events,
        gateway=DefaultPolicyGateway(),
        policy=policy,
    )

    agent_ids: list[UUID] = []
    try:
        for slot in range(config.agents):
            agent_id = uuid5(run_id, f"agent:{slot}")
            economy.register_agent(
                agent_id,
                at=start,
                initial_credits=config.initial_credits,
            )
            experiment_store.register_agent(
                run_id=run_id,
                agent_id=agent_id,
                agent_slot=slot,
                initial_credits=config.initial_credits,
            )
            agent_ids.append(agent_id)

        _seed_initial_traces(
            traces,
            run_id=run_id,
            config=config,
            half_life_seconds=half_life,
            start=start,
        )

        for cycle in range(config.cycles):
            cycle_at = start + timedelta(seconds=cycle * config.cycle_seconds)
            _inject_novel_traces(
                traces,
                run_id=run_id,
                config=config,
                half_life_seconds=half_life,
                seed=seed,
                cycle=cycle,
                at=cycle_at,
            )

            if cycle % config.probe_every_cycles == 0:
                _record_probe(
                    connection,
                    traces,
                    run_id=run_id,
                    config=config,
                    cycle=cycle,
                    phase="pre",
                    at=cycle_at,
                )

            for slot, agent_id in enumerate(agent_ids):
                agent_at = cycle_at + timedelta(microseconds=slot + 1)
                neighborhood_index = _stable_neighborhood(
                    seed,
                    cycle,
                    slot,
                    len(config.neighborhoods),
                )
                neighborhood = config.neighborhoods[neighborhood_index]
                observation = AgentObservation(
                    trigger=f"decay:{arm}:cycle:{cycle}:neighborhood:{neighborhood}",
                    observed_at=agent_at,
                    query_embedding=_probe_embedding(neighborhood_index),
                    retrieval_limit=config.retrieval_limit,
                    metadata={
                        "cycle": cycle,
                        "agent_slot": slot,
                        "neighborhood": neighborhood,
                        "balance": economy.balance(agent_id),
                        "resurrection_energy_threshold": config.resurrection_energy_threshold,
                        "reinforcement_amount": config.reinforcement_amount,
                    },
                )
                with events.transaction():
                    result = runtime.step(agent_id, observation)
                    meter.charge(agent_id, result.request, at=agent_at)
                if result.request.action == ActionType.REINFORCE_TRACE:
                    target = result.request.payload.get("trace_id")
                    if isinstance(target, UUID):
                        _record_resurrection(
                            connection,
                            traces,
                            run_id=run_id,
                            config=config,
                            cycle=cycle,
                            slot=slot,
                            agent_id=agent_id,
                            neighborhood_index=neighborhood_index,
                            neighborhood=neighborhood,
                            target_id=target,
                            before=result.context.retrieved,
                            at=agent_at,
                        )

            post_at = cycle_at + timedelta(microseconds=config.agents + 2)
            if cycle % config.probe_every_cycles == 0:
                _record_probe(
                    connection,
                    traces,
                    run_id=run_id,
                    config=config,
                    cycle=cycle,
                    phase="post",
                    at=post_at,
                )

            completed_cycle = cycle + 1
            if completed_cycle % config.snapshot_every == 0 or completed_cycle == config.cycles:
                metrics = collect_decay_metrics(
                    connection,
                    run_id=run_id,
                    config=config,
                )
                experiment_store.snapshot(
                    run_id=run_id,
                    cycle=completed_cycle,
                    captured_at=post_at,
                    metrics=metrics,
                )

        completed_at = start + timedelta(seconds=config.cycles * config.cycle_seconds)
        final_metrics = collect_decay_metrics(
            connection,
            run_id=run_id,
            config=config,
        )
        experiment_store.complete(
            run_id,
            cycles_completed=config.cycles,
            completed_at=completed_at,
        )
        summary = {
            "run_id": str(run_id),
            "name": config.name,
            "arm": arm,
            "seed": seed,
            "config_hash": config_hash,
            "code_sha": code_sha,
            "cycles": config.cycles,
            "agents": config.agents,
            "half_life_seconds": half_life,
            "metrics": final_metrics,
        }
        export_decay_artifacts(
            connection,
            run_id=run_id,
            output_dir=output_dir,
            summary=summary,
        )
        return summary
    except Exception as exc:
        experiment_store.fail(
            run_id,
            failure=f"{type(exc).__name__}: {exc}",
            completed_at=datetime.now(UTC),
        )
        raise
