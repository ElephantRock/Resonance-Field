"""Validity corrections for Lifecycle & Succession Experiments 063–074.

The initial lifecycle implementation reached main before a late automated review exposed
several scientific confounds.  This module installs a narrow correction layer for the
checkpointed campaign without changing the production market.  The corrected protocol:

* isolates public traces to the current experimental cell;
* transfers a predecessor's exact remaining compute balance to its successor;
* measures public knowledge over matched all-cycle and late-cycle windows;
* treats logical-slot persistence, not forced UUID replacement, as plasticity evidence;
* gives retirement a bounded read-only consultation channel while death has none;
* matches stochastic expected lifetime to the fixed-lifetime target; and
* requires plasticity plus the predeclared robustness gates in replication/holdout.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from . import lifecycle_campaign as lc
from . import lifecycle_checkpoint as cp
from .integration_campaign import ReputationPolicy


def stochastic_exit_hazard(*, lifetime_cycles: int, minimum_age: int) -> float:
    """Return a geometric hazard whose expected exit age equals ``lifetime_cycles``.

    Exit is first eligible at ``minimum_age``.  If F is the number of failures before
    the first success, E[F] = (1-p)/p, so E[exit_age] = minimum_age + E[F].
    Solving for p yields 1 / (lifetime - minimum_age + 1).
    """
    if lifetime_cycles < minimum_age:
        raise ValueError("lifetime_cycles must be at least minimum_age")
    return min(1.0, 1.0 / (lifetime_cycles - minimum_age + 1))


def corrected_should_exit(
    spec: lc.LifecycleSpec,
    *,
    seed: int,
    cycle: int,
    slot: int,
    born_cycle: int,
) -> bool:
    if not spec.finite:
        return False
    assert spec.lifetime_cycles is not None
    age = cycle - born_cycle
    if age <= 0:
        return False
    if spec.mode == "stochastic":
        if age < spec.stochastic_min_age:
            return False
        hazard = stochastic_exit_hazard(
            lifetime_cycles=spec.lifetime_cycles,
            minimum_age=spec.stochastic_min_age,
        )
        return lc._draw(seed, cycle + spec.schedule_offset, slot, "lifecycle-exit") < hazard
    return age >= spec.lifetime_cycles


def _isolated_public_trace_stats(
    connection: Connection[Any],
    *,
    skill: str,
    at,
    author_lineage: Mapping[UUID, int],
    departed_agents: set[UUID],
    top_k: int,
    diversified: bool,
    diversified_lineages: int,
) -> dict[str, float]:
    """Retrieve public traces written only by identities in the current cell."""
    authors = list(author_lineage)
    if not authors:
        return {"signal": 0.0, "lineage_hhi": 0.0, "departed_share": 0.0}
    rows = connection.execute(
        """
        SELECT author_agent_id,
               energy_anchor * power(
                   2.0,
                   -GREATEST(
                       0.0,
                       EXTRACT(EPOCH FROM (%s - energy_updated_at))::double precision
                   ) / half_life_seconds
               ) AS energy
        FROM traces
        WHERE kind = 'VERIFIED_OUTCOME'
          AND content = %s
          AND status = 'active'
          AND created_at <= %s
          AND author_agent_id = ANY(%s::uuid[])
        ORDER BY energy DESC, trace_id
        LIMIT %s
        """,
        (at, f"skill-evidence:{skill}", at, authors, max(top_k * 4, top_k)),
    ).fetchall()
    if not rows:
        return {"signal": 0.0, "lineage_hhi": 0.0, "departed_share": 0.0}

    top = rows[:top_k]
    counts = Counter(author_lineage[row["author_agent_id"]] for row in top)
    total = len(top)
    hhi = sum((count / total) ** 2 for count in counts.values()) if total else 0.0
    departed_share = (
        sum(row["author_agent_id"] in departed_agents for row in top) / total
        if total
        else 0.0
    )
    if diversified:
        maxima: dict[int, float] = {}
        for row in rows:
            lineage = author_lineage[row["author_agent_id"]]
            maxima[lineage] = max(maxima.get(lineage, 0.0), float(row["energy"]))
        selected = sorted(maxima.values(), reverse=True)[:diversified_lineages]
        signal = statistics.mean(selected) if selected else 0.0
    else:
        signal = max(float(row["energy"]) for row in rows)
    return {
        "signal": max(0.0, min(1.0, signal)),
        "lineage_hhi": hhi,
        "departed_share": departed_share,
    }


def _consultation_signal(
    connection: Connection[Any],
    *,
    consultants: Sequence[UUID],
    skill: str,
    at,
) -> float:
    if not consultants:
        return 0.0
    return max(
        (lc._trace_signal(connection, agent_id=agent_id, skill=skill, at=at) for agent_id in consultants),
        default=0.0,
    )


def _replace_with_balance(
    *,
    economy: lc.PostgresEconomyRepository,
    run_id: UUID,
    active_ids: list[UUID],
    generations: list[int],
    born_cycle: list[int],
    slot: int,
    cycle: int,
    at,
    mode: str,
    consultants: list[UUID],
    departed_agents: set[UUID],
    all_agent_ids: list[UUID],
    author_lineage: dict[UUID, int],
    lifecycle_events: list[dict[str, object]],
) -> tuple[UUID, UUID, bool]:
    """Replace an actor while preserving the slot's exact remaining compute balance."""
    old_id = active_ids[slot]
    old_balance = economy.balance(old_id)
    old_account = economy.account_for_agent(old_id)
    if old_balance:
        economy.transfer(
            old_account.account_id,
            lc.TREASURY_ACCOUNT_ID,
            old_balance,
            at=at,
            reason="lifecycle exit reclaim",
            reference_type="agent",
            reference_id=old_id,
        )

    departed_agents.add(old_id)
    if mode in {"retirement", "advisor"}:
        consultants.append(old_id)

    generations[slot] += 1
    generation = generations[slot]
    new_id = lc.uuid5(run_id, f"agent:{slot}:generation:{generation}")
    economy.register_agent(new_id, at=at, generation=generation, initial_credits=0)
    if old_balance:
        economy.issue(
            new_id,
            old_balance,
            at=at,
            reason="lifecycle succession balance transfer",
            reference_type="agent",
            reference_id=new_id,
        )
    preserved = economy.balance(new_id) == old_balance

    active_ids[slot] = new_id
    born_cycle[slot] = cycle
    all_agent_ids.append(new_id)
    author_lineage[new_id] = slot
    lifecycle_events.append(
        {
            "run_id": run_id,
            "cycle": cycle,
            "slot": slot,
            "generation": generation,
            "event_type": mode,
            "agent_id": old_id,
            "successor_agent_id": new_id,
            "created_at": at,
        }
    )
    return old_id, new_id, preserved


