"""Matching-objective machinery for Experiments 093–098.

The intervention leaves agents, candidate sets, sealed bids, capability accumulation,
public traces, prices, and reputation policy unchanged. Only the deterministic function
mapping a sealed bid to its auction score is replaced inside an isolated experiment cell.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection

import resonance.market.postgres as market_postgres
from resonance.market.models import MarketBid, MarketTask, bid_score as production_bid_score

from . import lifecycle_campaign as lc
from .adaptive_campaign import _summarize_rows
from .integration_campaign import ReputationPolicy
from .matching_config import MatchingConfig, MatchingObjectiveSpec, matching_environment


def _components(task: MarketTask, bid: MarketBid) -> tuple[float, float, float]:
    confidence = bid.confidence
    price_efficiency = 1.0 - (bid.price / task.budget)
    available_seconds = max(1.0, (task.deadline - task.created_at).total_seconds())
    speed = 1.0 - min(1.0, bid.estimated_completion_seconds / available_seconds)
    return confidence, price_efficiency, speed


def _unblended_score(task: MarketTask, bid: MarketBid, spec: MatchingObjectiveSpec) -> float:
    if spec.mode == "baseline":
        return production_bid_score(task, bid)
    confidence, price_efficiency, speed = _components(task, bid)
    if spec.mode == "weighted":
        return (
            spec.confidence_weight * confidence
            + spec.price_weight * price_efficiency
            + spec.speed_weight * speed
        )
    if spec.mode == "capped_confidence":
        return (
            spec.confidence_weight * min(confidence, spec.confidence_cap)
            + spec.price_weight * price_efficiency
            + spec.speed_weight * speed
        )
    if spec.mode == "geometric":
        # A balanced objective: one strong bid dimension cannot fully compensate for
        # another dimension collapsing toward zero.
        return max(0.0, confidence * price_efficiency * speed) ** (1.0 / 3.0)
    raise ValueError(f"unsupported matching objective: {spec.mode}")


def objective_score(task: MarketTask, bid: MarketBid, spec: MatchingObjectiveSpec) -> float:
    """Score one sealed bid under the experimental matching objective."""
    raw_cycle = task.success_condition.get("campaign_cycle")
    cycle = int(raw_cycle) if raw_cycle is not None else 0
    if spec.restore_after_cycle is not None and cycle >= spec.restore_after_cycle:
        return production_bid_score(task, bid)
    baseline = production_bid_score(task, bid)
    alternative = _unblended_score(task, bid, spec)
    return (1.0 - spec.blend) * baseline + spec.blend * alternative


def matching_arm(
    config: MatchingConfig,
    *,
    label: str,
    environment=None,
) -> lc.LifecycleArmSpec:
    env = environment if environment is not None else matching_environment(config)
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


def _task_from_group(rows: Sequence[Mapping[str, object]]) -> MarketTask:
    first = rows[0]
    return MarketTask(
        task_id=first["task_id"],  # type: ignore[arg-type]
        requester_agent_id=first["requester_agent_id"],  # type: ignore[arg-type]
        escrow_account_id=first["escrow_account_id"],  # type: ignore[arg-type]
        description=str(first["description"]),
        budget=int(first["budget"]),
        deadline=first["deadline"],  # type: ignore[arg-type]
        created_at=first["task_created_at"],  # type: ignore[arg-type]
        required_capabilities=tuple(first["required_capabilities"] or ()),  # type: ignore[arg-type]
        success_condition=first["success_condition"] or {},  # type: ignore[arg-type]
        status=str(first["task_status"]),
        awarded_agent_id=first["awarded_agent_id"],  # type: ignore[arg-type]
        winning_bid_id=first["winning_bid_id"],  # type: ignore[arg-type]
        awarded_at=first["awarded_at"],  # type: ignore[arg-type]
        completed_at=first["completed_at"],  # type: ignore[arg-type]
    )


def _bid_from_row(row: Mapping[str, object]) -> MarketBid:
    return MarketBid(
        bid_id=row["bid_id"],  # type: ignore[arg-type]
        task_id=row["task_id"],  # type: ignore[arg-type]
        bidder_agent_id=row["bidder_agent_id"],  # type: ignore[arg-type]
        price=int(row["price"]),
        confidence=float(row["confidence"]),
        estimated_completion_seconds=int(row["estimated_completion_seconds"]),
        strategy_summary=str(row["strategy_summary"]),
        submitted_at=row["submitted_at"],  # type: ignore[arg-type]
        status=str(row["bid_status"]),
    )


def _winner_repeat_rebound(
    rows: Sequence[Mapping[str, object]],
    *,
    restore_after_cycle: int | None,
    shift_period: int,
) -> float:
    if restore_after_cycle is None:
        return 0.0
    previous: dict[int, int] = {}
    repeats: list[tuple[int, float]] = []
    for row in rows:
        domain = int(row["domain"])
        winner = int(row["winner"])
        if domain in previous:
            repeats.append((int(row["cycle"]), float(previous[domain] == winner)))
        previous[domain] = winner
    width = shift_period
    pre = [
        value
        for cycle, value in repeats
        if max(0, restore_after_cycle - width) <= cycle < restore_after_cycle
    ]
    post = [
        value
        for cycle, value in repeats
        if restore_after_cycle <= cycle < restore_after_cycle + width
    ]
    return (statistics.mean(post) if post else 0.0) - (statistics.mean(pre) if pre else 0.0)


def _replay(
    connection: Connection[Any],
    *,
    run_id: str,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    label: str,
    seed: int,
    environment,
    spec: MatchingObjectiveSpec,
) -> tuple[dict[str, float], dict[str, bool], list[dict[str, object]]]:
    rows = connection.execute(
        """
        SELECT
            o.cycle, o.regime, o.domain_index, o.winner_slot, o.success, o.task_id,
            mt.requester_agent_id, mt.escrow_account_id, mt.description, mt.budget,
            mt.deadline, mt.created_at AS task_created_at, mt.required_capabilities,
            mt.success_condition, mt.status AS task_status, mt.awarded_agent_id,
            mt.winning_bid_id, mt.awarded_at, mt.completed_at,
            mb.bid_id, mb.bidder_agent_id, mb.price, mb.confidence,
            mb.estimated_completion_seconds, mb.strategy_summary, mb.submitted_at,
            mb.status AS bid_status
        FROM integration_campaign_outcomes o
        JOIN market_tasks mt ON mt.task_id = o.task_id
        JOIN market_bids mb ON mb.task_id = o.task_id
        WHERE o.run_id = %s
        ORDER BY o.cycle, mb.submitted_at, mb.bid_id
        """,
        (UUID(run_id),),
    ).fetchall()
    by_cycle: dict[int, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        by_cycle[int(row["cycle"])].append(row)

    expected_run_id = uuid5(
        NAMESPACE_URL,
        f"lifecycle:{code_sha}:{config_hash}:{experiment_number}:{label}:{seed}",
    )
    if str(expected_run_id) != run_id:
        raise RuntimeError("matching replay run identity mismatch")
    agent_ids = tuple(
        uuid5(expected_run_id, f"agent:{slot}:generation:0")
        for slot in range(environment.agents)
    )
    slot_by_agent = {agent_id: slot for slot, agent_id in enumerate(agent_ids)}

    observations: list[dict[str, object]] = []
    baseline_rows: list[dict[str, object]] = []
    objective_rows: list[dict[str, object]] = []
    actual_rows: list[dict[str, object]] = []
    override_flags: list[float] = []
    pre_override: list[float] = []
    post_override: list[float] = []
    replay_exact: list[bool] = []
    candidate_exact: list[bool] = []
    selected_confidences: list[float] = []
    selected_max_confidence: list[float] = []

    for cycle in range(environment.cycles):
        group = by_cycle.get(cycle)
        if not group:
            raise RuntimeError(f"missing sealed-bid replay rows for cycle {cycle}")
        task = _task_from_group(group)
        bids = [_bid_from_row(row) for row in group]
        requester_slot = lc._requester_slot(environment, seed, cycle)
        expected_candidates = set(
            lc._candidate_slots(
                seed,
                cycle,
                agents=environment.agents,
                requester_slot=requester_slot,
                count=environment.candidate_count,
            )
        )
        bidder_slots = {slot_by_agent[bid.bidder_agent_id] for bid in bids}
        candidate_exact.append(bidder_slots == expected_candidates)

        baseline_ranked = sorted(
            bids,
            key=lambda bid: (
                -production_bid_score(task, bid),
                bid.submitted_at,
                str(bid.bid_id),
            ),
        )
        objective_ranked = sorted(
            bids,
            key=lambda bid: (
                -objective_score(task, bid, spec),
                bid.submitted_at,
                str(bid.bid_id),
            ),
        )
        baseline_winner = baseline_ranked[0]
        objective_winner = objective_ranked[0]
        actual_winner_id = task.winning_bid_id
        replay_exact.append(actual_winner_id == objective_winner.bid_id)
        overridden = float(baseline_winner.bid_id != objective_winner.bid_id)
        effective_intervention = spec.restore_after_cycle is None or cycle < spec.restore_after_cycle
        if spec.intervention and effective_intervention:
            override_flags.append(overridden)
        if spec.restore_after_cycle is not None:
            (pre_override if cycle < spec.restore_after_cycle else post_override).append(overridden)

        objective_winner_slot = slot_by_agent[objective_winner.bidder_agent_id]
        baseline_winner_slot = slot_by_agent[baseline_winner.bidder_agent_id]
        actual_winner_slot = int(group[0]["winner_slot"])
        success = bool(group[0]["success"])
        domain = int(group[0]["domain_index"])
        regime = int(group[0]["regime"])
        baseline_rows.append(
            {"cycle": cycle, "regime": regime, "domain": domain, "winner": baseline_winner_slot, "success": success}
        )
        objective_rows.append(
            {"cycle": cycle, "regime": regime, "domain": domain, "winner": objective_winner_slot, "success": success}
        )
        actual_rows.append(
            {"cycle": cycle, "regime": regime, "domain": domain, "winner": actual_winner_slot, "success": success}
        )
        selected_confidences.append(objective_winner.confidence)
        max_confidence = max(bid.confidence for bid in bids)
        selected_max_confidence.append(float(abs(objective_winner.confidence - max_confidence) < 1e-12))

        for bid in bids:
            observations.append(
                {
                    "cycle": cycle,
                    "task_id": task.task_id,
                    "bid_id": bid.bid_id,
                    "bidder_slot": slot_by_agent[bid.bidder_agent_id],
                    "baseline_score": production_bid_score(task, bid),
                    "objective_score": objective_score(task, bid, spec),
                    "selected": bid.bid_id == actual_winner_id,
                    "baseline_selected": bid.bid_id == baseline_winner.bid_id,
                    "objective_selected": bid.bid_id == objective_winner.bid_id,
                    "objective_mode": (
                        "baseline"
                        if spec.restore_after_cycle is not None and cycle >= spec.restore_after_cycle
                        else spec.mode
                    ),
                    "created_at": task.deadline,
                }
            )

    baseline_summary = _summarize_rows(
        baseline_rows,
        domain_count=len(environment.domains),
        shift_period=environment.shift_period,
    )
    objective_summary = _summarize_rows(
        objective_rows,
        domain_count=len(environment.domains),
        shift_period=environment.shift_period,
    )
    metrics = {
        "objective_override_rate": statistics.mean(override_flags) if override_flags else 0.0,
        "baseline_replay_incumbent_share": baseline_summary["early_incumbent_share"],
        "objective_replay_incumbent_share": objective_summary["early_incumbent_share"],
        "same_bid_logical_improvement": (
            baseline_summary["early_incumbent_share"] - objective_summary["early_incumbent_share"]
        ),
        "objective_replay_exact_rate": statistics.mean(float(value) for value in replay_exact),
        "mean_selected_bid_confidence": statistics.mean(selected_confidences),
        "selected_max_confidence_share": statistics.mean(selected_max_confidence),
        "pre_restore_objective_override_rate": statistics.mean(pre_override) if pre_override else 0.0,
        "post_restore_objective_override_rate": statistics.mean(post_override) if post_override else 0.0,
        "restoration_winner_rebound": _winner_repeat_rebound(
            actual_rows,
            restore_after_cycle=spec.restore_after_cycle,
            shift_period=environment.shift_period,
        ),
        "matching_observation_rows": float(len(observations)),
    }
    invariants = {
        "objective_replay_exact": all(replay_exact),
        "candidate_set_baseline_exact": all(candidate_exact),
        "matching_observation_complete": len(observations)
        == environment.cycles * environment.candidate_count,
    }
    return metrics, invariants, observations


def _persist_observations(
    connection: Connection[Any],
    *,
    run_id: str,
    observations: Sequence[Mapping[str, object]],
) -> None:
    with connection.transaction():
        for row in observations:
            connection.execute(
                """
                INSERT INTO matching_objective_observations (
                    run_id, cycle, task_id, bid_id, bidder_slot,
                    baseline_score, objective_score, selected,
                    baseline_counterfactual_selected, objective_counterfactual_selected,
                    objective_mode, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    UUID(run_id),
                    row["cycle"],
                    row["task_id"],
                    row["bid_id"],
                    row["bidder_slot"],
                    row["baseline_score"],
                    row["objective_score"],
                    row["selected"],
                    row["baseline_selected"],
                    row["objective_selected"],
                    row["objective_mode"],
                    row["created_at"],
                ),
            )


