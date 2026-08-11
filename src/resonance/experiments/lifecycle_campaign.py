"""Real-market lifecycle and succession machinery for Experiments 063–074."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from resonance.economy import PostgresEconomyRepository
from resonance.economy.postgres import TREASURY_ACCOUNT_ID
from resonance.market import PostgresMarketService
from resonance.reputation import PostgresReputationRepository
from resonance.substrate.models import Trace
from resonance.substrate.postgres import PostgresTraceRepository

from .adaptive_campaign import _summarize_rows
from .integration_campaign import (
    IntegrationCampaignConfig,
    IntegrationEnvironment,
    PostgresReputationBidSignalProvider,
    ReputationPolicy,
    _candidate_slots,
    _domain_index,
    _draw,
    _gini,
    _requester_slot,
    _run_invariants,
    _trace_signal,
)

_DOMAIN_DIMENSION = "task_domain_success"
_SKILL_DIMENSION = "skill_success"
_BASE_TIME = datetime(2026, 8, 11, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class LifecycleSpec:
    mode: str = "immortal"
    lifetime_cycles: int | None = None
    stochastic_min_age: int = 0
    advisor_weight: float = 0.0
    diversified_retrieval: bool = False
    schedule_offset: int = 0

    def __post_init__(self) -> None:
        allowed = {"immortal", "fixed", "stochastic", "retirement", "death", "advisor"}
        if self.mode not in allowed:
            raise ValueError(f"unsupported lifecycle mode: {self.mode}")
        if self.mode != "immortal":
            if self.lifetime_cycles is None or self.lifetime_cycles <= 2:
                raise ValueError("finite lifecycle requires lifetime_cycles > 2")
        if self.stochastic_min_age < 0:
            raise ValueError("stochastic_min_age must be non-negative")
        if not 0 <= self.advisor_weight <= 0.5:
            raise ValueError("advisor_weight must be in [0, 0.5]")

    @property
    def finite(self) -> bool:
        return self.mode != "immortal"

    @property
    def label(self) -> str:
        if self.mode == "immortal":
            base = "immortal"
        else:
            base = f"{self.mode}-life{self.lifetime_cycles}"
        if self.diversified_retrieval:
            base += "-diverse"
        if self.mode == "advisor":
            base += f"-adv{self.advisor_weight:g}"
        if self.schedule_offset:
            base += f"-off{self.schedule_offset}"
        return base

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LifecycleArmSpec:
    label: str
    policy: ReputationPolicy
    environment: IntegrationEnvironment
    lifecycle: LifecycleSpec
    public_trace_confidence_weight: float
    retrieval_top_k: int
    diversified_lineages: int
    knowledge_signal_threshold: float


def should_exit(
    spec: LifecycleSpec,
    *,
    seed: int,
    cycle: int,
    slot: int,
    born_cycle: int,
) -> bool:
    """Return whether a currently active identity exits before this cycle's task."""
    if not spec.finite:
        return False
    assert spec.lifetime_cycles is not None
    age = cycle - born_cycle
    if age <= 0:
        return False
    if spec.mode == "stochastic":
        if age < spec.stochastic_min_age:
            return False
        hazard = min(1.0, 1.0 / spec.lifetime_cycles)
        return _draw(seed, cycle + spec.schedule_offset, slot, "lifecycle-exit") < hazard
    return age >= spec.lifetime_cycles


