"""Experiment 003: persistent reputation under active trace decay and regime shift."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from resonance.economy import PostgresEconomyRepository
from resonance.market.models import MarketBid, MarketTask, bid_score
from resonance.reputation import PostgresReputationRepository
from resonance.substrate.models import Trace
from resonance.substrate.postgres import PostgresTraceRepository

from .postgres import PostgresExperimentStore
from .reputation_metrics import summarize_reputation_experiment
from .reputation_models import ReputationExperimentConfig

_ALLOWED_ARMS = frozenset(
    {"slow_reputation", "slow_no_reputation", "fast_reputation", "fast_no_reputation"}
)
_BASE_TIME = datetime(2026, 3, 1, tzinfo=UTC)
_DIMENSION = "task_success"


def _draw(seed: int, cycle: int, slot: int, label: str) -> float:
    digest = hashlib.sha256(f"{label}:{seed}:{cycle}:{slot}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / (2**64 - 1)


def _domain_index(seed: int, cycle: int, size: int) -> int:
    digest = hashlib.sha256(f"domain:{seed}:{cycle}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % size


def _candidate_slots(
    seed: int,
    cycle: int,
    *,
    agents: int,
    requester_slot: int,
    count: int,
) -> list[int]:
    eligible = [slot for slot in range(agents) if slot != requester_slot]
    return sorted(
        eligible,
        key=lambda slot: (
            hashlib.sha256(f"candidate:{seed}:{cycle}:{slot}".encode()).digest(),
            slot,
        ),
    )[:count]


def _skill_embedding(index: int) -> tuple[float, ...]:
    values = [0.0] * 1536
    values[index] = 1.0
    values[96] = 0.2
    return tuple(values)


def _evidence_signal(
    connection: Connection[Any],
    *,
    agent_id: UUID,
    skill: str,
    at: datetime,
) -> float:
    row = connection.execute(
        """
        SELECT COALESCE(MAX(
            energy_anchor * power(
                2.0,
                -GREATEST(
                    0.0,
                    EXTRACT(EPOCH FROM (%s - energy_updated_at))::double precision
                ) / half_life_seconds
            )
        ), 0.0) AS signal
        FROM traces
        WHERE author_agent_id = %s
          AND kind = 'VERIFIED_OUTCOME'
          AND content = %s
          AND status = 'active'
        """,
        (at, agent_id, f"skill-evidence:{skill}"),
    ).fetchone()
    return 0.0 if row is None else float(row["signal"])


def _create_task(
    connection: Connection[Any],
    economy: PostgresEconomyRepository,
    *,
    run_id: UUID,
    cycle: int,
    requester_id: UUID,
    domain: str,
    required_skill: str,
    config: ReputationExperimentConfig,
    at: datetime,
) -> MarketTask:
    task_id = uuid5(run_id, f"task:{cycle}")
    escrow = economy.create_system_account("task_escrow", at=at, reference_id=task_id)
    deadline = at + timedelta(seconds=config.bid_deadline_seconds)
    connection.execute(
        """
        INSERT INTO market_tasks (
            task_id, requester_agent_id, escrow_account_id, description, budget,
            deadline, required_capabilities, success_condition, status, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'open', %s)
        """,
        (
            task_id,
            requester_id,
            escrow.account_id,
            f"Delegated evaluation for {domain}",
            config.task_budget,
            deadline,
            Jsonb([required_skill]),
            Jsonb({"task_domain": domain, "required_skill": required_skill}),
            at,
        ),
    )
    requester = economy.account_for_agent(requester_id)
    economy.transfer(
        requester.account_id,
        escrow.account_id,
        config.task_budget,
        at=at,
        reason="experiment delegation escrow",
        reference_type="task",
        reference_id=task_id,
    )
    return MarketTask(
        task_id=task_id,
        requester_agent_id=requester_id,
        escrow_account_id=escrow.account_id,
        description=f"Delegated evaluation for {domain}",
        budget=config.task_budget,
        deadline=deadline,
        created_at=at,
        required_capabilities=(required_skill,),
        success_condition={"task_domain": domain, "required_skill": required_skill},
    )


def _submit_bid(
    connection: Connection[Any],
    *,
    run_id: UUID,
    task: MarketTask,
    cycle: int,
    slot: int,
    agent_id: UUID,
    confidence: float,
    price: int,
    completion_seconds: int,
    at: datetime,
) -> MarketBid:
    bid = MarketBid(
        bid_id=uuid5(run_id, f"bid:{cycle}:{slot}"),
        task_id=task.task_id,
        bidder_agent_id=agent_id,
        price=price,
        confidence=confidence,
        estimated_completion_seconds=completion_seconds,
        strategy_summary=f"General-purpose bid from slot {slot}",
        submitted_at=at,
    )
    connection.execute(
        """
        INSERT INTO market_bids (
            bid_id, task_id, bidder_agent_id, price, confidence,
            estimated_completion_seconds, strategy_summary, status, submitted_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'sealed', %s)
        """,
        (
            bid.bid_id,
            bid.task_id,
            bid.bidder_agent_id,
            bid.price,
            bid.confidence,
            bid.estimated_completion_seconds,
            bid.strategy_summary,
            bid.submitted_at,
        ),
    )
    return bid


def _settle_winner(
    connection: Connection[Any],
    economy: PostgresEconomyRepository,
    *,
    task: MarketTask,
    winner: MarketBid,
    at: datetime,
) -> None:
    connection.execute(
        "UPDATE market_bids SET status = 'selected' WHERE bid_id = %s",
        (winner.bid_id,),
    )
    connection.execute(
        "UPDATE market_bids SET status = 'rejected' WHERE task_id = %s AND bid_id <> %s",
        (task.task_id, winner.bid_id),
    )
    connection.execute(
        """
        UPDATE market_tasks
        SET status = 'awarded', awarded_agent_id = %s, winning_bid_id = %s, awarded_at = %s
        WHERE task_id = %s
        """,
        (winner.bidder_agent_id, winner.bid_id, at, task.task_id),
    )
    winner_account = economy.account_for_agent(winner.bidder_agent_id)
    requester_account = economy.account_for_agent(task.requester_agent_id)
    economy.transfer(
        task.escrow_account_id,
        winner_account.account_id,
        winner.price,
        at=at,
        reason="experiment delegation settlement",
        reference_type="task",
        reference_id=task.task_id,
    )
    refund = task.budget - winner.price
    if refund:
        economy.transfer(
            task.escrow_account_id,
            requester_account.account_id,
            refund,
            at=at,
            reason="experiment unused delegation refund",
            reference_type="task",
            reference_id=task.task_id,
        )
    connection.execute(
        "UPDATE market_tasks SET status = 'completed', completed_at = %s WHERE task_id = %s",
        (at, task.task_id),
    )


def _outcome_rows(connection: Connection[Any], run_id: UUID) -> list[Mapping[str, object]]:
    return list(
        connection.execute(
            """
            SELECT cycle, regime, task_domain, required_skill, winner_agent_id,
                   reputation_score, success_probability, success
            FROM reputation_delegation_outcomes
            WHERE run_id = %s ORDER BY cycle
            """,
            (run_id,),
        ).fetchall()
    )


def collect_reputation_metrics(
    connection: Connection[Any],
    *,
    run_id: UUID,
    config: ReputationExperimentConfig,
) -> dict[str, object]:
    rows = _outcome_rows(connection, run_id)
    metrics = summarize_reputation_experiment(
        rows,
        domains=config.domains,
        shift_cycle=config.shift_cycle,
        early_post_shift_cycles=config.early_post_shift_cycles,
        late_post_shift_cycles=config.late_post_shift_cycles,
    )
    evidence = connection.execute(
        "SELECT COUNT(*) AS count FROM reputation_evidence WHERE source_type = 'delegation_task' AND source_id IN (SELECT task_id FROM reputation_delegation_outcomes WHERE run_id = %s)",
        (run_id,),
    ).fetchone()
    traces = connection.execute(
        """
        SELECT COUNT(*) AS count FROM traces
        WHERE kind = 'VERIFIED_OUTCOME'
          AND author_agent_id IN (SELECT agent_id FROM experiment_agents WHERE run_id = %s)
        """,
        (run_id,),
    ).fetchone()
    metrics["reputation_evidence_count"] = 0 if evidence is None else int(evidence["count"])
    metrics["verified_evidence_trace_count"] = 0 if traces is None else int(traces["count"])
    return metrics


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: str(value) if isinstance(value, (UUID, datetime)) else value for key, value in row.items()})


def export_reputation_artifacts(
    connection: Connection[Any],
    *,
    run_id: UUID,
    output_dir: str | Path,
    summary: Mapping[str, object],
) -> None:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "experiment.json").write_text(json.dumps(dict(summary), indent=2, sort_keys=True) + "\n")
    queries = {
        "outcomes.csv": "SELECT * FROM reputation_delegation_outcomes WHERE run_id = %s ORDER BY cycle",
        "auction_scores.csv": "SELECT * FROM reputation_auction_scores WHERE run_id = %s ORDER BY task_id, total_score DESC, bidder_agent_id",
        "reputation.csv": "SELECT rs.* FROM reputation_states rs JOIN experiment_agents ea ON ea.agent_id = rs.agent_id WHERE ea.run_id = %s ORDER BY rs.context_key, rs.agent_id",
        "reputation_evidence.csv": "SELECT re.* FROM reputation_evidence re JOIN experiment_agents ea ON ea.agent_id = re.agent_id WHERE ea.run_id = %s ORDER BY re.created_at, re.evidence_id",
        "tasks.csv": "SELECT mt.* FROM market_tasks mt JOIN reputation_delegation_outcomes o ON o.task_id = mt.task_id WHERE o.run_id = %s ORDER BY o.cycle",
        "traces.csv": "SELECT trace_id, author_agent_id, kind, content, created_at, initial_energy, energy_anchor, energy_updated_at, half_life_seconds, quality_score FROM traces WHERE author_agent_id IN (SELECT agent_id FROM experiment_agents WHERE run_id = %s) AND kind = 'VERIFIED_OUTCOME' ORDER BY created_at, trace_id",
    }
    for filename, query in queries.items():
        rows = connection.execute(query, (run_id,)).fetchall()
        _write_csv(destination / filename, [dict(row) for row in rows])


def run_reputation_experiment(
    connection: Connection[Any],
    *,
    config: ReputationExperimentConfig,
    config_hash: str,
    seed: int,
    arm: str,
    code_sha: str,
    output_dir: str | Path,
) -> dict[str, object]:
    if arm not in _ALLOWED_ARMS:
        raise ValueError(f"unsupported reputation arm: {arm}")
    if not connection.autocommit:
        raise ValueError("reputation experiment runner requires autocommit")
    connection.row_factory = dict_row

    run_id = uuid5(NAMESPACE_URL, f"reputation:{code_sha}:{config_hash}:{arm}:{seed}")
    start = _BASE_TIME
    half_life = config.half_life_for(arm)
    reputation_enabled = config.reputation_enabled(arm)
    store = PostgresExperimentStore(connection)
    store.start_run(
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
    reputation = PostgresReputationRepository(connection)
    traces = PostgresTraceRepository(connection)
    agent_ids: list[UUID] = []
    slot_by_id: dict[UUID, int] = {}
    practice: dict[tuple[int, str], int] = {}

    try:
        for slot in range(config.agents):
            agent_id = uuid5(run_id, f"agent:{slot}")
            economy.register_agent(agent_id, at=start, initial_credits=config.initial_credits)
            store.register_agent(
                run_id=run_id,
                agent_id=agent_id,
                agent_slot=slot,
                initial_credits=config.initial_credits,
            )
            agent_ids.append(agent_id)
            slot_by_id[agent_id] = slot

        for cycle in range(config.cycles):
            task_at = start + timedelta(seconds=cycle * config.cycle_seconds)
            regime = 0 if cycle < config.shift_cycle else 1
            domain_index = _domain_index(seed, cycle, len(config.domains))
            task_domain = config.domains[domain_index]
            required_index = domain_index if regime == 0 else (domain_index + 1) % len(config.domains)
            required_skill = config.domains[required_index]
            requester_slot = cycle % config.agents
            requester_id = agent_ids[requester_slot]
            task = _create_task(
                connection,
                economy,
                run_id=run_id,
                cycle=cycle,
                requester_id=requester_id,
                domain=task_domain,
                required_skill=required_skill,
                config=config,
                at=task_at,
            )

            scored: list[tuple[float, int, MarketBid, float, float, float]] = []
            for candidate_slot in _candidate_slots(
                seed,
                cycle,
                agents=config.agents,
                requester_slot=requester_slot,
                count=config.candidate_count,
            ):
                candidate_id = agent_ids[candidate_slot]
                signal = _evidence_signal(
                    connection,
                    agent_id=candidate_id,
                    skill=required_skill,
                    at=task_at,
                )
                noise = _draw(seed, cycle, candidate_slot, "confidence")
                confidence = min(0.98, 0.35 + 0.45 * signal + 0.20 * noise)
                price = 5 + int(_draw(seed, cycle, candidate_slot, "price") * 6)
                completion = 5 + int(_draw(seed, cycle, candidate_slot, "speed") * 12)
                bid_at = task_at + timedelta(microseconds=candidate_slot + 1)
                bid = _submit_bid(
                    connection,
                    run_id=run_id,
                    task=task,
                    cycle=cycle,
                    slot=candidate_slot,
                    agent_id=candidate_id,
                    confidence=confidence,
                    price=price,
                    completion_seconds=completion,
                    at=bid_at,
                )
                baseline = bid_score(task, bid)
                rep_score = reputation.get(
                    candidate_id,
                    dimension=_DIMENSION,
                    context_key=task_domain,
                    at=task_at,
                ).score
                total = baseline + (
                    config.reputation_weight * (rep_score - 0.5) if reputation_enabled else 0.0
                )
                scored.append((total, candidate_slot, bid, baseline, rep_score, signal))
                connection.execute(
                    """
                    INSERT INTO reputation_auction_scores (
                        run_id, task_id, bid_id, bidder_agent_id, task_domain,
                        required_skill, baseline_score, reputation_score,
                        evidence_signal, total_score, selected, captured_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s)
                    """,
                    (
                        run_id, task.task_id, bid.bid_id, candidate_id, task_domain,
                        required_skill, baseline, rep_score, signal, total, task_at,
                    ),
                )

            total, winner_slot, winner, baseline, rep_score, signal = max(
                scored,
                key=lambda item: (item[0], -item[1]),
            )
            awarded_at = task.deadline + timedelta(microseconds=1)
            _settle_winner(connection, economy, task=task, winner=winner, at=awarded_at)
            connection.execute(
                "UPDATE reputation_auction_scores SET selected = TRUE WHERE run_id = %s AND bid_id = %s",
                (run_id, winner.bid_id),
            )

            practice_before = practice.get((winner_slot, required_skill), 0)
            probability = min(
                config.maximum_success_probability,
                config.base_success_probability
                + config.practice_gain * math.sqrt(practice_before),
            )
            roll = _draw(seed, cycle, winner_slot, "outcome")
            success = roll < probability
            practice[(winner_slot, required_skill)] = practice_before + 1
            outcome_id = uuid5(run_id, f"outcome:{cycle}")
            connection.execute(
                """
                INSERT INTO reputation_delegation_outcomes (
                    outcome_id, run_id, cycle, regime, task_id, task_domain,
                    required_skill, winner_agent_id, winner_bid_id, baseline_score,
                    reputation_score, total_score, evidence_signal, practice_before,
                    success_probability, outcome_roll, success, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    outcome_id, run_id, cycle, regime, task.task_id, task_domain,
                    required_skill, winner.bidder_agent_id, winner.bid_id, baseline,
                    rep_score, total, signal, practice_before, probability, roll,
                    success, awarded_at,
                ),
            )
            reputation.record_evidence(
                winner.bidder_agent_id,
                dimension=_DIMENSION,
                context_key=task_domain,
                positive=success,
                source_type="delegation_task",
                source_id=task.task_id,
                at=awarded_at,
            )
            if success:
                traces.add(
                    Trace(
                        trace_id=uuid5(run_id, f"verified:{cycle}:{winner_slot}:{required_skill}"),
                        author_agent_id=winner.bidder_agent_id,
                        kind="VERIFIED_OUTCOME",
                        content=f"skill-evidence:{required_skill}",
                        embedding=_skill_embedding(required_index),
                        created_at=awarded_at,
                        updated_at=awarded_at,
                        initial_energy=config.evidence_initial_energy,
                        half_life_seconds=half_life,
                        confidence=probability,
                        quality_score=0.9,
                    )
                )

            completed_cycle = cycle + 1
            if completed_cycle % config.snapshot_every == 0 or completed_cycle == config.cycles:
                store.snapshot(
                    run_id=run_id,
                    cycle=completed_cycle,
                    captured_at=awarded_at,
                    metrics=collect_reputation_metrics(connection, run_id=run_id, config=config),
                )

        completed_at = start + timedelta(seconds=config.cycles * config.cycle_seconds)
        metrics = collect_reputation_metrics(connection, run_id=run_id, config=config)
        store.complete(run_id, cycles_completed=config.cycles, completed_at=completed_at)
        summary = {
            "run_id": str(run_id),
            "name": config.name,
            "arm": arm,
            "seed": seed,
            "code_sha": code_sha,
            "config_hash": config_hash,
            "cycles": config.cycles,
            "agents": config.agents,
            "shift_cycle": config.shift_cycle,
            "half_life_seconds": half_life,
            "reputation_enabled": reputation_enabled,
            "metrics": metrics,
        }
        export_reputation_artifacts(
            connection,
            run_id=run_id,
            output_dir=output_dir,
            summary=summary,
        )
        return summary
    except Exception as exc:
        store.fail(
            run_id,
            failure=f"{type(exc).__name__}: {exc}",
            completed_at=datetime.now(UTC),
        )
        raise
