"""PostgreSQL implementation of agent identity and double-entry compute credits."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import dict_row

from .models import AgentIdentity, ComputeAccount

TREASURY_ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000001")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _agent_from_row(row: Mapping[str, Any]) -> AgentIdentity:
    return AgentIdentity(
        agent_id=row["agent_id"],
        generation=row["generation"],
        status=row["status"],
        model_profile=row["model_profile"],
        created_at=row["created_at"],
        last_active_at=row["last_active_at"],
    )


def _account_from_row(row: Mapping[str, Any]) -> ComputeAccount:
    return ComputeAccount(
        account_id=row["account_id"],
        owner_agent_id=row["owner_agent_id"],
        account_kind=row["account_kind"],
        reference_id=row["reference_id"],
        balance=row["balance"],
        created_at=row["created_at"],
    )


class PostgresEconomyRepository:
    """Trusted ledger service. Agent actions never receive treasury capabilities."""

    def __init__(self, connection: Connection[Any]) -> None:
        if not connection.autocommit:
            raise ValueError("PostgresEconomyRepository requires an autocommit connection")
        connection.row_factory = dict_row
        self._connection = connection

    def register_agent(
        self,
        agent_id: UUID,
        *,
        at: datetime,
        generation: int = 0,
        model_profile: str = "STANDARD",
        initial_credits: int = 0,
    ) -> AgentIdentity:
        _aware("at", at)
        if generation < 0:
            raise ValueError("generation must be non-negative")
        if not model_profile.strip():
            raise ValueError("model_profile must not be empty")
        if initial_credits < 0:
            raise ValueError("initial_credits must be non-negative")

        account_id = uuid4()
        with self._connection.transaction():
            self._connection.execute(
                """
                INSERT INTO agents (
                    agent_id, generation, status, model_profile, created_at, last_active_at
                ) VALUES (%s, %s, 'active', %s, %s, %s)
                """,
                (agent_id, generation, model_profile, at, at),
            )
            self._connection.execute(
                """
                INSERT INTO compute_accounts (
                    account_id, owner_agent_id, account_kind, balance, created_at
                ) VALUES (%s, %s, 'agent', 0, %s)
                """,
                (account_id, agent_id, at),
            )
            if initial_credits:
                self._transfer_locked(
                    TREASURY_ACCOUNT_ID,
                    account_id,
                    initial_credits,
                    at=at,
                    reason="initial allocation",
                    reference_type="agent",
                    reference_id=agent_id,
                )

        agent = self.get_agent(agent_id)
        assert agent is not None
        return agent

    def get_agent(self, agent_id: UUID) -> AgentIdentity | None:
        row = self._connection.execute(
            """
            SELECT agent_id, generation, status, model_profile, created_at, last_active_at
            FROM agents WHERE agent_id = %s
            """,
            (agent_id,),
        ).fetchone()
        return None if row is None else _agent_from_row(row)

    def account_for_agent(self, agent_id: UUID) -> ComputeAccount:
        row = self._connection.execute(
            """
            SELECT account_id, owner_agent_id, account_kind, reference_id, balance, created_at
            FROM compute_accounts WHERE owner_agent_id = %s
            """,
            (agent_id,),
        ).fetchone()
        if row is None:
            raise KeyError(agent_id)
        return _account_from_row(row)

    def balance(self, agent_id: UUID) -> int:
        return self.account_for_agent(agent_id).balance

    def issue(
        self,
        agent_id: UUID,
        amount: int,
        *,
        at: datetime,
        reason: str = "allocation",
        reference_type: str | None = None,
        reference_id: UUID | None = None,
    ) -> UUID:
        account = self.account_for_agent(agent_id)
        return self.transfer(
            TREASURY_ACCOUNT_ID,
            account.account_id,
            amount,
            at=at,
            reason=reason,
            reference_type=reference_type,
            reference_id=reference_id,
        )

    def create_system_account(
        self,
        account_kind: str,
        *,
        at: datetime,
        reference_id: UUID | None = None,
    ) -> ComputeAccount:
        _aware("at", at)
        if not account_kind.strip() or account_kind == "agent":
            raise ValueError("account_kind must identify a non-agent system account")
        account = ComputeAccount(
            account_id=uuid4(),
            owner_agent_id=None,
            account_kind=account_kind,
            reference_id=reference_id,
            balance=0,
            created_at=at,
        )
        self._connection.execute(
            """
            INSERT INTO compute_accounts (
                account_id, owner_agent_id, account_kind, reference_id, balance, created_at
            ) VALUES (%s, NULL, %s, %s, 0, %s)
            """,
            (account.account_id, account.account_kind, account.reference_id, account.created_at),
        )
        return account

    def transfer(
        self,
        source_account_id: UUID,
        target_account_id: UUID,
        amount: int,
        *,
        at: datetime,
        reason: str,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
    ) -> UUID:
        _aware("at", at)
        if amount <= 0:
            raise ValueError("amount must be positive")
        if source_account_id == target_account_id:
            raise ValueError("source and target accounts must differ")
        if not reason.strip():
            raise ValueError("reason must not be empty")
        with self._connection.transaction():
            return self._transfer_locked(
                source_account_id,
                target_account_id,
                amount,
                at=at,
                reason=reason,
                reference_type=reference_type,
                reference_id=reference_id,
            )

    def _transfer_locked(
        self,
        source_account_id: UUID,
        target_account_id: UUID,
        amount: int,
        *,
        at: datetime,
        reason: str,
        reference_type: str | None,
        reference_id: UUID | None,
    ) -> UUID:
        account_ids = sorted((source_account_id, target_account_id), key=str)
        rows = self._connection.execute(
            """
            SELECT account_id, balance
            FROM compute_accounts
            WHERE account_id = ANY(%s)
            ORDER BY account_id
            FOR UPDATE
            """,
            (account_ids,),
        ).fetchall()
        balances = {row["account_id"]: row["balance"] for row in rows}
        if source_account_id not in balances:
            raise KeyError(source_account_id)
        if target_account_id not in balances:
            raise KeyError(target_account_id)
        if balances[source_account_id] < amount:
            raise ValueError("insufficient compute credits")

        transaction_id = uuid4()
        self._connection.execute(
            """
            INSERT INTO compute_transactions (
                transaction_id, reason, reference_type, reference_id, created_at
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (transaction_id, reason, reference_type, reference_id, at),
        )
        self._connection.execute(
            """
            INSERT INTO compute_postings (transaction_id, account_id, amount)
            VALUES (%s, %s, %s), (%s, %s, %s)
            """,
            (
                transaction_id,
                source_account_id,
                -amount,
                transaction_id,
                target_account_id,
                amount,
            ),
        )
        self._connection.execute(
            "UPDATE compute_accounts SET balance = balance - %s WHERE account_id = %s",
            (amount, source_account_id),
        )
        self._connection.execute(
            "UPDATE compute_accounts SET balance = balance + %s WHERE account_id = %s",
            (amount, target_account_id),
        )
        return transaction_id
