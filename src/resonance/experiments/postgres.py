"""PostgreSQL persistence for reproducible experiment runs and snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class PostgresExperimentStore:
    def __init__(self, connection: Connection[Any]) -> None:
        if not connection.autocommit:
            raise ValueError("PostgresExperimentStore requires an autocommit connection")
        connection.row_factory = dict_row
        self._connection = connection

    def start_run(
        self,
        *,
        run_id: UUID,
        name: str,
        ablation: str,
        seed: int,
        config_hash: str,
        config: Mapping[str, object],
        code_sha: str,
        cycles_requested: int,
        started_at: datetime,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO experiment_runs (
                run_id, name, ablation, seed, config_hash, config, code_sha,
                status, cycles_requested, cycles_completed, started_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'running', %s, 0, %s)
            """,
            (
                run_id,
                name,
                ablation,
                seed,
                config_hash,
                Jsonb(dict(config)),
                code_sha,
                cycles_requested,
                started_at,
            ),
        )

    def register_agent(
        self,
        *,
        run_id: UUID,
        agent_id: UUID,
        agent_slot: int,
        initial_credits: int,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO experiment_agents (
                run_id, agent_id, agent_slot, initial_credits
            ) VALUES (%s, %s, %s, %s)
            """,
            (run_id, agent_id, agent_slot, initial_credits),
        )

    def record_action_cost(
        self,
        *,
        run_id: UUID,
        request_id: UUID,
        agent_id: UUID,
        action: str,
        credits: int,
        ledger_transaction_id: UUID | None,
        charged_at: datetime,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO experiment_action_costs (
                run_id, request_id, agent_id, action, credits,
                ledger_transaction_id, charged_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                request_id,
                agent_id,
                action,
                credits,
                ledger_transaction_id,
                charged_at,
            ),
        )

    def snapshot(
        self,
        *,
        run_id: UUID,
        cycle: int,
        captured_at: datetime,
        metrics: Mapping[str, object],
    ) -> UUID:
        snapshot_id = uuid4()
        self._connection.execute(
            """
            INSERT INTO experiment_snapshots (
                snapshot_id, run_id, cycle, captured_at, metrics
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (snapshot_id, run_id, cycle, captured_at, Jsonb(dict(metrics))),
        )
        self._connection.execute(
            "UPDATE experiment_runs SET cycles_completed = %s WHERE run_id = %s",
            (cycle, run_id),
        )
        return snapshot_id

    def complete(self, run_id: UUID, *, cycles_completed: int, completed_at: datetime) -> None:
        self._connection.execute(
            """
            UPDATE experiment_runs
            SET status = 'completed', cycles_completed = %s, completed_at = %s, failure = NULL
            WHERE run_id = %s
            """,
            (cycles_completed, completed_at, run_id),
        )

    def fail(self, run_id: UUID, *, failure: str, completed_at: datetime) -> None:
        self._connection.execute(
            """
            UPDATE experiment_runs
            SET status = 'failed', completed_at = %s, failure = %s
            WHERE run_id = %s
            """,
            (completed_at, failure[:4000], run_id),
        )