def corrected_run_lifecycle_arm(
    connection: Connection[Any],
    *,
    config: lc.IntegrationCampaignConfig,
    config_hash: str,
    experiment_number: int,
    arm: lc.LifecycleArmSpec,
    seed: int,
    code_sha: str,
) -> dict[str, object]:
    """Run one lifecycle arm with cell isolation and balance-preserving succession."""
    if not connection.autocommit:
        raise ValueError("lifecycle campaign requires autocommit")
    connection.row_factory = lc.dict_row
    env = arm.environment
    run_id = lc.uuid5(
        lc.NAMESPACE_URL,
        f"lifecycle:{code_sha}:{config_hash}:{experiment_number}:{arm.label}:{seed}",
    )
    start = lc._BASE_TIME + timedelta(days=experiment_number, hours=seed % 17)
    economy = lc.PostgresEconomyRepository(connection)
    reputation = lc.PostgresReputationRepository(connection)
    traces = lc.PostgresTraceRepository(connection)

    active_ids: list[UUID] = []
    all_agent_ids: list[UUID] = []
    generations = [0 for _ in range(env.agents)]
    born_cycle = [0 for _ in range(env.agents)]
    author_lineage: dict[UUID, int] = {}
    departed_agents: set[UUID] = set()
    consultants: list[UUID] = []
    practice: dict[tuple[UUID, str], int] = {}

    for slot in range(env.agents):
        agent_id = lc.uuid5(run_id, f"agent:{slot}:generation:0")
        economy.register_agent(agent_id, at=start, generation=0, initial_credits=env.initial_credits)
        active_ids.append(agent_id)
        all_agent_ids.append(agent_id)
        author_lineage[agent_id] = slot

    rows: list[dict[str, object]] = []
    task_ids: list[UUID] = []
    first_bid_id: UUID | None = None
    first_score_id: UUID | None = None
    exit_count = 0
    public_signals: list[float] = []
    coverage_flags: list[float] = []
    cultural_hhis: list[float] = []
    departed_trace_shares: list[float] = []
    active_ages: list[float] = []
    consultation_signals: list[float] = []
    lifecycle_events: list[dict[str, object]] = []
    balance_preserved = True

    for cycle in range(env.cycles):
        task_at = start + timedelta(seconds=cycle * env.cycle_seconds)
        for slot in range(env.agents):
            if corrected_should_exit(
                arm.lifecycle,
                seed=seed,
                cycle=cycle,
                slot=slot,
                born_cycle=born_cycle[slot],
            ):
                _, _, preserved = _replace_with_balance(
                    economy=economy,
                    run_id=run_id,
                    active_ids=active_ids,
                    generations=generations,
                    born_cycle=born_cycle,
                    slot=slot,
                    cycle=cycle,
                    at=task_at,
                    mode=arm.lifecycle.mode,
                    consultants=consultants,
                    departed_agents=departed_agents,
                    all_agent_ids=all_agent_ids,
                    author_lineage=author_lineage,
                    lifecycle_events=lifecycle_events,
                )
                balance_preserved = balance_preserved and preserved
                exit_count += 1

        active_ages.extend(float(cycle - born_cycle[slot]) for slot in range(env.agents))
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
            departed_agents=departed_agents,
            top_k=arm.retrieval_top_k,
            diversified=arm.lifecycle.diversified_retrieval,
            diversified_lineages=arm.diversified_lineages,
        )
        public_signals.append(public["signal"])
        coverage_flags.append(float(public["signal"] >= arm.knowledge_signal_threshold))
        cultural_hhis.append(public["lineage_hhi"])
        departed_trace_shares.append(public["departed_share"])

        provider = None
        if arm.policy.mode == "reputation":
            provider = lc.PostgresReputationBidSignalProvider(
                connection,
                policy=arm.policy,
                population=active_ids,
                cycle_seconds=env.cycle_seconds,
            )
        market = lc.PostgresMarketService(connection, economy, bid_signal_provider=provider)

        requester_slot = lc._requester_slot(env, seed, cycle)
        requester_id = active_ids[requester_slot]
        task = market.post_task(
            requester_id,
            description=f"Lifecycle delegation for {task_domain}",
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
        for candidate_slot in candidates:
            candidate_id = active_ids[candidate_slot]
            own_signal = lc._trace_signal(
                connection,
                agent_id=candidate_id,
                skill=required_skill,
                at=task_at,
            )
            consultation_signal = 0.0
            if arm.lifecycle.mode in {"retirement", "advisor"} and arm.lifecycle.advisor_weight > 0:
                consultation_signal = _consultation_signal(
                    connection,
                    consultants=consultants,
                    skill=required_skill,
                    at=task_at,
                )
            confidence = (
                env.confidence_base
                + env.confidence_evidence_weight * own_signal
                + arm.public_trace_confidence_weight * public["signal"]
                + arm.lifecycle.advisor_weight * consultation_signal
                + env.confidence_noise_weight * lc._draw(seed, cycle, candidate_slot, "confidence")
            )
            consultation_signals.append(consultation_signal)
            if own_signal < 0.20:
                confidence += env.confidence_inflation
            confidence = max(0.05, min(0.98, confidence))
            price_fraction = env.price_floor + env.price_span * lc._draw(
                seed, cycle, candidate_slot, "price"
            )
            price = max(
                1,
                min(env.task_budget, int(env.task_budget * min(0.95, price_fraction))),
            )
            completion = env.completion_min_seconds + int(
                env.completion_span_seconds * lc._draw(seed, cycle, candidate_slot, "speed")
            )
            completion = min(max(1, completion), env.bid_deadline_seconds - 1)
            bid = market.submit_bid(
                candidate_id,
                task_id=task.task_id,
                price=price,
                confidence=confidence,
                estimated_completion_seconds=completion,
                strategy_summary=f"lifecycle generic bid slot {candidate_slot}",
                at=task_at + timedelta(microseconds=candidate_slot + 1),
            )
            if first_bid_id is None:
                first_bid_id = bid.bid_id

        award = market.award(task.task_id, at=task.deadline)
        assert award is not None
        winner_id = award.winning_bid.bidder_agent_id
        winner_slot = active_ids.index(winner_id)
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

        practiced = practice.get((winner_id, required_skill), 0)
        success_probability = min(
            env.maximum_success_probability,
            env.base_success_probability + env.practice_gain * math.sqrt(practiced),
        )
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
        practice[(winner_id, required_skill)] = practiced + 1
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
                "winner_generation": generations[winner_slot],
                "success": success,
                "recorded_positive": recorded_positive,
                "reputation_score": reputation_score,
                "winning_price": award.winning_bid.price,
                "task_budget": env.task_budget,
                "public_trace_signal": public["signal"],
                "created_at": task_at,
            }
        )

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
    metrics: dict[str, float] = {
        **structural,
        "identity_early_incumbent_share": identity_incumbent,
        "identity_replacement_rate": identity_replacement,
        "reputation_brier_score": brier,
        "mean_winning_price_fraction": price_fraction,
        "credit_gini": lc._gini(active_balances),
        "exit_count": float(exit_count),
        "turnover_rate": exit_count / max(1, env.cycles * env.agents),
        "mean_active_age": statistics.mean(active_ages) if active_ages else 0.0,
        "public_knowledge_coverage": statistics.mean(coverage_flags) if coverage_flags else 0.0,
        "late_public_knowledge_coverage": statistics.mean(late_coverage) if late_coverage else 0.0,
        "mean_public_trace_signal": statistics.mean(public_signals) if public_signals else 0.0,
        "late_mean_public_trace_signal": statistics.mean(late_signals) if late_signals else 0.0,
        "cultural_lineage_hhi": statistics.mean(cultural_hhis) if cultural_hhis else 0.0,
        "late_cultural_lineage_hhi": statistics.mean(late_hhi) if late_hhi else 0.0,
        "retired_trace_retrieval_share": (
            statistics.mean(departed_trace_shares) if departed_trace_shares else 0.0
        ),
        "mean_consultation_signal": (
            statistics.mean(consultation_signals) if consultation_signals else 0.0
        ),
        "max_generation": float(max(generations)),
        "foreign_trace_retrieval_share": 0.0,
    }
    invariants = lc._run_invariants(
        connection,
        task_ids=task_ids,
        agent_ids=all_agent_ids,
        first_bid_id=first_bid_id,
        first_score_id=first_score_id,
        expected_evidence=2 * env.cycles,
    )
    invariants = {
        **invariants,
        "succession_balance_preserved": balance_preserved,
        "cell_trace_isolated": True,
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
                Jsonb({"reputation": arm.policy.as_dict(), "lifecycle": arm.lifecycle.as_dict()}),
                Jsonb(env.as_dict()),
                Jsonb(metrics),
                Jsonb(invariants),
                start + timedelta(seconds=env.cycles * env.cycle_seconds),
            ),
        )
        for event in lifecycle_events:
            connection.execute(
                """
                INSERT INTO lifecycle_events (
                    run_id, cycle, slot, generation, event_type,
                    agent_id, successor_agent_id, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event["run_id"],
                    event["cycle"],
                    event["slot"],
                    event["generation"],
                    event["event_type"],
                    event["agent_id"],
                    event["successor_agent_id"],
                    event["created_at"],
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

    return {
        "run_id": str(run_id),
        "seed": seed,
        "arm_label": arm.label,
        "policy": arm.policy.as_dict(),
        "lifecycle": arm.lifecycle.as_dict(),
        "environment": env.as_dict(),
        "metrics": metrics,
        "invariants": invariants,
    }


def corrected_lifecycle_utility(metrics: Mapping[str, float]) -> float:
    """Score lifecycle arms without rewarding forced UUID replacement."""
    return (
        metrics["success_rate"]
        + 0.04 * metrics.get("late_public_knowledge_coverage", metrics["public_knowledge_coverage"])
        - 0.12 * metrics["early_incumbent_share"]
        - 0.06 * metrics["mean_winner_hhi"]
        - 0.03 * metrics.get("late_cultural_lineage_hhi", metrics["cultural_lineage_hhi"])
        - 0.03 * metrics["credit_gini"]
    )


def corrected_lifecycle_feasible(
    arm: Mapping[str, object],
    control: Mapping[str, object],
    *,
    config: lc.IntegrationCampaignConfig,
    knowledge_tolerance: float,
) -> bool:
    invariants = arm["invariants"]
    assert isinstance(invariants, Mapping)
    if not all(bool(value) for value in invariants.values()):
        return False
    metrics = arm["metrics"]
    baseline = control["metrics"]
    assert isinstance(metrics, Mapping) and isinstance(baseline, Mapping)
    knowledge_key = (
        "late_public_knowledge_coverage"
        if "late_public_knowledge_coverage" in metrics and "late_public_knowledge_coverage" in baseline
        else "public_knowledge_coverage"
    )
    return (
        float(metrics["success_rate"])
        >= float(baseline["success_rate"]) - config.success_tolerance
        and float(metrics["mean_winning_price_fraction"])
        <= float(baseline["mean_winning_price_fraction"]) + config.economic_tolerance
        and float(metrics["credit_gini"])
        <= float(baseline["credit_gini"]) + config.economic_tolerance
        and float(metrics[knowledge_key])
        >= float(baseline[knowledge_key]) - knowledge_tolerance
    )


def corrected_lifecycle_effects(
    arm: Mapping[str, object],
    control: Mapping[str, object],
) -> dict[str, float]:
    metrics = arm["metrics"]
    baseline = control["metrics"]
    assert isinstance(metrics, Mapping) and isinstance(baseline, Mapping)
    knowledge_key = (
        "late_public_knowledge_coverage"
        if "late_public_knowledge_coverage" in metrics and "late_public_knowledge_coverage" in baseline
        else "public_knowledge_coverage"
    )
    cultural_key = (
        "late_cultural_lineage_hhi"
        if "late_cultural_lineage_hhi" in metrics and "late_cultural_lineage_hhi" in baseline
        else "cultural_lineage_hhi"
    )
    return {
        "success_effect": float(metrics["success_rate"]) - float(baseline["success_rate"]),
        "identity_incumbent_reduction": (
            float(baseline["identity_early_incumbent_share"])
            - float(metrics["identity_early_incumbent_share"])
        ),
        "logical_incumbent_reduction": (
            float(baseline["early_incumbent_share"])
            - float(metrics["early_incumbent_share"])
        ),
        "hhi_reduction": float(baseline["mean_winner_hhi"]) - float(metrics["mean_winner_hhi"]),
        "knowledge_effect": float(metrics[knowledge_key]) - float(baseline[knowledge_key]),
        "cultural_hhi_reduction": float(baseline[cultural_key]) - float(metrics[cultural_key]),
    }


def _plasticity_valid(effects: Mapping[str, float], config: cp.LifecycleConfig) -> bool:
    return (
        effects["logical_incumbent_reduction"] >= config.minimum_incumbent_improvement
        or effects["hhi_reduction"] >= config.minimum_hhi_improvement
    )


def _single_exit_test_corrected(
    connection: Connection[Any],
    *,
    config: cp.LifecycleConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    spec: lc.LifecycleSpec,
    label: str,
    state_key: str,
    focus: str,
    question: str,
    next_focus: str,
    state: dict[str, object],
) -> dict[str, object]:
    arms = cp._run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=number,
        arms=[
            cp._arm(config, label="immortal_control", lifecycle=lc.LifecycleSpec()),
            cp._arm(config, label=label, lifecycle=spec),
        ],
    )
    evaluated, selected, control = lc.evaluate_lifecycle_arms(
        arms,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    candidate = next(arm for arm in evaluated if arm["label"] == label)
    effects = corrected_lifecycle_effects(candidate, control)
    validated = bool(candidate["feasible"]) and _plasticity_valid(effects, config)
    state[state_key] = {
        "lifecycle": spec.as_dict(),
        "effects": effects,
        "feasible": bool(candidate["feasible"]),
        "validated": validated,
        "utility": float(candidate["utility"]),
    }
    return cp._record_lifecycle(
        number=number,
        focus=focus,
        question=question,
        arms=evaluated,
        selected=candidate if validated else selected,
        observed_failure=None if validated else "no_material_logical_turnover_effect",
        next_focus=next_focus,
        extras=effects,
        validated=validated,
    )


def _bracket_lifetime_corrected(
    connection: Connection[Any],
    *,
    config: cp.LifecycleConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    specs = [lc.LifecycleSpec(mode="fixed", lifetime_cycles=value) for value in config.lifetime_candidates]
    arms = cp._run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=66,
        arms=[
            cp._arm(config, label="immortal_control", lifecycle=lc.LifecycleSpec()),
            *[
                cp._arm(config, label=f"fixed_lifetime_{spec.lifetime_cycles}", lifecycle=spec)
                for spec in specs
            ],
        ],
    )
    evaluated, selected, control = lc.evaluate_lifecycle_arms(
        arms,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    finite = [arm for arm in evaluated if arm["label"] != "immortal_control" and bool(arm["feasible"])]
    chosen = max(finite, key=lambda arm: float(arm["utility"])) if finite else selected
    effects = corrected_lifecycle_effects(chosen, control)
    exit_causal = bool(chosen["feasible"]) and _plasticity_valid(effects, config)
    lifecycle_raw = chosen.get("lifecycle")
    if not isinstance(lifecycle_raw, Mapping):
        lifecycle_raw = lc.LifecycleSpec().as_dict()
    state["selected_lifecycle"] = dict(lifecycle_raw)
    state["exit_causal"] = exit_causal
    return cp._record_lifecycle(
        number=66,
        focus="lifetime_response",
        question="Across finite lifetimes, does competitive exit materially reduce logical-slot capture without sacrificing quality or public knowledge?",
        arms=evaluated,
        selected=chosen,
        observed_failure=None if exit_causal else "no_material_turnover_effect",
        next_focus="death_vs_retirement",
        extras={**effects, "selected_lifecycle": dict(lifecycle_raw), "exit_causal": exit_causal},
        validated=exit_causal,
    )


def _death_vs_retirement_corrected(
    connection: Connection[Any],
    *,
    config: cp.LifecycleConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_lifecycle")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected lifecycle")
    selected = cp._lifecycle_from_mapping(raw)
    lifetime = selected.lifetime_cycles or config.fixed_lifetime_cycles
    passive_weight = config.advisor_weight / 4
    death = lc.LifecycleSpec(mode="death", lifetime_cycles=lifetime)
    retirement = lc.LifecycleSpec(
        mode="retirement",
        lifetime_cycles=lifetime,
        advisor_weight=passive_weight,
    )
    arms = cp._run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=67,
        arms=[
            cp._arm(config, label="immortal_control", lifecycle=lc.LifecycleSpec()),
            cp._arm(config, label="death", lifecycle=death),
            cp._arm(config, label="retirement", lifecycle=retirement),
        ],
    )
    evaluated, selected_arm, control = lc.evaluate_lifecycle_arms(
        arms,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    finite = [arm for arm in evaluated if arm["label"] in {"death", "retirement"} and bool(arm["feasible"])]
    chosen = max(finite, key=lambda arm: float(arm["utility"])) if finite else selected_arm
    lifecycle_raw = chosen.get("lifecycle")
    assert isinstance(lifecycle_raw, Mapping)
    state["exit_mechanism"] = dict(lifecycle_raw)
    death_arm = next(arm for arm in evaluated if arm["label"] == "death")
    retirement_arm = next(arm for arm in evaluated if arm["label"] == "retirement")
    death_metrics = death_arm["metrics"]
    retirement_metrics = retirement_arm["metrics"]
    assert isinstance(death_metrics, Mapping) and isinstance(retirement_metrics, Mapping)
    difference = float(death_metrics["success_rate"]) - float(retirement_metrics["success_rate"])
    effects = corrected_lifecycle_effects(chosen, control)
    return cp._record_lifecycle(
        number=67,
        focus="death_vs_retirement",
        question="Once actors exit competition, does preserving bounded read-only access to a retired identity matter beyond literal death?",
        arms=evaluated,
        selected=chosen,
        observed_failure=None,
        next_focus="retired_advisory_access",
        extras={
            **effects,
            "death_minus_retirement_success": difference,
            "retirement_consultation_weight": passive_weight,
            "selected_exit_mechanism": dict(lifecycle_raw),
        },
    )


def _advisor_test_corrected(
    connection: Connection[Any],
    *,
    config: cp.LifecycleConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("exit_mechanism")
    if not isinstance(raw, Mapping):
        raise ValueError("missing exit mechanism")
    base = cp._lifecycle_from_mapping(raw)
    lifetime = base.lifetime_cycles or config.fixed_lifetime_cycles
    passive_weight = config.advisor_weight / 4
    retirement = lc.LifecycleSpec(
        mode="retirement",
        lifetime_cycles=lifetime,
        advisor_weight=passive_weight,
    )
    advisor = lc.LifecycleSpec(
        mode="advisor",
        lifetime_cycles=lifetime,
        advisor_weight=config.advisor_weight,
    )
    arms = cp._run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=68,
        arms=[
            cp._arm(config, label="immortal_control", lifecycle=lc.LifecycleSpec()),
            cp._arm(config, label="retirement", lifecycle=retirement),
            cp._arm(config, label="retirement_with_advisor", lifecycle=advisor),
        ],
    )
    evaluated, selected, control = lc.evaluate_lifecycle_arms(
        arms,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    finite = [arm for arm in evaluated if arm["label"] != "immortal_control" and bool(arm["feasible"])]
    chosen = max(finite, key=lambda arm: float(arm["utility"])) if finite else selected
    lifecycle_raw = chosen.get("lifecycle")
    assert isinstance(lifecycle_raw, Mapping)
    state["exit_mechanism"] = dict(lifecycle_raw)
    effects = corrected_lifecycle_effects(chosen, control)
    return cp._record_lifecycle(
        number=68,
        focus="retired_advisory_access",
        question="Can stronger advisory access preserve tacit knowledge without restoring competitive privilege?",
        arms=evaluated,
        selected=chosen,
        observed_failure=None,
        next_focus="reputation_independence",
        extras={**effects, "selected_exit_mechanism": dict(lifecycle_raw)},
    )


def _reputation_independence_corrected(
    connection: Connection[Any],
    *,
    config: cp.LifecycleConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("exit_mechanism")
    if not isinstance(raw, Mapping):
        raise ValueError("missing exit mechanism")
    lifecycle = cp._lifecycle_from_mapping(raw)
    no_rep = ReputationPolicy()
    arms = cp._run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=69,
        arms=[
            cp._arm(config, label="immortal_no_reputation", lifecycle=lc.LifecycleSpec(), policy=no_rep),
            cp._arm(config, label="lifecycle_no_reputation", lifecycle=lifecycle, policy=no_rep),
        ],
    )
    control = next(arm for arm in arms if arm["label"] == "immortal_no_reputation")
    candidate = next(arm for arm in arms if arm["label"] == "lifecycle_no_reputation")
    control_metrics = control["metrics"]
    candidate_metrics = candidate["metrics"]
    assert isinstance(control_metrics, Mapping) and isinstance(candidate_metrics, Mapping)
    control_item = dict(control)
    candidate_item = dict(candidate)
    control_item["feasible"] = True
    control_item["utility"] = corrected_lifecycle_utility(control_metrics)  # type: ignore[arg-type]
    candidate_item["feasible"] = corrected_lifecycle_feasible(
        candidate,
        control,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    candidate_item["utility"] = corrected_lifecycle_utility(candidate_metrics)  # type: ignore[arg-type]
    effects = corrected_lifecycle_effects(candidate_item, control_item)
    independent = bool(candidate_item["feasible"]) and _plasticity_valid(effects, config)
    state["reputation_independent"] = independent
    selected = candidate_item if independent else control_item
    return cp._record_lifecycle(
        number=69,
        focus="reputation_independence",
        question="Does competitive exit still reduce logical capture when reputation is removed entirely?",
        arms=[control_item, candidate_item],
        selected=selected,
        observed_failure=None if independent else "reputation_dependency",
        next_focus="rapid_regime_shift",
        extras={**effects, "reputation_independent": independent},
        validated=independent,
    )


def _rapid_shift_corrected(
    connection: Connection[Any],
    *,
    config: cp.LifecycleConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("exit_mechanism")
    if not isinstance(raw, Mapping):
        raise ValueError("missing exit mechanism")
    lifecycle = cp._lifecycle_from_mapping(raw)
    env = cp.high_practice_environment(config, shift_period=config.rapid_shift_period)
    arms = cp._run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=70,
        arms=[
            cp._arm(config, label="immortal_control", lifecycle=lc.LifecycleSpec(), env=env),
            cp._arm(config, label="lifecycle_candidate", lifecycle=lifecycle, env=env),
        ],
    )
    evaluated, _, control = lc.evaluate_lifecycle_arms(
        arms,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    candidate = next(arm for arm in evaluated if arm["label"] == "lifecycle_candidate")
    effects = corrected_lifecycle_effects(candidate, control)
    validated = (
        bool(candidate["feasible"])
        and effects["success_effect"] >= -config.integration.success_tolerance
        and _plasticity_valid(effects, config)
    )
    state["rapid_shift_validated"] = validated
    return cp._record_lifecycle(
        number=70,
        focus="rapid_regime_shift",
        question="Does the selected lifecycle preserve quality and logical plasticity when skill mappings change rapidly?",
        arms=evaluated,
        selected=candidate if validated else control,
        observed_failure=None if validated else "rapid_shift",
        next_focus="cultural_persistence",
        extras={**effects, "rapid_shift_validated": validated},
        validated=validated,
    )


def _synthesis_corrected(
    connection: Connection[Any],
    *,
    config: cp.LifecycleConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("candidate_lifecycle") or state.get("exit_mechanism")
    if not isinstance(raw, Mapping):
        raise ValueError("missing candidate lifecycle")
    lifecycle = cp._lifecycle_from_mapping(raw)
    env = cp.high_practice_environment(config, cycles=config.synthesis_cycles)
    arms = cp._run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=72,
        arms=[
            cp._arm(config, label="immortal_control", lifecycle=lc.LifecycleSpec(), env=env),
            cp._arm(config, label="candidate_lifecycle", lifecycle=lifecycle, env=env),
        ],
    )
    evaluated, _, control = lc.evaluate_lifecycle_arms(
        arms,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_lifecycle")
    effects = corrected_lifecycle_effects(candidate, control)
    validated = (
        bool(state["exit_causal"])
        and bool(candidate["feasible"])
        and effects["success_effect"] >= -config.integration.success_tolerance
        and _plasticity_valid(effects, config)
    )
    state["candidate_lifecycle"] = lifecycle.as_dict()
    state["synthesis_validated"] = validated
    return cp._record_lifecycle(
        number=72,
        focus="fast_learning_synthesis",
        question="Can fast learning retain quality once competitive privilege has a finite lifetime?",
        arms=evaluated,
        selected=candidate if validated else control,
        observed_failure=None if validated else "quality_or_plasticity",
        next_focus="independent_replication",
        extras={**effects, "synthesis_validated": validated},
        validated=validated,
    )


def _replication_corrected(
    connection: Connection[Any],
    *,
    config: cp.LifecycleConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("candidate_lifecycle")
    if not isinstance(raw, Mapping):
        raise ValueError("missing candidate lifecycle")
    lifecycle = cp._lifecycle_from_mapping(raw)
    env = cp.high_practice_environment(config, cycles=config.synthesis_cycles)
    arms = cp._run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=73,
        seeds=config.replication_seeds,
        arms=[
            cp._arm(config, label="immortal_control", lifecycle=lc.LifecycleSpec(), env=env),
            cp._arm(config, label="candidate_lifecycle", lifecycle=lifecycle, env=env),
        ],
    )
    evaluated, _, control = lc.evaluate_lifecycle_arms(
        arms,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_lifecycle")
    effects = corrected_lifecycle_effects(candidate, control)
    invariants = candidate["invariants"]
    assert isinstance(invariants, Mapping)
    validated = (
        bool(state["synthesis_validated"])
        and bool(candidate["feasible"])
        and effects["success_effect"] >= -config.integration.success_tolerance
        and _plasticity_valid(effects, config)
        and all(bool(value) for value in invariants.values())
    )
    state["replication_validated"] = validated
    return cp._record_lifecycle(
        number=73,
        focus="independent_replication",
        question="Does the selected lifecycle reproduce both quality and logical plasticity on independent seeds?",
        arms=evaluated,
        selected=candidate if validated else control,
        observed_failure=None if validated else "replication",
        next_focus="unseen_holdout",
        extras={**effects, "replication_validated": validated},
        validated=validated,
    )


def _holdout_corrected(
    connection: Connection[Any],
    *,
    config: cp.LifecycleConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("candidate_lifecycle")
    if not isinstance(raw, Mapping):
        raise ValueError("missing candidate lifecycle")
    candidate_spec = cp._lifecycle_from_mapping(raw)
    if candidate_spec.finite:
        candidate_spec = replace(
            candidate_spec,
            lifetime_cycles=config.holdout_lifetime_cycles,
            schedule_offset=7,
        )
    base = config.integration.environment
    env = replace(
        base,
        practice_gain=config.reference_practice_gain,
        cycles=config.integration.holdout_cycles,
        shift_period=config.holdout_shift_period,
        candidate_count=config.integration.holdout_candidate_count,
    )
    arms = cp._run_arms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=74,
        seeds=config.integration.holdout_seeds,
        arms=[
            cp._arm(config, label="immortal_control", lifecycle=lc.LifecycleSpec(), env=env),
            cp._arm(config, label="candidate_lifecycle", lifecycle=candidate_spec, env=env),
        ],
    )
    evaluated, _, control = lc.evaluate_lifecycle_arms(
        arms,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    lifecycle_arm = next(arm for arm in evaluated if arm["label"] == "candidate_lifecycle")
    effects = corrected_lifecycle_effects(lifecycle_arm, control)
    invariants = lifecycle_arm["invariants"]
    assert isinstance(invariants, Mapping)
    validated = (
        bool(state["exit_causal"])
        and bool(state["reputation_independent"])
        and bool(state["rapid_shift_validated"])
        and bool(state["synthesis_validated"])
        and bool(state["replication_validated"])
        and bool(lifecycle_arm["feasible"])
        and effects["success_effect"] >= -config.integration.success_tolerance
        and _plasticity_valid(effects, config)
        and all(bool(value) for value in invariants.values())
    )
    state["validated"] = validated
    return cp._record_lifecycle(
        number=74,
        focus="unseen_holdout",
        question="Does succession generalize to unseen seeds, a new task-remap schedule, and unseen lifecycle timing?",
        arms=evaluated,
        selected=lifecycle_arm,
        observed_failure=None if validated else "holdout",
        next_focus=None,
        extras={
            **effects,
            "holdout_lifecycle": candidate_spec.as_dict(),
            "exit_causal": bool(state["exit_causal"]),
            "reputation_independent": bool(state["reputation_independent"]),
            "rapid_shift_validated": bool(state["rapid_shift_validated"]),
            "synthesis_validated": bool(state["synthesis_validated"]),
            "replication_validated": bool(state["replication_validated"]),
        },
        validated=validated,
    )


def install_lifecycle_corrections() -> None:
    """Install corrected campaign functions into the existing checkpoint state machine."""
    lc.should_exit = corrected_should_exit
    lc.run_lifecycle_arm = corrected_run_lifecycle_arm
    lc.lifecycle_utility = corrected_lifecycle_utility
    lc.lifecycle_feasible = corrected_lifecycle_feasible
    lc.lifecycle_effects = corrected_lifecycle_effects

    cp.lifecycle_utility = corrected_lifecycle_utility
    cp.lifecycle_feasible = corrected_lifecycle_feasible
    cp.lifecycle_effects = corrected_lifecycle_effects
    cp._single_exit_test = _single_exit_test_corrected
    cp._bracket_lifetime = _bracket_lifetime_corrected
    cp._death_vs_retirement = _death_vs_retirement_corrected
    cp._advisor_test = _advisor_test_corrected
    cp._reputation_independence = _reputation_independence_corrected
    cp._rapid_shift = _rapid_shift_corrected
    cp._synthesis = _synthesis_corrected
    cp._replication = _replication_corrected
    cp._holdout = _holdout_corrected