def _trace_rows(
    connection: Connection[Any],
    *,
    skill: str,
    at: datetime,
    limit: int,
) -> list[dict[str, object]]:
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
        ORDER BY energy DESC, trace_id
        LIMIT %s
        """,
        (at, f"skill-evidence:{skill}", limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _public_trace_stats(
    connection: Connection[Any],
    *,
    skill: str,
    at: datetime,
    author_lineage: Mapping[UUID, int],
    retired_agents: set[UUID],
    top_k: int,
    diversified: bool,
    diversified_lineages: int,
) -> dict[str, float]:
    rows = _trace_rows(connection, skill=skill, at=at, limit=max(top_k * 4, top_k))
    if not rows:
        return {
            "signal": 0.0,
            "lineage_hhi": 0.0,
            "retired_share": 0.0,
            "lineage_count": 0.0,
        }

    top = rows[:top_k]
    counts = Counter(author_lineage.get(row["author_agent_id"], -1) for row in top)
    total = sum(counts.values())
    hhi = sum((count / total) ** 2 for count in counts.values()) if total else 0.0
    retired_share = (
        sum(row["author_agent_id"] in retired_agents for row in top) / len(top)
        if top
        else 0.0
    )

    if diversified:
        maxima: dict[int, float] = {}
        for row in rows:
            lineage = author_lineage.get(row["author_agent_id"], -1)
            maxima[lineage] = max(maxima.get(lineage, 0.0), float(row["energy"]))
        selected = sorted(maxima.values(), reverse=True)[:diversified_lineages]
        signal = statistics.mean(selected) if selected else 0.0
    else:
        signal = max(float(row["energy"]) for row in rows)

    return {
        "signal": max(0.0, min(1.0, signal)),
        "lineage_hhi": hhi,
        "retired_share": retired_share,
        "lineage_count": float(len(counts)),
    }


def _advisor_signal(
    connection: Connection[Any],
    *,
    advisors: Sequence[UUID],
    skill: str,
    at: datetime,
) -> float:
    if not advisors:
        return 0.0
    return max(
        (_trace_signal(connection, agent_id=agent_id, skill=skill, at=at) for agent_id in advisors),
        default=0.0,
    )


def _identity_incumbent_metrics(
    rows: Sequence[Mapping[str, object]],
    *,
    domain_count: int,
    shift_period: int,
) -> tuple[float, float]:
    """Measure incumbent persistence using concrete identity UUIDs, not logical slots."""
    shares: list[float] = []
    replacements: list[float] = []
    window = min(20, shift_period)
    for shift in range(shift_period, len(rows), shift_period):
        pre = rows[max(0, shift - shift_period):shift]
        early = rows[shift:min(len(rows), shift + window)]
        post = rows[shift:min(len(rows), shift + shift_period)]
        if not pre or not early or not post:
            continue
        old: dict[int, str] = {}
        new: dict[int, str] = {}
        for domain in range(domain_count):
            pre_counts = Counter(
                str(row["winner_agent_id"]) for row in pre if int(row["domain"]) == domain
            )
            post_counts = Counter(
                str(row["winner_agent_id"]) for row in post if int(row["domain"]) == domain
            )
            if pre_counts:
                high = max(pre_counts.values())
                old[domain] = min(key for key, value in pre_counts.items() if value == high)
            if post_counts:
                high = max(post_counts.values())
                new[domain] = min(key for key, value in post_counts.items() if value == high)
        shares.append(
            sum(
                old.get(int(row["domain"])) == str(row["winner_agent_id"])
                for row in early
            ) / len(early)
        )
        comparable = [domain for domain in old if domain in new]
        replacements.append(
            sum(old[domain] != new[domain] for domain in comparable) / len(comparable)
            if comparable
            else 0.0
        )
    return (
        statistics.mean(shares) if shares else 0.0,
        statistics.mean(replacements) if replacements else 0.0,
    )


def _reclaim_and_replace(
    connection: Connection[Any],
    *,
    economy: PostgresEconomyRepository,
    run_id: UUID,
    active_ids: list[UUID],
    generations: list[int],
    born_cycle: list[int],
    slot: int,
    cycle: int,
    at: datetime,
    initial_credits: int,
    mode: str,
    advisors: list[UUID],
    retired_agents: set[UUID],
    all_agent_ids: list[UUID],
    author_lineage: dict[UUID, int],
    lifecycle_events: list[dict[str, object]],
) -> tuple[UUID, UUID]:
    old_id = active_ids[slot]
    balance = economy.balance(old_id)
    if balance > 0:
        account = economy.account_for_agent(old_id)
        economy.transfer(
            account.account_id,
            TREASURY_ACCOUNT_ID,
            balance,
            at=at,
            reason="lifecycle exit reclaim",
            reference_type="agent",
            reference_id=old_id,
        )
    retired_agents.add(old_id)
    if mode == "advisor":
        advisors.append(old_id)
    generations[slot] += 1
    generation = generations[slot]
    new_id = uuid5(run_id, f"agent:{slot}:generation:{generation}")
    economy.register_agent(
        new_id,
        at=at,
        generation=generation,
        initial_credits=initial_credits,
    )
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
    return old_id, new_id


def run_lifecycle_arm(
    connection: Connection[Any],
    *,
    config: IntegrationCampaignConfig,
    config_hash: str,
    experiment_number: int,
    arm: LifecycleArmSpec,
    seed: int,
    code_sha: str,
) -> dict[str, object]:
    """Run one lifecycle arm through the production sealed-bid market."""
    if not connection.autocommit:
        raise ValueError("lifecycle campaign requires autocommit")
    connection.row_factory = dict_row
    env = arm.environment
    run_id = uuid5(
        NAMESPACE_URL,
        f"lifecycle:{code_sha}:{config_hash}:{experiment_number}:{arm.label}:{seed}",
    )
    start = _BASE_TIME + timedelta(days=experiment_number, hours=seed % 17)
    economy = PostgresEconomyRepository(connection)
    reputation = PostgresReputationRepository(connection)
    traces = PostgresTraceRepository(connection)

    active_ids: list[UUID] = []
    all_agent_ids: list[UUID] = []
    generations = [0 for _ in range(env.agents)]
    born_cycle = [0 for _ in range(env.agents)]
    author_lineage: dict[UUID, int] = {}
    retired_agents: set[UUID] = set()
    advisors: list[UUID] = []
    practice: dict[tuple[UUID, str], int] = {}

    for slot in range(env.agents):
        agent_id = uuid5(run_id, f"agent:{slot}:generation:0")
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
    knowledge_coverage: list[float] = []
    cultural_hhis: list[float] = []
    retired_trace_shares: list[float] = []
    active_ages: list[float] = []
    lifecycle_events: list[dict[str, object]] = []

    for cycle in range(env.cycles):
        task_at = start + timedelta(seconds=cycle * env.cycle_seconds)

        for slot in range(env.agents):
            if should_exit(
                arm.lifecycle,
                seed=seed,
                cycle=cycle,
                slot=slot,
                born_cycle=born_cycle[slot],
            ):
                _reclaim_and_replace(
                    connection,
                    economy=economy,
                    run_id=run_id,
                    active_ids=active_ids,
                    generations=generations,
                    born_cycle=born_cycle,
                    slot=slot,
                    cycle=cycle,
                    at=task_at,
                    initial_credits=env.initial_credits,
                    mode=arm.lifecycle.mode,
                    advisors=advisors,
                    retired_agents=retired_agents,
                    all_agent_ids=all_agent_ids,
                    author_lineage=author_lineage,
                    lifecycle_events=lifecycle_events,
                )
                exit_count += 1

        active_ages.extend(float(cycle - born_cycle[slot]) for slot in range(env.agents))
        regime = cycle // env.shift_period
        regime_start_cycle = regime * env.shift_period
        regime_start_at = start + timedelta(seconds=regime_start_cycle * env.cycle_seconds)
        domain_index = _domain_index(seed, cycle, len(env.domains))
        task_domain = env.domains[domain_index]
        required_index = (domain_index + regime) % len(env.domains)
        required_skill = env.domains[required_index]

        public = _public_trace_stats(
            connection,
            skill=required_skill,
            at=task_at,
            author_lineage=author_lineage,
            retired_agents=retired_agents,
            top_k=arm.retrieval_top_k,
            diversified=arm.lifecycle.diversified_retrieval,
            diversified_lineages=arm.diversified_lineages,
        )
        public_signals.append(public["signal"])
        cultural_hhis.append(public["lineage_hhi"])
        retired_trace_shares.append(public["retired_share"])
        if retired_agents:
            knowledge_coverage.append(float(public["signal"] >= arm.knowledge_signal_threshold))

        provider = None
        if arm.policy.mode == "reputation":
            provider = PostgresReputationBidSignalProvider(
                connection,
                policy=arm.policy,
                population=active_ids,
                cycle_seconds=env.cycle_seconds,
            )
        market = PostgresMarketService(connection, economy, bid_signal_provider=provider)

        requester_slot = _requester_slot(env, seed, cycle)
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

        candidates = _candidate_slots(
            seed,
            cycle,
            agents=env.agents,
            requester_slot=requester_slot,
            count=env.candidate_count,
        )
        for candidate_slot in candidates:
            candidate_id = active_ids[candidate_slot]
            own_signal = _trace_signal(
                connection,
                agent_id=candidate_id,
                skill=required_skill,
                at=task_at,
            )
            advisor_signal = (
                _advisor_signal(
                    connection,
                    advisors=advisors,
                    skill=required_skill,
                    at=task_at,
                )
                if arm.lifecycle.mode == "advisor"
                else 0.0
            )
            confidence = (
                env.confidence_base
                + env.confidence_evidence_weight * own_signal
                + arm.public_trace_confidence_weight * public["signal"]
                + arm.lifecycle.advisor_weight * advisor_signal
                + env.confidence_noise_weight * _draw(seed, cycle, candidate_slot, "confidence")
            )
            if own_signal < 0.20:
                confidence += env.confidence_inflation
            confidence = max(0.05, min(0.98, confidence))
            price_fraction = env.price_floor + env.price_span * _draw(
                seed, cycle, candidate_slot, "price"
            )
            price = max(
                1,
                min(env.task_budget, int(env.task_budget * min(0.95, price_fraction))),
            )
            completion = env.completion_min_seconds + int(
                env.completion_span_seconds * _draw(seed, cycle, candidate_slot, "speed")
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
        success = _draw(seed, cycle, winner_slot, "outcome") < success_probability
        noise_flip = _draw(seed, cycle, winner_slot, "evidence-noise") < env.evidence_noise
        recorded_positive = not success if noise_flip else success
        outcome_at = task.deadline + timedelta(seconds=1)

        market.settle(task.task_id, at=outcome_at)
        reputation.record_evidence(
            winner_id,
            dimension=_DOMAIN_DIMENSION,
            context_key=task_domain,
            positive=recorded_positive,
            source_type="integration_domain",
            source_id=task.task_id,
            at=outcome_at,
        )
        reputation.record_evidence(
            winner_id,
            dimension=_SKILL_DIMENSION,
            context_key=required_skill,
            positive=recorded_positive,
            source_type="integration_skill",
            source_id=task.task_id,
            at=outcome_at,
        )
        if cycle == 0:
            reputation.record_evidence(
                winner_id,
                dimension=_DOMAIN_DIMENSION,
                context_key=task_domain,
                positive=recorded_positive,
                source_type="integration_domain",
                source_id=task.task_id,
                at=outcome_at,
            )

        if success:
            traces.add(
                Trace(
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
    structural = _summarize_rows(
        rows,
        domain_count=len(env.domains),
        shift_period=env.shift_period,
    )
    identity_incumbent, identity_replacement = _identity_incumbent_metrics(
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
    metrics: dict[str, float] = {
        **structural,
        "identity_early_incumbent_share": identity_incumbent,
        "identity_replacement_rate": identity_replacement,
        "reputation_brier_score": brier,
        "mean_winning_price_fraction": price_fraction,
        "credit_gini": _gini(active_balances),
        "exit_count": float(exit_count),
        "turnover_rate": exit_count / max(1, env.cycles * env.agents),
        "mean_active_age": statistics.mean(active_ages) if active_ages else 0.0,
        "public_knowledge_coverage": (
            statistics.mean(knowledge_coverage)
            if knowledge_coverage
            else statistics.mean(
                float(signal >= arm.knowledge_signal_threshold) for signal in public_signals
            )
        ),
        "mean_public_trace_signal": statistics.mean(public_signals) if public_signals else 0.0,
        "cultural_lineage_hhi": statistics.mean(cultural_hhis) if cultural_hhis else 0.0,
        "retired_trace_retrieval_share": (
            statistics.mean(retired_trace_shares) if retired_trace_shares else 0.0
        ),
        "max_generation": float(max(generations)),
    }
    invariants = _run_invariants(
        connection,
        task_ids=task_ids,
        agent_ids=all_agent_ids,
        first_bid_id=first_bid_id,
        first_score_id=first_score_id,
        expected_evidence=2 * env.cycles,
    )

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


def _mean_mapping(rows: Sequence[Mapping[str, float]]) -> dict[str, float]:
    keys = rows[0].keys()
    return {key: statistics.mean(float(row[key]) for row in rows) for key in keys}


def aggregate_lifecycle_arm(cells: Sequence[Mapping[str, object]]) -> dict[str, object]:
    metric_rows = [cell["metrics"] for cell in cells]
    assert all(isinstance(row, Mapping) for row in metric_rows)
    metrics = _mean_mapping(metric_rows)  # type: ignore[arg-type]
    invariant_keys = cells[0]["invariants"].keys()  # type: ignore[union-attr]
    invariants = {
        key: all(bool(cell["invariants"][key]) for cell in cells)  # type: ignore[index]
        for key in invariant_keys
    }
    first = cells[0]
    return {
        "label": first["arm_label"],
        "policy": first["policy"],
        "lifecycle": first["lifecycle"],
        "environment": first["environment"],
        "metrics": metrics,
        "invariants": invariants,
        "run_ids": [cell["run_id"] for cell in cells],
    }


def run_lifecycle_experiment(
    connection: Connection[Any],
    *,
    config: IntegrationCampaignConfig,
    config_hash: str,
    experiment_number: int,
    arms: Sequence[LifecycleArmSpec],
    seeds: Sequence[int],
    code_sha: str,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for arm in arms:
        cells = [
            run_lifecycle_arm(
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
        results.append(aggregate_lifecycle_arm(cells))
    return results


def lifecycle_utility(metrics: Mapping[str, float]) -> float:
    return (
        metrics["success_rate"]
        + 0.06 * metrics["identity_replacement_rate"]
        + 0.04 * metrics["public_knowledge_coverage"]
        - 0.10 * metrics["identity_early_incumbent_share"]
        - 0.06 * metrics["mean_winner_hhi"]
        - 0.03 * metrics["cultural_lineage_hhi"]
        - 0.03 * metrics["credit_gini"]
    )


def lifecycle_feasible(
    arm: Mapping[str, object],
    control: Mapping[str, object],
    *,
    config: IntegrationCampaignConfig,
    knowledge_tolerance: float,
) -> bool:
    invariants = arm["invariants"]
    assert isinstance(invariants, Mapping)
    if not all(bool(value) for value in invariants.values()):
        return False
    metrics = arm["metrics"]
    baseline = control["metrics"]
    assert isinstance(metrics, Mapping) and isinstance(baseline, Mapping)
    return (
        float(metrics["success_rate"])
        >= float(baseline["success_rate"]) - config.success_tolerance
        and float(metrics["mean_winning_price_fraction"])
        <= float(baseline["mean_winning_price_fraction"]) + config.economic_tolerance
        and float(metrics["credit_gini"])
        <= float(baseline["credit_gini"]) + config.economic_tolerance
        and float(metrics["public_knowledge_coverage"])
        >= float(baseline["public_knowledge_coverage"]) - knowledge_tolerance
    )


def evaluate_lifecycle_arms(
    arms: Sequence[dict[str, object]],
    *,
    config: IntegrationCampaignConfig,
    knowledge_tolerance: float,
    control_label: str = "immortal_control",
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    control = next(arm for arm in arms if arm["label"] == control_label)
    evaluated: list[dict[str, object]] = []
    for arm in arms:
        metrics = arm["metrics"]
        assert isinstance(metrics, Mapping)
        item = dict(arm)
        item["feasible"] = lifecycle_feasible(
            arm,
            control,
            config=config,
            knowledge_tolerance=knowledge_tolerance,
        )
        item["utility"] = lifecycle_utility(metrics)
        evaluated.append(item)
    candidates = [
        arm for arm in evaluated
        if arm["label"] != control_label and bool(arm["feasible"])
    ]
    pool = candidates or [arm for arm in evaluated if bool(arm["feasible"])]
    if not pool:
        pool = evaluated
    selected = max(pool, key=lambda item: (float(item["utility"]), str(item["label"])))
    return evaluated, selected, control


def lifecycle_effects(
    arm: Mapping[str, object],
    control: Mapping[str, object],
) -> dict[str, float]:
    metrics = arm["metrics"]
    baseline = control["metrics"]
    assert isinstance(metrics, Mapping) and isinstance(baseline, Mapping)
    return {
        "success_effect": float(metrics["success_rate"]) - float(baseline["success_rate"]),
        "identity_incumbent_reduction": (
            float(baseline["identity_early_incumbent_share"])
            - float(metrics["identity_early_incumbent_share"])
        ),
        "hhi_reduction": float(baseline["mean_winner_hhi"]) - float(metrics["mean_winner_hhi"]),
        "knowledge_effect": (
            float(metrics["public_knowledge_coverage"])
            - float(baseline["public_knowledge_coverage"])
        ),
    }
