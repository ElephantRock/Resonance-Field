"""Real-market capability-decay machinery for Experiments 081–086."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from . import lifecycle_campaign as lc
from .capability_config import CapabilityDecaySpec
from .integration_campaign import IntegrationCampaignConfig, IntegrationEnvironment
from .lifecycle_corrections import _isolated_public_trace_stats
from .two_timescale_metrics import forgetting_timescale_from_observations


@dataclass(frozen=True, slots=True)
class CapabilityArmSpec:
    label: str
    environment: IntegrationEnvironment
    decay: CapabilityDecaySpec
    public_trace_confidence_weight: float
    retrieval_top_k: int
    knowledge_signal_threshold: float
    dormant_inactivity_threshold: int
    formation_target_fraction: float
    formation_window: int
    formation_persistence: int
    association_reference_window: int
    association_rolling_window: int
    association_target_fraction: float
    association_persistence: int
    clock_visit_margin: float


def effective_practice_value(
    *,
    cumulative: int,
    anchor_effective: float,
    last_practice_cycle: int | None,
    current_cycle: int,
    spec: CapabilityDecaySpec,
) -> tuple[float, int, float]:
    """Return effective practice, inactivity age, and kernel retention multiplier."""
    if cumulative <= 0 or last_practice_cycle is None:
        return 0.0, current_cycle + 1, 1.0
    idle = max(0, current_cycle - last_practice_cycle)
    if spec.mode == "none":
        return float(cumulative), idle, 1.0
    if spec.mode in {"exponential", "exponential_floor"}:
        assert spec.half_life_cycles is not None
        multiplier = 2 ** (-idle / spec.half_life_cycles)
        decayed = anchor_effective * multiplier
        floor = spec.retention_floor * cumulative
        return max(floor, decayed), idle, multiplier
    assert spec.mode == "step"
    assert spec.inactive_cycles is not None
    multiplier = 1.0 if idle < spec.inactive_cycles else 0.0
    return anchor_effective * multiplier, idle, multiplier


def _float_gini(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    total = sum(values)
    if total <= 0:
        return 0.0
    ordered = sorted(values)
    count = len(ordered)
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    return (2 * weighted) / (count * total) - (count + 1) / count


def _formation_timescale(
    expected: Sequence[float],
    *,
    env: IntegrationEnvironment,
    target_fraction: float,
    window: int,
    persistence: int,
) -> float:
    if not expected:
        return 0.0
    target = env.base_success_probability + target_fraction * (
        env.maximum_success_probability - env.base_success_probability
    )
    if len(expected) < window:
        return float(len(expected))
    consecutive = 0
    first_endpoint = len(expected)
    for end in range(window, len(expected) + 1):
        rolling = statistics.mean(expected[end - window : end])
        if rolling >= target:
            consecutive += 1
            if consecutive == 1:
                first_endpoint = end
            if consecutive >= persistence:
                return float(first_endpoint)
        else:
            consecutive = 0
            first_endpoint = len(expected)
    return float(len(expected))


def _mean_mapping(rows: Sequence[Mapping[str, float]]) -> dict[str, float]:
    keys = rows[0].keys()
    return {key: statistics.mean(float(row[key]) for row in rows) for key in keys}


def _aggregate_arm(cells: Sequence[Mapping[str, object]]) -> dict[str, object]:
    metric_rows = [cell["metrics"] for cell in cells]
    assert all(isinstance(row, Mapping) for row in metric_rows)
    metrics = _mean_mapping(metric_rows)  # type: ignore[arg-type]
    invariant_rows = [cell["invariants"] for cell in cells]
    assert all(isinstance(row, Mapping) for row in invariant_rows)
    invariant_keys = invariant_rows[0].keys()  # type: ignore[union-attr]
    invariants = {
        key: all(bool(row[key]) for row in invariant_rows)  # type: ignore[index]
        for key in invariant_keys
    }
    first = cells[0]
    return {
        "label": first["arm_label"],
        "capability_decay": first["capability_decay"],
        "environment": first["environment"],
        "metrics": metrics,
        "invariants": invariants,
        "run_ids": [cell["run_id"] for cell in cells],
    }


def run_capability_arm(
    connection: Connection[Any],
    *,
    config: IntegrationCampaignConfig,
    config_hash: str,
    experiment_number: int,
    arm: CapabilityArmSpec,
    seed: int,
    code_sha: str,
) -> dict[str, object]:
    """Run one immortal capability-decay arm through the production sealed-bid market."""
    if not connection.autocommit:
        raise ValueError("capability-decay campaign requires autocommit")
    connection.row_factory = lc.dict_row
    env = arm.environment
    run_id = lc.uuid5(
        lc.NAMESPACE_URL,
        f"capability-decay:{code_sha}:{config_hash}:{experiment_number}:{arm.label}:{seed}",
    )
    start = lc._BASE_TIME + timedelta(days=experiment_number, hours=seed % 17)
    economy = lc.PostgresEconomyRepository(connection)
    reputation = lc.PostgresReputationRepository(connection)
    traces = lc.PostgresTraceRepository(connection)

    active_ids: list[UUID] = []
    author_lineage: dict[UUID, int] = {}
    cumulative: dict[tuple[UUID, str], int] = {}
    effective_anchor: dict[tuple[UUID, str], float] = {}
    last_practice: dict[tuple[UUID, str], int] = {}
    practice_intervals: list[float] = []

    for slot in range(env.agents):
        agent_id = lc.uuid5(run_id, f"agent:{slot}:generation:0")
        economy.register_agent(
            agent_id,
            at=start,
            generation=0,
            initial_credits=env.initial_credits,
        )
        active_ids.append(agent_id)
        author_lineage[agent_id] = slot

    rows: list[dict[str, object]] = []
    task_ids: list[UUID] = []
    first_bid_id: UUID | None = None
    first_score_id: UUID | None = None
    public_signals: list[float] = []
    coverage_flags: list[float] = []
    cultural_hhis: list[float] = []
    expected_probabilities: list[float] = []
    candidate_ginis: list[float] = []
    winner_advantages: list[float] = []
    recent_winner_flags: list[float] = []
    refresh_advantages: list[float] = []
    dormant_ratios: list[float] = []
    all_effective_ratios: list[float] = []
    decay_tau_samples: list[float] = []
    observation_rows: list[dict[str, object]] = []
    regime_rank_snapshots: list[dict[str, UUID]] = []
    history_preserved = True

    def state_for(agent_id: UUID, skill: str, cycle: int) -> tuple[float, int, float, int]:
        key = (agent_id, skill)
        count = cumulative.get(key, 0)
        effective, idle, multiplier = effective_practice_value(
            cumulative=count,
            anchor_effective=effective_anchor.get(key, 0.0),
            last_practice_cycle=last_practice.get(key),
            current_cycle=cycle,
            spec=arm.decay,
        )
        return effective, idle, multiplier, count

    for cycle in range(env.cycles):
        task_at = start + timedelta(seconds=cycle * env.cycle_seconds)
        regime = cycle // env.shift_period
        regime_start_cycle = regime * env.shift_period
        regime_start_at = start + timedelta(seconds=regime_start_cycle * env.cycle_seconds)
        domain_index = lc._domain_index(seed, cycle, len(env.domains))
        task_domain = env.domains[domain_index]
        required_index = (domain_index + regime) % len(env.domains)
        required_skill = env.domains[required_index]

        public = _isolated_public_trace_stats(
            connection,
            skill=required_skill,
            at=task_at,
            author_lineage=author_lineage,
            departed_agents=set(),
            top_k=arm.retrieval_top_k,
            diversified=False,
            diversified_lineages=1,
        )
        public_signals.append(public["signal"])
        coverage_flags.append(float(public["signal"] >= arm.knowledge_signal_threshold))
        cultural_hhis.append(public["lineage_hhi"])

        market = lc.PostgresMarketService(connection, economy)
        requester_slot = lc._requester_slot(env, seed, cycle)
        requester_id = active_ids[requester_slot]
        task = market.post_task(
            requester_id,
            description=f"Capability-decay delegation for {task_domain}",
            budget=env.task_budget,
            deadline=task_at + timedelta(seconds=env.bid_deadline_seconds),
            at=task_at,
            required_capabilities=(required_skill,),
            success_condition={
                "task_domain": task_domain,
                "required_skill": required_skill,
                "campaign_cycle": cycle,
                "regime": regime,
                "regime_start_at": regime_start_at.isoformat(),
            },
        )
        task_ids.append(task.task_id)

        candidates = lc._candidate_slots(
            seed,
            cycle,
            agents=env.agents,
            requester_slot=requester_slot,
            count=env.candidate_count,
        )
        candidate_state: dict[UUID, tuple[float, int, float, int, int]] = {}
        for candidate_slot in candidates:
            candidate_id = active_ids[candidate_slot]
            effective, idle, multiplier, count = state_for(
                candidate_id,
                required_skill,
                cycle,
            )
            candidate_state[candidate_id] = (
                effective,
                idle,
                multiplier,
                count,
                candidate_slot,
            )
            if count > 0:
                ratio = effective / count
                all_effective_ratios.append(ratio)
                if idle >= arm.dormant_inactivity_threshold:
                    dormant_ratios.append(ratio)
            if idle > 0 and 0.0 < multiplier < 1.0:
                decay_tau_samples.append(idle / -math.log2(multiplier))

            own_signal = lc._trace_signal(
                connection,
                agent_id=candidate_id,
                skill=required_skill,
                at=task_at,
            )
            confidence = (
                env.confidence_base
                + env.confidence_evidence_weight * own_signal
                + arm.public_trace_confidence_weight * public["signal"]
                + env.confidence_noise_weight
                * lc._draw(seed, cycle, candidate_slot, "confidence")
            )
            confidence = max(0.05, min(0.98, confidence))
            price_fraction = env.price_floor + env.price_span * lc._draw(
                seed,
                cycle,
                candidate_slot,
                "price",
            )
            price = max(
                1,
                min(env.task_budget, int(env.task_budget * min(0.95, price_fraction))),
            )
            completion = env.completion_min_seconds + int(
                env.completion_span_seconds
                * lc._draw(seed, cycle, candidate_slot, "speed")
            )
            completion = min(max(1, completion), env.bid_deadline_seconds - 1)
            bid = market.submit_bid(
                candidate_id,
                task_id=task.task_id,
                price=price,
                confidence=confidence,
                estimated_completion_seconds=completion,
                strategy_summary=f"capability-decay generic bid slot {candidate_slot}",
                at=task_at + timedelta(microseconds=candidate_slot + 1),
            )
            if first_bid_id is None:
                first_bid_id = bid.bid_id

        candidate_ginis.append(
            _float_gini([value[0] for value in candidate_state.values()])
        )
        award = market.award(task.task_id, at=task.deadline)
        assert award is not None
        winner_id = award.winning_bid.bidder_agent_id
        winner_slot = active_ids.index(winner_id)
        winner_effective, winner_idle, _, practiced, _ = candidate_state[winner_id]
        challenger_values = [
            value[0] for agent_id, value in candidate_state.items() if agent_id != winner_id
        ]
        advantage = winner_effective - (
            statistics.mean(challenger_values) if challenger_values else 0.0
        )
        winner_advantages.append(advantage)
        recent = float(
            practiced > 0 and winner_idle <= arm.dormant_inactivity_threshold
        )
        recent_winner_flags.append(recent)
        if recent:
            refresh_advantages.append(advantage)

        score_row = connection.execute(
            """
            SELECT auction_score_id, components
            FROM market_auction_scores
            WHERE task_id = %s AND selected
            """,
            (task.task_id,),
        ).fetchone()
        assert score_row is not None
        if first_score_id is None:
            first_score_id = score_row["auction_score_id"]
        components = dict(score_row["components"] or {})
        reputation_score = float(components.get("reputation_score", 0.5))

        success_probability = min(
            env.maximum_success_probability,
            env.base_success_probability + env.practice_gain * math.sqrt(winner_effective),
        )
        expected_probabilities.append(success_probability)
        success = lc._draw(seed, cycle, winner_slot, "outcome") < success_probability
        noise_flip = lc._draw(seed, cycle, winner_slot, "evidence-noise") < env.evidence_noise
        recorded_positive = not success if noise_flip else success
        outcome_at = task.deadline + timedelta(seconds=1)

        market.settle(task.task_id, at=outcome_at)
        reputation.record_evidence(
            winner_id,
            dimension=lc._DOMAIN_DIMENSION,
            context_key=task_domain,
            positive=recorded_positive,
            source_type="integration_domain",
            source_id=task.task_id,
            at=outcome_at,
        )
        reputation.record_evidence(
            winner_id,
            dimension=lc._SKILL_DIMENSION,
            context_key=required_skill,
            positive=recorded_positive,
            source_type="integration_skill",
            source_id=task.task_id,
            at=outcome_at,
        )
        if cycle == 0:
            reputation.record_evidence(
                winner_id,
                dimension=lc._DOMAIN_DIMENSION,
                context_key=task_domain,
                positive=recorded_positive,
                source_type="integration_domain",
                source_id=task.task_id,
                at=outcome_at,
            )
        if success:
            traces.add(
                lc.Trace(
                    author_agent_id=winner_id,
                    kind="VERIFIED_OUTCOME",
                    content=f"skill-evidence:{required_skill}",
                    created_at=outcome_at,
                    updated_at=outcome_at,
                    initial_energy=0.9,
                    half_life_seconds=env.trace_half_life_cycles * env.cycle_seconds,
                    confidence=1.0,
                    quality_score=1.0,
                )
            )

        key = (winner_id, required_skill)
        prior_cycle = last_practice.get(key)
        if prior_cycle is not None:
            practice_intervals.append(float(cycle - prior_cycle))
        old_cumulative = cumulative.get(key, 0)
        new_cumulative = old_cumulative + 1
        cumulative[key] = new_cumulative
        effective_anchor[key] = winner_effective + 1.0
        last_practice[key] = cycle
        history_preserved = history_preserved and new_cumulative >= old_cumulative

        for agent_id, value in candidate_state.items():
            effective, idle, _, count, candidate_slot = value
            observation_rows.append(
                {
                    "run_id": run_id,
                    "cycle": cycle,
                    "agent_id": agent_id,
                    "skill": required_skill,
                    "candidate_slot": candidate_slot,
                    "selected": agent_id == winner_id,
                    "cumulative_practice": count,
                    "effective_practice": effective,
                    "inactivity_cycles": idle,
                    "created_at": task_at,
                }
            )

        rows.append(
            {
                "cycle": cycle,
                "regime": regime,
                "task_id": task.task_id,
                "domain": domain_index,
                "task_domain": task_domain,
                "required_skill": required_skill,
                "winner": winner_slot,
                "winner_agent_id": winner_id,
                "winner_generation": 0,
                "success": success,
                "recorded_positive": recorded_positive,
                "reputation_score": reputation_score,
                "winning_price": award.winning_bid.price,
                "task_budget": env.task_budget,
                "public_trace_signal": public["signal"],
                "effective_practice": winner_effective,
                "cumulative_practice": practiced,
                "expected_success_probability": success_probability,
                "created_at": task_at,
            }
        )

        if (cycle + 1) % env.shift_period == 0:
            snapshot: dict[str, UUID] = {}
            for skill in env.domains:
                ranked = [
                    (state_for(agent_id, skill, cycle)[0], str(agent_id), agent_id)
                    for agent_id in active_ids
                ]
                snapshot[skill] = max(ranked)[2]
            regime_rank_snapshots.append(snapshot)

    assert first_bid_id is not None and first_score_id is not None
    structural = lc._summarize_rows(
        rows,
        domain_count=len(env.domains),
        shift_period=env.shift_period,
    )
    identity_incumbent, identity_replacement = lc._identity_incumbent_metrics(
        rows,
        domain_count=len(env.domains),
        shift_period=env.shift_period,
    )
    brier = statistics.mean(
        (float(row["reputation_score"]) - float(bool(row["success"]))) ** 2
        for row in rows
    )
    price_fraction = statistics.mean(
        int(row["winning_price"]) / int(row["task_budget"]) for row in rows
    )
    active_balances = [economy.balance(agent_id) for agent_id in active_ids]
    late_start = env.cycles // 2
    late_coverage = coverage_flags[late_start:]
    late_hhi = cultural_hhis[late_start:]
    late_signals = public_signals[late_start:]

    turnover_values: list[float] = []
    for before, after in zip(regime_rank_snapshots, regime_rank_snapshots[1:], strict=False):
        turnover_values.append(
            sum(before[skill] != after[skill] for skill in env.domains) / len(env.domains)
        )
    observations = [
        (
            int(row["cycle"]),
            str(row["task_domain"]),
            str(row["required_skill"]),
            int(row["winner"]),
        )
        for row in rows
    ]
    tau_d_assoc, _, _ = forgetting_timescale_from_observations(
        observations,
        shift_period=env.shift_period,
        agents=env.agents,
        reference_window=arm.association_reference_window,
        rolling_window=arm.association_rolling_window,
        target_fraction=arm.association_target_fraction,
        persistence=arm.association_persistence,
    )
    tau_f = _formation_timescale(
        expected_probabilities,
        env=env,
        target_fraction=arm.formation_target_fraction,
        window=arm.formation_window,
        persistence=arm.formation_persistence,
    )
    tau_visit = (
        statistics.mean(practice_intervals) if practice_intervals else float(env.cycles)
    )
    if arm.decay.timescale is None:
        declared_tau_skill = float(env.cycles * 2)
        empirical_tau_skill = float(env.cycles * 2)
        decay_censored = 1.0
    else:
        declared_tau_skill = float(arm.decay.timescale)
        if arm.decay.mode == "step":
            dropped = [
                int(row["inactivity_cycles"])
                for row in observation_rows
                if int(row["cumulative_practice"]) > 0
                and float(row["effective_practice"]) == 0.0
            ]
            empirical_tau_skill = float(min(dropped)) if dropped else declared_tau_skill
        else:
            empirical_tau_skill = (
                statistics.median(decay_tau_samples)
                if decay_tau_samples
                else declared_tau_skill
            )
        decay_censored = 0.0
    clock_inside = float(
        tau_visit * arm.clock_visit_margin < declared_tau_skill < env.shift_period
        and tau_f < env.shift_period
    )

    metrics: dict[str, float] = {
        **structural,
        "identity_early_incumbent_share": identity_incumbent,
        "identity_replacement_rate": identity_replacement,
        "reputation_brier_score": brier,
        "mean_winning_price_fraction": price_fraction,
        "credit_gini": lc._gini(active_balances),
        "exit_count": 0.0,
        "turnover_rate": 0.0,
        "mean_active_age": statistics.mean(range(env.cycles)) if env.cycles else 0.0,
        "public_knowledge_coverage": statistics.mean(coverage_flags) if coverage_flags else 0.0,
        "late_public_knowledge_coverage": statistics.mean(late_coverage) if late_coverage else 0.0,
        "mean_public_trace_signal": statistics.mean(public_signals) if public_signals else 0.0,
        "late_mean_public_trace_signal": statistics.mean(late_signals) if late_signals else 0.0,
        "cultural_lineage_hhi": statistics.mean(cultural_hhis) if cultural_hhis else 0.0,
        "late_cultural_lineage_hhi": statistics.mean(late_hhi) if late_hhi else 0.0,
        "retired_trace_retrieval_share": 0.0,
        "mean_consultation_signal": 0.0,
        "max_generation": 0.0,
        "foreign_trace_retrieval_share": 0.0,
        "mean_effective_practice": statistics.mean(
            float(row["effective_practice"]) for row in observation_rows
        ),
        "mean_cumulative_practice": statistics.mean(
            float(row["cumulative_practice"]) for row in observation_rows
        ),
        "mean_effective_to_cumulative_ratio": (
            statistics.mean(all_effective_ratios) if all_effective_ratios else 1.0
        ),
        "dormant_effective_ratio": (
            statistics.mean(dormant_ratios) if dormant_ratios else 1.0
        ),
        "dormant_sample_count": float(len(dormant_ratios)),
        "mean_effective_practice_gini": (
            statistics.mean(candidate_ginis) if candidate_ginis else 0.0
        ),
        "mean_winner_effective_advantage": (
            statistics.mean(winner_advantages) if winner_advantages else 0.0
        ),
        "winner_recent_practice_share": (
            statistics.mean(recent_winner_flags) if recent_winner_flags else 0.0
        ),
        "incumbent_refresh_feedback": (
            statistics.mean(refresh_advantages) if refresh_advantages else 0.0
        ),
        "mean_reuse_interval": tau_visit,
        "skill_rank_turnover": (
            statistics.mean(turnover_values) if turnover_values else 0.0
        ),
        "tau_f": tau_f,
        "tau_d_assoc": float(tau_d_assoc),
        "tau_visit": tau_visit,
        "tau_d_skill": declared_tau_skill,
        "tau_d_skill_empirical": empirical_tau_skill,
        "skill_decay_censored": decay_censored,
        "clock_window_inside": clock_inside,
    }
    invariants = lc._run_invariants(
        connection,
        task_ids=task_ids,
        agent_ids=active_ids,
        first_bid_id=first_bid_id,
        first_score_id=first_score_id,
        expected_evidence=2 * env.cycles,
    )
    invariants = {
        **invariants,
        "cell_trace_isolated": True,
        "identity_turnover_zero": True,
        "capability_history_preserved": history_preserved,
        "capability_observations_complete": (
            len(observation_rows) == env.cycles * env.candidate_count
        ),
    }

    with connection.transaction():
        connection.execute(
            """
            INSERT INTO integration_campaign_runs (
                run_id, campaign_name, experiment_number, arm_label, seed,
                policy, environment, metrics, invariants, completed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                config.name,
                experiment_number,
                arm.label,
                seed,
                Jsonb(
                    {
                        "reputation": {"mode": "none", "weight": 0.0},
                        "capability_decay": arm.decay.as_dict(),
                    }
                ),
                Jsonb(env.as_dict()),
                Jsonb(metrics),
                Jsonb(invariants),
                start + timedelta(seconds=env.cycles * env.cycle_seconds),
            ),
        )
        for row in rows:
            connection.execute(
                """
                INSERT INTO integration_campaign_outcomes (
                    run_id, cycle, regime, task_id, task_domain, domain_index,
                    required_skill, winner_agent_id, winner_slot, success,
                    recorded_positive, reputation_score, winning_price,
                    task_budget, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    run_id,
                    row["cycle"],
                    row["regime"],
                    row["task_id"],
                    row["task_domain"],
                    row["domain"],
                    row["required_skill"],
                    row["winner_agent_id"],
                    row["winner"],
                    row["success"],
                    row["recorded_positive"],
                    row["reputation_score"],
                    row["winning_price"],
                    row["task_budget"],
                    row["created_at"],
                ),
            )
        for row in observation_rows:
            connection.execute(
                """
                INSERT INTO capability_practice_observations (
                    run_id, cycle, agent_id, skill, candidate_slot, selected,
                    cumulative_practice, effective_practice, inactivity_cycles, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    row["run_id"],
                    row["cycle"],
                    row["agent_id"],
                    row["skill"],
                    row["candidate_slot"],
                    row["selected"],
                    row["cumulative_practice"],
                    row["effective_practice"],
                    row["inactivity_cycles"],
                    row["created_at"],
                ),
            )

    return {
        "run_id": str(run_id),
        "seed": seed,
        "arm_label": arm.label,
        "capability_decay": arm.decay.as_dict(),
        "environment": env.as_dict(),
        "metrics": metrics,
        "invariants": invariants,
    }


def run_capability_experiment(
    connection: Connection[Any],
    *,
    config: IntegrationCampaignConfig,
    config_hash: str,
    experiment_number: int,
    arms: Sequence[CapabilityArmSpec],
    seeds: Sequence[int],
    code_sha: str,
) -> list[dict[str, object]]:
    """Run and aggregate capability-decay arms over paired seeds."""
    aggregated: list[dict[str, object]] = []
    for arm in arms:
        cells = [
            run_capability_arm(
                connection,
                config=config,
                config_hash=config_hash,
                experiment_number=experiment_number,
                arm=arm,
                seed=seed,
                code_sha=code_sha,
            )
            for seed in seeds
        ]
        aggregated.append(_aggregate_arm(cells))
    return aggregated


__all__ = [
    "CapabilityArmSpec",
    "effective_practice_value",
    "run_capability_arm",
    "run_capability_experiment",
]