def run_matching_cell(
    connection: Connection[Any],
    *,
    config: MatchingConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    label: str,
    spec: MatchingObjectiveSpec,
    seed: int,
    environment=None,
) -> dict[str, object]:
    arm = matching_arm(config, label=label, environment=environment)
    original_score = market_postgres.bid_score

    def experimental_score(task: MarketTask, bid: MarketBid) -> float:
        return objective_score(task, bid, spec)

    market_postgres.bid_score = experimental_score
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
        market_postgres.bid_score = original_score

    replay_metrics, replay_invariants, observations = _replay(
        connection,
        run_id=str(cell["run_id"]),
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=experiment_number,
        label=label,
        seed=seed,
        environment=arm.environment,
        spec=spec,
    )
    metrics = dict(cell["metrics"])
    metrics.update(replay_metrics)
    cell["metrics"] = metrics
    invariants = dict(cell["invariants"])
    invariants.update(replay_invariants)
    invariants["identity_turnover_absent"] = float(metrics.get("exit_count", 0.0)) == 0.0
    invariants["matching_reputation_neutral"] = arm.policy.mode == "none"
    cell["invariants"] = invariants
    cell["matching_objective"] = spec.as_dict()
    _persist_observations(connection, run_id=str(cell["run_id"]), observations=observations)
    return cell


def run_matching_arm(
    connection: Connection[Any],
    *,
    config: MatchingConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    label: str,
    spec: MatchingObjectiveSpec,
    seeds: Sequence[int],
    environment=None,
) -> dict[str, object]:
    cells = [
        run_matching_cell(
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
    aggregate["matching_objective"] = spec.as_dict()
    return aggregate


def run_matching_arms(
    connection: Connection[Any],
    *,
    config: MatchingConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    specs: Sequence[tuple[str, MatchingObjectiveSpec]],
    seeds: Sequence[int] | None = None,
    environment=None,
) -> list[dict[str, object]]:
    actual_seeds = seeds if seeds is not None else config.integration.seeds
    return [
        run_matching_arm(
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
    "matching_arm",
    "objective_score",
    "run_matching_arm",
    "run_matching_arms",
    "run_matching_cell",
]
