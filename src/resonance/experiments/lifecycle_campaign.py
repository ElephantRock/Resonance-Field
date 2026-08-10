"""Lifecycle and succession experiment engine for Experiments 063 through 074."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from resonance.economy import PostgresEconomyRepository
from resonance.market import PostgresMarketService
from resonance.reputation import PostgresReputationRepository
from resonance.substrate.models import Trace
from resonance.substrate.postgres import PostgresTraceRepository

from .adaptive_campaign import _summarize_rows
from .integration_campaign import (
    IntegrationEnvironment,
    PostgresReputationBidSignalProvider,
    ReputationPolicy,
    _BASE_TIME,
    _DOMAIN_DIMENSION,
    _SKILL_DIMENSION,
    _candidate_slots,
    _domain_index,
    _draw,
    _gini,
    _requester_slot,
    _run_invariants,
    _trace_signal,
)
from .phase_boundary_campaign import reference_policy


@dataclass(frozen=True, slots=True)
class LifecyclePolicy:
    """Exogenous competitive-lifecycle intervention.

    `disposition` controls what happens to the old executable identity after
    competitive exit. Public traces always remain in the substrate.
    """

    mode: str = "immortal"
    lifetime_cycles: int | None = None
    disposition: str = "active"
    advisory: bool = False
    public_retrieval: str = "standard"
    phase_offset: int = 0

    def __post_init__(self) -> None:
        if self.mode not in {"immortal", "fixed", "stochastic"}:
            raise ValueError("lifecycle mode must be immortal, fixed, or stochastic")
        if self.mode != "immortal" and (self.lifetime_cycles is None or self.lifetime_cycles <= 1):
            raise ValueError("finite lifecycle requires lifetime_cycles > 1")
        if self.disposition not in {"active", "retire", "death", "advisor"}:
            raise ValueError("invalid lifecycle disposition")
        if self.mode == "immortal" and self.disposition != "active":
            raise ValueError("immortal lifecycle must keep actors active")
        if self.advisory and self.disposition != "advisor":
            raise ValueError("advisory access requires advisor disposition")
        if self.public_retrieval not in {"standard", "diversified"}:
            raise ValueError("public_retrieval must be standard or diversified")

    @property
    def label(self) -> str:
        if self.mode == "immortal":
            return "immortal"
        return (
            f"{self.mode}-L{self.lifetime_cycles}-{self.disposition}"
            f"-{'advisor' if self.advisory else 'silent'}"
            f"-{self.public_retrieval}-o{self.phase_offset}"
        )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SuccessionArm:
    label: str
    policy: ReputationPolicy
    environment: IntegrationEnvironment
    lifecycle: LifecyclePolicy


def _energy_rows(
    connection: Connection[Any],
    *,
    skill: str,
    at: datetime,
    limit: int = 160,
) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT
            author_agent_id,
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
        ORDER BY energy DESC, created_at DESC, trace_id
        LIMIT %s
        """,
        (at, f"skill-evidence:{skill}", limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _public_knowledge(
    connection: Connection[Any],
    *,
    skill: str,
    at: datetime,
    lineage_by_agent: Mapping[UUID, int],
    current_agent_id: UUID,
    current_lineage: int,
    retrieval_k: int,
    retrieval_mode: str,
    diversity_per_lineage: int,
) -> tuple[float, float, float]:
    rows = _energy_rows(connection, skill=skill, at=at)
    if not rows:
        return 0.0, 0.0, 0.0

    selected: list[dict[str, object]] = []
    if retrieval_mode == "standard":
        selected = rows[:retrieval_k]
    else:
        per_lineage: Counter[int] = Counter()
        for row in rows:
            author = row["author_agent_id"]
            lineage = lineage_by_agent.get(author)
            if lineage is None or per_lineage[lineage] >= diversity_per_lineage:
                continue
            selected.append(row)
            per_lineage[lineage] += 1
            if len(selected) >= retrieval_k:
                break
        if len(selected) < retrieval_k:
            used = {id(row) for row in selected}
            for row in rows:
                if id(row) in used:
                    continue
                selected.append(row)
                if len(selected) >= retrieval_k:
                    break

    energies = [float(row["energy"]) for row in selected]
    signal = statistics.mean(energies) if energies else 0.0
    lineages = [lineage_by_agent.get(row["author_agent_id"], -1) for row in selected]
    counts = Counter(lineages)
    total = len(lineages)
    hhi = sum((count / total) ** 2 for count in counts.values()) if total else 0.0
    predecessor = sum(
        1
        for row in selected
        if lineage_by_agent.get(row["author_agent_id"]) == current_lineage
        and row["author_agent_id"] != current_agent_id
    )
    predecessor_share = predecessor / total if total else 0.0
    return signal, hhi, predecessor_share


def _actor_incumbency(rows: Sequence[Mapping[str, object]], shift_period: int, window: int = 18) -> float:
    pre = [
        row
        for row in rows
        if max(0, shift_period - window) <= int(row["cycle"]) < shift_period
    ]
    post = [
        row
        for row in rows
        if shift_period <= int(row["cycle"]) < min(shift_period + window, len(rows))
    ]
    if not pre or not post:
        return 0.0
    by_domain: dict[str, Counter[UUID]] = {}
    for row in pre:
        counts = by_domain.setdefault(str(row["task_domain"]), Counter())
        counts[row["winner_agent_id"]] += 1  # type: ignore[index]
    incumbents = {
        domain: counts.most_common(1)[0][0]
        for domain, counts in by_domain.items()
        if counts
    }
    eligible = [row for row in post if str(row["task_domain"]) in incumbents]
    if not eligible:
        return 0.0
    matches = sum(
        row["winner_agent_id"] == incumbents[str(row["task_domain"])]
        for row in eligible
    )
    return matches / len(eligible)


def _replacement_due(
    lifecycle: LifecyclePolicy,
    *,
    seed: int,
    cycle: int,
    slot: int,
    birth_cycle: int,
) -> bool:
    if lifecycle.mode == "immortal":
        return False
    assert lifecycle.lifetime_cycles is not None
    age = cycle - birth_cycle
    if lifecycle.mode == "fixed":
        return age >= lifecycle.lifetime_cycles
    if age < 2:
        return False
    return _draw(seed, cycle, slot, "lifecycle-hazard") < 1.0 / lifecycle.lifetime_cycles


def _initial_birth_cycle(lifecycle: LifecyclePolicy, *, slot: int, agents: int) -> int:
    if lifecycle.mode != "fixed":
        return 0
    assert lifecycle.lifetime_cycles is not None
    stagger = int(slot * lifecycle.lifetime_cycles / agents)
    age = (stagger + lifecycle.phase_offset) % lifecycle.lifetime_cycles
    return -age


def _lifecycle_utility(metrics: Mapping[str, float], domain_count: int) -> float:
    normalized_mi = metrics["agent_domain_mutual_information"] / math.log(domain_count)
    structure = (
        0.50 * normalized_mi
        + 0.30 * metrics["mean_specialization"]
        + 0.20 * metrics["winner_replacement_rate"]
    )
    return (
        metrics["success_rate"]
        + 0.08 * structure
        + 0.04 * metrics["mean_public_knowledge_signal"]
        - 0.10 * metrics["early_actor_incumbent_share"]
        - 0.06 * metrics["early_incumbent_share"]
        - 0.03 * metrics["mean_retrieval_lineage_hhi"]
        - 0.02 * metrics["credit_gini"]
    )


def _lifecycle_valid(
    candidate: Mapping[str, object],
    reference: Mapping[str, object],
    *,
    config,
    require_reduction: bool = True,
) -> tuple[bool, dict[str, float]]:
    cm = candidate["metrics"]
    rm = reference["metrics"]
    assert isinstance(cm, Mapping) and isinstance(rm, Mapping)
    knowledge_base = max(float(rm["mean_public_knowledge_signal"]), 1e-9)
    knowledge_ratio = float(cm["mean_public_knowledge_signal"]) / knowledge_base
    actor_reduction = float(rm["early_actor_incumbent_share"]) - float(cm["early_actor_incumbent_share"])
    lineage_delta = float(cm["early_incumbent_share"]) - float(rm["early_incumbent_share"])
    success_delta = float(cm["success_rate"]) - float(rm["success_rate"])
    invariants = candidate["invariants"]
    assert isinstance(invariants, Mapping)
    valid = (
        all(bool(value) for value in invariants.values())
        and success_delta >= -config.integration.success_tolerance
        and knowledge_ratio >= config.minimum_knowledge_retention
        and lineage_delta <= config.integration.incumbent_tolerance
        and (
            not require_reduction
            or actor_reduction >= config.minimum_actor_incumbency_reduction
        )
    )
    return valid, {
        "success_delta": success_delta,
        "actor_incumbency_reduction": actor_reduction,
        "lineage_incumbency_delta": lineage_delta,
        "knowledge_retention_ratio": knowledge_ratio,
    }


def run_succession_arm(
    connection: Connection[Any],
    *,
    config,
    config_hash: str,
    experiment_number: int,
    arm: SuccessionArm,
    seed: int,
    code_sha: str,
) -> dict[str, object]:
    if not connection.autocommit:
        raise ValueError("succession campaign requires autocommit")
    connection.row_factory = dict_row
    env = arm.environment
    lifecycle = arm.lifecycle
    run_id = uuid5(
        NAMESPACE_URL,
        f"succession:{code_sha}:{config_hash}:{experiment_number}:{arm.label}:{seed}",
    )
    start = _BASE_TIME + timedelta(days=experiment_number, hours=seed % 17)
    economy = PostgresEconomyRepository(connection)
    reputation = PostgresReputationRepository(connection)
    traces = PostgresTraceRepository(connection)

    current_ids: list[UUID] = []
    all_agent_ids: list[UUID] = []
    generation = [0 for _ in range(env.agents)]
    birth_cycle = [
        _initial_birth_cycle(lifecycle, slot=slot, agents=env.agents)
        for slot in range(env.agents)
    ]
    lineage_by_agent: dict[UUID, int] = {}
    practice: dict[tuple[UUID, str], int] = {}
    archived_practice: dict[int, dict[str, int]] = {}
    lifecycle_events: list[dict[str, object]] = []

    for slot in range(env.agents):
        agent_id = uuid5(run_id, f"agent:{slot}:gen:0")
        economy.register_agent(agent_id, at=start, initial_credits=env.initial_credits)
        current_ids.append(agent_id)
        all_agent_ids.append(agent_id)
        lineage_by_agent[agent_id] = slot

    rows: list[dict[str, object]] = []
    task_ids: list[UUID] = []
    first_bid_id: UUID | None = None
    first_score_id: UUID | None = None
    public_signals: list[float] = []
    lineage_hhis: list[float] = []
    predecessor_shares: list[float] = []
    newborn_outcomes: list[bool] = []

    for cycle in range(env.cycles):
        task_at = start + timedelta(seconds=cycle * env.cycle_seconds)

        for slot in range(env.agents):
            old_id = current_ids[slot]
            if not _replacement_due(
                lifecycle,
                seed=seed,
                cycle=cycle,
                slot=slot,
                birth_cycle=birth_cycle[slot],
            ):
                continue

            old_practice = {
                skill: count
                for (agent_id, skill), count in practice.items()
                if agent_id == old_id
            }
            if lifecycle.disposition in {"retire", "advisor"}:
                archived_practice[slot] = old_practice
            for key in [key for key in practice if key[0] == old_id]:
                del practice[key]

            generation[slot] += 1
            new_id = uuid5(run_id, f"agent:{slot}:gen:{generation[slot]}")
            economy.register_agent(
                new_id,
                at=task_at,
                initial_credits=env.initial_credits,
            )
            current_ids[slot] = new_id
            all_agent_ids.append(new_id)
            lineage_by_agent[new_id] = slot
            birth_cycle[slot] = cycle
            lifecycle_events.append(
                {
                    "cycle": cycle,
                    "slot": slot,
                    "generation": generation[slot],
                    "event_type": lifecycle.disposition,
                    "old_agent_id": old_id,
                    "new_agent_id": new_id,
                    "created_at": task_at,
                }
            )

        regime = cycle // env.shift_period
        regime_start_cycle = regime * env.shift_period
        regime_start_at = start + timedelta(seconds=regime_start_cycle * env.cycle_seconds)
        domain_index = _domain_index(seed, cycle, len(env.domains))
        task_domain = env.domains[domain_index]
        required_index = (domain_index + regime) % len(env.domains)
        required_skill = env.domains[required_index]
        requester_slot = _requester_slot(env, seed, cycle)
        requester_id = current_ids[requester_slot]

        provider = None
        if arm.policy.mode == "reputation":
            provider = PostgresReputationBidSignalProvider(
                connection,
                policy=arm.policy,
                population=current_ids,
                cycle_seconds=env.cycle_seconds,
            )
        market = PostgresMarketService(connection, economy, bid_signal_provider=provider)

        task = market.post_task(
            requester_id,
            description=f"Succession delegation for {task_domain}",
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
        candidate_public: dict[int, tuple[float, float, float]] = {}
        for candidate_slot in candidates:
            candidate_id = current_ids[candidate_slot]
            own_signal = _trace_signal(
                connection,
                agent_id=candidate_id,
                skill=required_skill,
                at=task_at,
            )
            public_signal, cultural_hhi, predecessor_share = _public_knowledge(
                connection,
                skill=required_skill,
                at=task_at,
                lineage_by_agent=lineage_by_agent,
                current_agent_id=candidate_id,
                current_lineage=candidate_slot,
                retrieval_k=config.public_retrieval_k,
                retrieval_mode=lifecycle.public_retrieval,
                diversity_per_lineage=config.cultural_diversity_per_lineage,
            )
            candidate_public[candidate_slot] = (
                public_signal,
                cultural_hhi,
                predecessor_share,
            )
            confidence = (
                env.confidence_base
                + env.confidence_evidence_weight * own_signal
                + config.public_confidence_gain * public_signal
                + env.confidence_noise_weight * _draw(seed, cycle, candidate_slot, "confidence")
            )
            if own_signal < 0.20:
                confidence += env.confidence_inflation
            confidence = max(0.05, min(0.98, confidence))
            price_fraction = env.price_floor + env.price_span * _draw(
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
                env.completion_span_seconds * _draw(
                    seed,
                    cycle,
                    candidate_slot,
                    "speed",
                )
            )
            completion = min(max(1, completion), env.bid_deadline_seconds - 1)
            bid = market.submit_bid(
                candidate_id,
                task_id=task.task_id,
                price=price,
                confidence=confidence,
                estimated_completion_seconds=completion,
                strategy_summary=f"generic succession bid slot {candidate_slot}",
                at=task_at + timedelta(microseconds=candidate_slot + 1),
            )
            if first_bid_id is None:
                first_bid_id = bid.bid_id

        award = market.award(task.task_id, at=task.deadline)
        assert award is not None
        winner_id = award.winning_bid.bidder_agent_id
        winner_slot = current_ids.index(winner_id)
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

        public_signal, cultural_hhi, predecessor_share = candidate_public[winner_slot]
        public_signals.append(public_signal)
        lineage_hhis.append(cultural_hhi)
        predecessor_shares.append(predecessor_share)

        practiced = practice.get((winner_id, required_skill), 0)
        advisor_practice = 0
        if lifecycle.advisory:
            advisor_practice = archived_practice.get(winner_slot, {}).get(required_skill, 0)
        success_probability = min(
            env.maximum_success_probability,
            env.base_success_probability
            + env.practice_gain * math.sqrt(practiced)
            + config.public_success_gain * public_signal
            + config.advisory_success_gain * min(1.0, math.sqrt(advisor_practice) / 3.0),
        )
        success = _draw(seed, cycle, winner_slot, "outcome") < success_probability
        if cycle - birth_cycle[winner_slot] < 6:
            newborn_outcomes.append(success)
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
                "winner_generation": generation[winner_slot],
                "winner_age": cycle - birth_cycle[winner_slot],
                "success": success,
                "recorded_positive": recorded_positive,
                "reputation_score": reputation_score,
                "winning_price": award.winning_bid.price,
                "task_budget": env.task_budget,
                "public_knowledge_signal": public_signal,
                "retrieval_lineage_hhi": cultural_hhi,
                "predecessor_lineage_share": predecessor_share,
                "created_at": task_at,
            }
        )

    assert first_bid_id is not None and first_score_id is not None
    structural = _summarize_rows(
        rows,
        domain_count=len(env.domains),
        shift_period=env.shift_period,
    )
    brier = statistics.mean(
        (float(row["reputation_score"]) - float(bool(row["success"]))) ** 2
        for row in rows
    )
    price_fraction = statistics.mean(
        int(row["winning_price"]) / int(row["task_budget"])
        for row in rows
    )
    active_balances = [economy.balance(agent_id) for agent_id in current_ids]
    metrics: dict[str, float] = {
        **structural,
        "early_actor_incumbent_share": _actor_incumbency(rows, env.shift_period),
        "reputation_brier_score": brier,
        "mean_winning_price_fraction": price_fraction,
        "credit_gini": _gini(active_balances),
        "turnover_events": float(len(lifecycle_events)),
        "turnover_rate": len(lifecycle_events) / max(1, env.cycles * env.agents),
        "mean_public_knowledge_signal": statistics.mean(public_signals) if public_signals else 0.0,
        "mean_retrieval_lineage_hhi": statistics.mean(lineage_hhis) if lineage_hhis else 0.0,
        "mean_predecessor_lineage_share": (
            statistics.mean(predecessor_shares) if predecessor_shares else 0.0
        ),
        "newborn_success_rate": (
            statistics.mean(float(value) for value in newborn_outcomes)
            if newborn_outcomes
            else 0.0
        ),
        "max_generation": float(max(generation)),
    }
    invariants = _run_invariants(
        connection,
        task_ids=task_ids,
        agent_ids=all_agent_ids,
        first_bid_id=first_bid_id,
        first_score_id=first_score_id,
        expected_evidence=2 * env.cycles,
    )

    env_payload = env.as_dict()
    env_payload["lifecycle"] = lifecycle.as_dict()
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
                config.integration.name,
                experiment_number,
                arm.label,
                seed,
                Jsonb(arm.policy.as_dict()),
                Jsonb(env_payload),
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
        for event in lifecycle_events:
            connection.execute(
                """
                INSERT INTO succession_events (
                    run_id, cycle, slot, generation, event_type,
                    old_agent_id, new_agent_id, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    event["cycle"],
                    event["slot"],
                    event["generation"],
                    event["event_type"],
                    event["old_agent_id"],
                    event["new_agent_id"],
                    event["created_at"],
                ),
            )

    return {
        "run_id": str(run_id),
        "seed": seed,
        "arm_label": arm.label,
        "policy": arm.policy.as_dict(),
        "environment": env_payload,
        "lifecycle": lifecycle.as_dict(),
        "metrics": metrics,
        "invariants": invariants,
    }


def aggregate_succession_arm(cells: Sequence[Mapping[str, object]]) -> dict[str, object]:
    first = cells[0]
    metric_names = list(first["metrics"].keys())  # type: ignore[union-attr]
    metrics = {
        key: statistics.mean(float(cell["metrics"][key]) for cell in cells)  # type: ignore[index]
        for key in metric_names
    }
    invariant_names = list(first["invariants"].keys())  # type: ignore[union-attr]
    invariants = {
        key: all(bool(cell["invariants"][key]) for cell in cells)  # type: ignore[index]
        for key in invariant_names
    }
    result = {
        "label": first["arm_label"],
        "policy": first["policy"],
        "environment": first["environment"],
        "lifecycle": first["lifecycle"],
        "metrics": metrics,
        "invariants": invariants,
        "run_ids": [cell["run_id"] for cell in cells],
    }
    domain_count = len(first["environment"]["domains"])  # type: ignore[index]
    result["utility"] = _lifecycle_utility(metrics, domain_count)
    return result


def run_succession_experiment(
    connection: Connection[Any],
    *,
    config,
    config_hash: str,
    code_sha: str,
    number: int,
    arms: Sequence[SuccessionArm],
    seeds: Sequence[int],
) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for arm in arms:
        cells = [
            run_succession_arm(
                connection,
                config=config,
                config_hash=config_hash,
                experiment_number=number,
                arm=arm,
                seed=seed,
                code_sha=code_sha,
            )
            for seed in seeds
        ]
        summaries.append(aggregate_succession_arm(cells))
    return summaries


def immortal_arm(label: str, *, policy: ReputationPolicy, env: IntegrationEnvironment) -> SuccessionArm:
    return SuccessionArm(label, policy, env, LifecyclePolicy())


def finite_arm(
    label: str,
    *,
    policy: ReputationPolicy,
    env: IntegrationEnvironment,
    lifetime: int,
    mode: str = "fixed",
    disposition: str = "retire",
    advisory: bool = False,
    public_retrieval: str = "standard",
    phase_offset: int = 0,
) -> SuccessionArm:
    return SuccessionArm(
        label,
        policy,
        env,
        LifecyclePolicy(
            mode=mode,
            lifetime_cycles=lifetime,
            disposition=disposition,
            advisory=advisory,
            public_retrieval=public_retrieval,
            phase_offset=phase_offset,
        ),
    )


def choose_lifecycle(
    arms: Sequence[dict[str, object]],
    *,
    reference_label: str,
    config,
    require_reduction: bool = True,
) -> tuple[dict[str, object], dict[str, object], dict[str, dict[str, float]]]:
    reference = next(arm for arm in arms if arm["label"] == reference_label)
    diagnostics: dict[str, dict[str, float]] = {}
    eligible: list[dict[str, object]] = []
    for arm in arms:
        if arm["label"] == reference_label:
            continue
        valid, diag = _lifecycle_valid(
            arm,
            reference,
            config=config,
            require_reduction=require_reduction,
        )
        diagnostics[str(arm["label"])] = diag
        if valid:
            eligible.append(arm)
    selected = max(
        eligible or [reference],
        key=lambda arm: (float(arm["utility"]), str(arm["label"])),
    )
    return selected, reference, diagnostics


def lifecycle_interaction(
    *,
    immortal_reputation: Mapping[str, object],
    lifecycle_reputation: Mapping[str, object],
    immortal_none: Mapping[str, object],
    lifecycle_none: Mapping[str, object],
) -> float:
    def success(arm: Mapping[str, object]) -> float:
        metrics = arm["metrics"]
        assert isinstance(metrics, Mapping)
        return float(metrics["success_rate"])

    return (
        success(lifecycle_reputation)
        - success(immortal_reputation)
        - (success(lifecycle_none) - success(immortal_none))
    )


def reference_reputation_policy() -> ReputationPolicy:
    return reference_policy()


def no_reputation_policy() -> ReputationPolicy:
    return ReputationPolicy()
