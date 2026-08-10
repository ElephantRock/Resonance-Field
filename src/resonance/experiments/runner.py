"""Deterministic experiment runner for the first Resonance Field emergence study."""

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
from resonance.agents.postgres_events import PostgresDecisionEventStore
from resonance.economy import PostgresEconomyRepository
from resonance.market import PostgresMarketService
from resonance.substrate.models import Trace
from resonance.substrate.postgres import PostgresTraceRepository

from .metering import ExperimentComputeMeter
from .metrics import summarize_behavior
from .models import ExperimentConfig
from .policy import SeededExperimentPolicy
from .postgres import PostgresExperimentStore

_ALLOWED_ABLATIONS = frozenset({"full", "no_market", "no_decay"})
_BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def apply_migrations(
    connection: Connection[Any], migrations_dir: str | Path = "migrations"
) -> None:
    for path in sorted(Path(migrations_dir).glob("*.sql")):
        connection.execute(path.read_text())


def _embedding(topic_index: int) -> tuple[float, ...]:
    if not 0 <= topic_index < 1536:
        raise ValueError("topic_index must fit the embedding dimension")
    values = [0.0] * 1536
    values[topic_index] = 1.0
    return tuple(values)


def _stable_index(seed: int, cycle: int, slot: int, size: int) -> int:
    digest = hashlib.sha256(f"topic:{seed}:{cycle}:{slot}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % size


def _post_budget(config: ExperimentConfig, seed: int, cycle: int, slot: int) -> int:
    width = config.task_budget_max - config.task_budget_min + 1
    return config.task_budget_min + ((seed + cycle * 7 + slot * 13) % width)


def _open_task(
    connection: Connection[Any], *, agent_id: UUID, at: datetime
) -> Mapping[str, object] | None:
    row = connection.execute(
        """
        SELECT task_id, budget
        FROM market_tasks
        WHERE status = 'open'
          AND requester_agent_id <> %s
          AND deadline > %s
        ORDER BY created_at, requester_agent_id
        LIMIT 1
        """,
        (agent_id, at),
    ).fetchone()
    return None if row is None else {"task_id": row["task_id"], "budget": row["budget"]}


def _resolve_due_tasks(
    connection: Connection[Any], market: PostgresMarketService, *, at: datetime
) -> None:
    rows = connection.execute(
        """
        SELECT task_id
        FROM market_tasks
        WHERE status = 'open' AND deadline <= %s
        ORDER BY deadline, requester_agent_id
        """,
        (at,),
    ).fetchall()
    for row in rows:
        result = market.award(row["task_id"], at=at)
        if result is not None:
            market.settle(row["task_id"], at=at)


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


def collect_metrics(
    connection: Connection[Any], run_id: UUID, topics: Sequence[str]
) -> dict[str, object]:
    metrics = summarize_behavior(
        _behavior_rows(connection, run_id), _balances(connection, run_id)
    )
    market = connection.execute(
        """
        SELECT
            COUNT(*) AS tasks_posted,
            COUNT(*) FILTER (WHERE status = 'completed') AS tasks_completed,
            COUNT(*) FILTER (WHERE status = 'cancelled') AS tasks_cancelled
        FROM market_tasks
        WHERE requester_agent_id IN (
            SELECT agent_id FROM experiment_agents WHERE run_id = %s
        )
        """,
        (run_id,),
    ).fetchone()
    bids = connection.execute(
        """
        SELECT COUNT(*) AS bids_submitted
        FROM market_bids
        WHERE bidder_agent_id IN (
            SELECT agent_id FROM experiment_agents WHERE run_id = %s
        )
        """,
        (run_id,),
    ).fetchone()
    traces = connection.execute(
        """
        SELECT content
        FROM traces
        WHERE author_agent_id IN (
            SELECT agent_id FROM experiment_agents WHERE run_id = %s
        )
        """,
        (run_id,),
    ).fetchall()
    covered = {
        topic for topic in topics if any(topic in str(row["content"]) for row in traces)
    }
    metrics.update(
        {
            "tasks_posted": 0 if market is None else market["tasks_posted"],
            "tasks_completed": 0 if market is None else market["tasks_completed"],
            "tasks_cancelled": 0 if market is None else market["tasks_cancelled"],
            "bids_submitted": 0 if bids is None else bids["bids_submitted"],
            "trace_count": len(traces),
            "topic_coverage": len(covered) / len(topics),
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
            encoded = {
                key: _json_default(value) if isinstance(value, (UUID, datetime)) else value
                for key, value in row.items()
            }
            writer.writerow(encoded)


def export_artifacts(
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

    event_rows = connection.execute(
        """
        SELECT d.event_id, d.agent_id, d.occurred_at, d.proposed_action,
               d.policy_result, d.outcome_status, d.confidence, d.request_id,
               d.correlation_id, d.retrieved_trace_ids, d.output_trace_ids,
               COALESCE(c.credits, 0) AS compute_spent
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
            handle.write(
                json.dumps(dict(row), default=_json_default, sort_keys=True) + "\n"
            )

    agent_rows = connection.execute(
        """
        SELECT ea.agent_slot, ea.agent_id, ea.initial_credits,
               ca.balance AS ending_balance, COALESCE(SUM(c.credits), 0) AS compute_spent
        FROM experiment_agents ea
        JOIN compute_accounts ca ON ca.owner_agent_id = ea.agent_id
        LEFT JOIN experiment_action_costs c
          ON c.run_id = ea.run_id AND c.agent_id = ea.agent_id
        WHERE ea.run_id = %s
        GROUP BY ea.agent_slot, ea.agent_id, ea.initial_credits, ca.balance
        ORDER BY ea.agent_slot
        """,
        (run_id,),
    ).fetchall()
    _write_csv(destination / "agents.csv", [dict(row) for row in agent_rows])

    task_rows = connection.execute(
        """
        SELECT task_id, requester_agent_id, budget, status, awarded_agent_id,
               created_at, awarded_at, completed_at
        FROM market_tasks
        WHERE requester_agent_id IN (
            SELECT agent_id FROM experiment_agents WHERE run_id = %s
        )
        ORDER BY created_at, requester_agent_id
        """,
        (run_id,),
    ).fetchall()
    _write_csv(destination / "tasks.csv", [dict(row) for row in task_rows])

    trace_rows = connection.execute(
        """
        SELECT trace_id, author_agent_id, kind, created_at, initial_energy,
               energy_anchor, half_life_seconds, confidence, quality_score
        FROM traces
        WHERE author_agent_id IN (
            SELECT agent_id FROM experiment_agents WHERE run_id = %s
        )
        ORDER BY created_at, author_agent_id, trace_id
        """,
        (run_id,),
    ).fetchall()
    _write_csv(destination / "traces.csv", [dict(row) for row in trace_rows])


def run_experiment(
    connection: Connection[Any],
    *,
    config: ExperimentConfig,
    config_hash: str,
    seed: int,
    ablation: str,
    code_sha: str,
    output_dir: str | Path,
) -> dict[str, object]:
    if ablation not in _ALLOWED_ABLATIONS:
        raise ValueError(f"unsupported ablation: {ablation}")
    if not connection.autocommit:
        raise ValueError("experiment runner requires an autocommit connection")
    connection.row_factory = dict_row

    run_id = uuid5(NAMESPACE_URL, f"{code_sha}:{config_hash}:{ablation}:{seed}")
    start = _BASE_TIME
    experiment_store = PostgresExperimentStore(connection)
    experiment_store.start_run(
        run_id=run_id,
        name=config.name,
        ablation=ablation,
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
    market = PostgresMarketService(connection, economy)
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
    policy = SeededExperimentPolicy(seed=seed, action_costs=config.action_costs)
    half_life = (
        config.no_decay_half_life_seconds
        if ablation == "no_decay"
        else config.trace_half_life_seconds
    )
    market_enabled = ablation != "no_market"

    agent_ids: list[UUID] = []
    try:
        for slot in range(config.agents):
            agent_id = uuid5(run_id, f"agent:{slot}")
            economy.register_agent(
                agent_id, at=start, initial_credits=config.initial_credits
            )
            experiment_store.register_agent(
                run_id=run_id,
                agent_id=agent_id,
                agent_slot=slot,
                initial_credits=config.initial_credits,
            )
            agent_ids.append(agent_id)

        for topic_index, topic in enumerate(config.topics):
            traces.add(
                Trace(
                    kind="OBSERVATION",
                    content=f"Seed observation for {topic}",
                    embedding=_embedding(topic_index),
                    created_at=start,
                    updated_at=start,
                    initial_energy=0.75,
                    half_life_seconds=half_life,
                    confidence=0.8,
                    quality_score=0.7,
                )
            )

        runtime = AgentRuntime(
            traces=traces,
            events=events,
            gateway=DefaultPolicyGateway(),
            policy=policy,
            market=market,
        )

        for cycle in range(config.cycles):
            cycle_at = start + timedelta(seconds=cycle * config.cycle_seconds)
            if market_enabled:
                _resolve_due_tasks(connection, market, at=cycle_at)

            for slot, agent_id in enumerate(agent_ids):
                agent_at = cycle_at + timedelta(microseconds=slot)
                topic_index = _stable_index(seed, cycle, slot, len(config.topics))
                topic = config.topics[topic_index]
                budget = _post_budget(config, seed, cycle, slot)
                deadline = agent_at + timedelta(
                    seconds=config.task_deadline_cycles * config.cycle_seconds
                )
                metadata = {
                    "cycle": cycle,
                    "agent_slot": slot,
                    "topic": topic,
                    "balance": economy.balance(agent_id),
                    "market_enabled": market_enabled,
                    "half_life_seconds": half_life,
                    "post_budget": budget,
                    "post_deadline": deadline,
                    "open_task": (
                        _open_task(connection, agent_id=agent_id, at=agent_at)
                        if market_enabled
                        else None
                    ),
                }
                observation = AgentObservation(
                    trigger=f"experiment:{ablation}:cycle:{cycle}:topic:{topic}",
                    observed_at=agent_at,
                    query_embedding=_embedding(topic_index),
                    retrieval_limit=6,
                    metadata=metadata,
                )
                with events.transaction():
                    result = runtime.step(agent_id, observation)
                    meter.charge(agent_id, result.request, at=agent_at)

            completed_cycle = cycle + 1
            if (
                completed_cycle % config.snapshot_every == 0
                or completed_cycle == config.cycles
            ):
                metrics = collect_metrics(connection, run_id, config.topics)
                experiment_store.snapshot(
                    run_id=run_id,
                    cycle=completed_cycle,
                    captured_at=cycle_at,
                    metrics=metrics,
                )

        final_cycle_at = start + timedelta(seconds=config.cycles * config.cycle_seconds)
        cleanup_at = final_cycle_at + timedelta(
            seconds=config.task_deadline_cycles * config.cycle_seconds + 1
        )
        if market_enabled:
            _resolve_due_tasks(connection, market, at=cleanup_at)
        final_metrics = collect_metrics(connection, run_id, config.topics)
        experiment_store.complete(
            run_id,
            cycles_completed=config.cycles,
            completed_at=cleanup_at,
        )
        summary = {
            "run_id": str(run_id),
            "name": config.name,
            "ablation": ablation,
            "seed": seed,
            "config_hash": config_hash,
            "code_sha": code_sha,
            "cycles": config.cycles,
            "agents": config.agents,
            "metrics": final_metrics,
        }
        export_artifacts(
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
