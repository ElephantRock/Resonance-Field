"""Adaptive PostgreSQL integration campaign for Experiments 014 through 040."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from resonance.economy import PostgresEconomyRepository
from resonance.market import BidSignal, MarketBid, MarketTask, PostgresMarketService
from resonance.reputation import PostgresReputationRepository
from resonance.substrate.models import Trace
from resonance.substrate.postgres import PostgresTraceRepository

from .adaptive_campaign import _summarize_rows

_DOMAIN_DIMENSION = "task_domain_success"
_SKILL_DIMENSION = "skill_success"
_BASE_TIME = datetime(2026, 8, 10, tzinfo=UTC)
_TREASURY_TOTAL = 1_000_000_000_000


@dataclass(frozen=True, slots=True)
class ReputationPolicy:
    mode: str = "none"
    weight: float = 0.0
    freshness_half_life_cycles: float | None = None
    mass_gate: float = 0.0
    blend_skill: float = 0.0
    positive_weight: float = 1.0
    negative_weight: float = 1.0
    shift_reset: float = 0.0
    temperature: float = 1.0
    score_cap: float = 0.30
    uncertainty_prior: float = 0.0
    exposure_penalty: float = 0.0
    exposure_window: int = 24

    def __post_init__(self) -> None:
        if self.mode not in {"none", "reputation"}:
            raise ValueError("mode must be none or reputation")
        if not 0.0 <= self.weight <= 0.75:
            raise ValueError("weight must be in [0, 0.75]")
        if self.freshness_half_life_cycles is not None and self.freshness_half_life_cycles <= 0:
            raise ValueError("freshness_half_life_cycles must be positive")
        if self.mass_gate < 0:
            raise ValueError("mass_gate must be non-negative")
        if not 0.0 <= self.blend_skill <= 1.0:
            raise ValueError("blend_skill must be in [0, 1]")
        if self.positive_weight <= 0 or self.negative_weight <= 0:
            raise ValueError("evidence weights must be positive")
        if not 0.0 <= self.shift_reset <= 1.0:
            raise ValueError("shift_reset must be in [0, 1]")
        if self.temperature <= 0:
            raise ValueError("temperature must be positive")
        if self.score_cap <= 0:
            raise ValueError("score_cap must be positive")
        if self.uncertainty_prior < 0:
            raise ValueError("uncertainty_prior must be non-negative")
        if self.exposure_penalty < 0 or self.exposure_window <= 0:
            raise ValueError("exposure controls must be non-negative and positive")

    @property
    def label(self) -> str:
        if self.mode == "none":
            return "no_reputation"
        fresh = (
            "raw"
            if self.freshness_half_life_cycles is None
            else f"fresh{self.freshness_half_life_cycles:g}"
        )
        return (
            f"blend-w{self.weight:.2f}-{fresh}-g{self.mass_gate:g}"
            f"-p{self.positive_weight:g}-n{self.negative_weight:g}"
            f"-r{self.shift_reset:g}-b{self.blend_skill:g}"
            f"-t{self.temperature:g}-c{self.score_cap:g}"
            f"-u{self.uncertainty_prior:g}-x{self.exposure_penalty:g}"
            f"-z{self.exposure_window}"
        )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IntegrationEnvironment:
    agents: int
    domains: tuple[str, ...]
    cycles: int
    cycle_seconds: int
    shift_period: int
    candidate_count: int
    task_budget: int
    bid_deadline_seconds: int
    trace_half_life_cycles: float
    initial_credits: int
    base_success_probability: float
    practice_gain: float
    maximum_success_probability: float
    confidence_base: float
    confidence_evidence_weight: float
    confidence_noise_weight: float
    price_floor: float
    price_span: float
    completion_min_seconds: int
    completion_span_seconds: int
    evidence_noise: float = 0.0
    requester_skew: float = 0.0
    confidence_inflation: float = 0.0

    def __post_init__(self) -> None:
        if self.agents <= 2 or len(self.domains) <= 1:
            raise ValueError("population and domains must exceed trivial size")
        if self.cycles <= self.shift_period or self.shift_period <= 0:
            raise ValueError("environment must contain at least one regime shift")
        if not 1 <= self.candidate_count < self.agents:
            raise ValueError("candidate_count must be between one and population")
        if min(
            self.cycle_seconds,
            self.task_budget,
            self.bid_deadline_seconds,
            self.initial_credits,
            self.completion_min_seconds,
        ) <= 0:
            raise ValueError("market/time bounds must be positive")
        if self.bid_deadline_seconds >= self.cycle_seconds:
            raise ValueError("cycle_seconds must exceed bid deadline")
        if self.trace_half_life_cycles <= 0 or self.completion_span_seconds < 0:
            raise ValueError("trace half-life must be positive and completion span non-negative")
        if not 0 <= self.base_success_probability <= self.maximum_success_probability <= 1:
            raise ValueError("success probabilities are invalid")
        if self.practice_gain < 0:
            raise ValueError("practice_gain must be non-negative")
        if not 0 <= self.confidence_base <= 1:
            raise ValueError("confidence_base must be in [0, 1]")
        if self.confidence_evidence_weight < 0 or self.confidence_noise_weight < 0:
            raise ValueError("confidence weights must be non-negative")
        if not 0 < self.price_floor < 1 or not 0 <= self.price_span < 1:
            raise ValueError("price controls must be fractions")
        if not 0 <= self.evidence_noise <= 0.5:
            raise ValueError("evidence_noise must be in [0, 0.5]")
        if not 0 <= self.requester_skew <= 0.8:
            raise ValueError("requester_skew must be in [0, 0.8]")
        if not 0 <= self.confidence_inflation <= 0.5:
            raise ValueError("confidence_inflation must be in [0, 0.5]")

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["domains"] = list(self.domains)
        return result


@dataclass(frozen=True, slots=True)
class IntegrationCampaignConfig:
    name: str
    environment: IntegrationEnvironment
    seeds: tuple[int, ...]
    holdout_seeds: tuple[int, ...]
    holdout_cycles: int
    holdout_shift_period: int
    holdout_candidate_count: int
    success_tolerance: float
    incumbent_tolerance: float
    economic_tolerance: float

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.seeds or not self.holdout_seeds:
            raise ValueError("campaign name and seed sets are required")
        if self.holdout_cycles <= self.holdout_shift_period:
            raise ValueError("holdout must contain a regime shift")
        if not 1 <= self.holdout_candidate_count < self.environment.agents:
            raise ValueError("invalid holdout_candidate_count")
        if min(self.success_tolerance, self.incumbent_tolerance, self.economic_tolerance) < 0:
            raise ValueError("selection tolerances must be non-negative")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> IntegrationCampaignConfig:
        env_value = value["environment"]
        assert isinstance(env_value, Mapping)
        env = IntegrationEnvironment(
            agents=int(env_value["agents"]),
            domains=tuple(str(item) for item in env_value["domains"]),
            cycles=int(env_value["cycles"]),
            cycle_seconds=int(env_value["cycle_seconds"]),
            shift_period=int(env_value["shift_period"]),
            candidate_count=int(env_value["candidate_count"]),
            task_budget=int(env_value["task_budget"]),
            bid_deadline_seconds=int(env_value["bid_deadline_seconds"]),
            trace_half_life_cycles=float(env_value["trace_half_life_cycles"]),
            initial_credits=int(env_value["initial_credits"]),
            base_success_probability=float(env_value["base_success_probability"]),
            practice_gain=float(env_value["practice_gain"]),
            maximum_success_probability=float(env_value["maximum_success_probability"]),
            confidence_base=float(env_value["confidence_base"]),
            confidence_evidence_weight=float(env_value["confidence_evidence_weight"]),
            confidence_noise_weight=float(env_value["confidence_noise_weight"]),
            price_floor=float(env_value["price_floor"]),
            price_span=float(env_value["price_span"]),
            completion_min_seconds=int(env_value["completion_min_seconds"]),
            completion_span_seconds=int(env_value["completion_span_seconds"]),
            evidence_noise=float(env_value.get("evidence_noise", 0.0)),
            requester_skew=float(env_value.get("requester_skew", 0.0)),
            confidence_inflation=float(env_value.get("confidence_inflation", 0.0)),
        )
        return cls(
            name=str(value["name"]),
            environment=env,
            seeds=tuple(int(item) for item in value["seeds"]),
            holdout_seeds=tuple(int(item) for item in value["holdout_seeds"]),
            holdout_cycles=int(value["holdout_cycles"]),
            holdout_shift_period=int(value["holdout_shift_period"]),
            holdout_candidate_count=int(value["holdout_candidate_count"]),
            success_tolerance=float(value["success_tolerance"]),
            incumbent_tolerance=float(value["incumbent_tolerance"]),
            economic_tolerance=float(value["economic_tolerance"]),
        )


@dataclass(frozen=True, slots=True)
class ArmSpec:
    label: str
    policy: ReputationPolicy
    environment: IntegrationEnvironment


class PostgresReputationBidSignalProvider:
    """Read-only reputation signal provider backed by auditable evidence rows."""

    def __init__(
        self,
        connection: Connection[Any],
        *,
        policy: ReputationPolicy,
        population: Sequence[UUID],
        cycle_seconds: int,
    ) -> None:
        connection.row_factory = dict_row
        self._connection = connection
        self._policy = policy
        self._population = tuple(population)
        self._cycle_seconds = cycle_seconds

    def _stats(
        self,
        agent_id: UUID,
        *,
        dimension: str,
        context_key: str,
        regime_start: datetime,
    ) -> tuple[float, float, datetime | None]:
        row = self._connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN positive AND created_at < %s THEN weight ELSE 0 END), 0.0)
                    AS pre_positive,
                COALESCE(SUM(CASE WHEN NOT positive AND created_at < %s THEN weight ELSE 0 END), 0.0)
                    AS pre_negative,
                COALESCE(SUM(CASE WHEN positive AND created_at >= %s THEN weight ELSE 0 END), 0.0)
                    AS post_positive,
                COALESCE(SUM(CASE WHEN NOT positive AND created_at >= %s THEN weight ELSE 0 END), 0.0)
                    AS post_negative,
                MAX(created_at) AS latest
            FROM reputation_evidence
            WHERE agent_id = %s AND dimension = %s AND context_key = %s
            """,
            (
                regime_start,
                regime_start,
                regime_start,
                regime_start,
                agent_id,
                dimension,
                context_key,
            ),
        ).fetchone()
        assert row is not None
        retained = 1.0 - self._policy.shift_reset
        positive = retained * float(row["pre_positive"]) + float(row["post_positive"])
        negative = retained * float(row["pre_negative"]) + float(row["post_negative"])
        return positive, negative, row["latest"]

    def _active_score(
        self,
        agent_id: UUID,
        *,
        dimension: str,
        context_key: str,
        regime_start: datetime,
        at: datetime,
    ) -> tuple[float, float]:
        positive, negative, latest = self._stats(
            agent_id,
            dimension=dimension,
            context_key=context_key,
            regime_start=regime_start,
        )
        positive *= self._policy.positive_weight
        negative *= self._policy.negative_weight
        mass = positive + negative
        raw = (1.0 + positive) / (2.0 + mass)

        if self._policy.freshness_half_life_cycles is None:
            freshness = 1.0
        elif latest is None:
            freshness = 0.0
        else:
            age_cycles = max(0.0, (at - latest).total_seconds() / self._cycle_seconds)
            freshness = 2 ** (-age_cycles / self._policy.freshness_half_life_cycles)

        mass_factor = (
            1.0
            if self._policy.mass_gate <= 0
            else mass / (mass + self._policy.mass_gate)
        )
        uncertainty = (
            1.0
            if self._policy.uncertainty_prior <= 0
            else mass / (mass + self._policy.uncertainty_prior)
        )
        active = 0.5 + (raw - 0.5) * freshness * mass_factor * uncertainty
        return active, mass

    def _exposure(self, agent_id: UUID, *, at: datetime) -> float:
        if self._policy.exposure_penalty <= 0:
            return 0.0
        start = at - timedelta(seconds=self._policy.exposure_window * self._cycle_seconds)
        row = self._connection.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE awarded_agent_id = %s) AS wins,
                COUNT(*) AS total
            FROM market_tasks
            WHERE awarded_agent_id = ANY(%s) AND awarded_at >= %s AND awarded_at < %s
            """,
            (agent_id, list(self._population), start, at),
        ).fetchone()
        assert row is not None
        total = int(row["total"])
        if not total:
            return 0.0
        share = int(row["wins"]) / total
        equal_share = 1.0 / len(self._population)
        return max(0.0, share - equal_share)

    def signal(self, task: MarketTask, bid: MarketBid, *, at: datetime) -> BidSignal:
        condition = task.success_condition
        domain = str(condition.get("task_domain", "global"))
        skill = str(condition.get("required_skill", domain))
        raw_regime_start = condition.get("regime_start_at")
        if isinstance(raw_regime_start, datetime):
            regime_start = raw_regime_start
        elif isinstance(raw_regime_start, str):
            regime_start = datetime.fromisoformat(raw_regime_start)
        else:
            regime_start = task.created_at

        domain_score, domain_mass = self._active_score(
            bid.bidder_agent_id,
            dimension=_DOMAIN_DIMENSION,
            context_key=domain,
            regime_start=regime_start,
            at=at,
        )
        skill_score, skill_mass = self._active_score(
            bid.bidder_agent_id,
            dimension=_SKILL_DIMENSION,
            context_key=skill,
            regime_start=regime_start,
            at=at,
        )
        score = (1.0 - self._policy.blend_skill) * domain_score + self._policy.blend_skill * skill_score
        centered = (score - 0.5) / self._policy.temperature
        centered = max(-0.5, min(0.5, centered))
        reputation_adjustment = self._policy.weight * centered
        reputation_adjustment = max(
            -self._policy.score_cap,
            min(self._policy.score_cap, reputation_adjustment),
        )
        exposure = self._exposure(bid.bidder_agent_id, at=at)
        exposure_adjustment = -self._policy.exposure_penalty * exposure
        adjustment = reputation_adjustment + exposure_adjustment
        return BidSignal(
            adjustment=adjustment,
            provider_label=self._policy.label,
            components={
                "reputation_score": score,
                "domain_score": domain_score,
                "skill_score": skill_score,
                "domain_mass": domain_mass,
                "skill_mass": skill_mass,
                "reputation_adjustment": reputation_adjustment,
                "exposure_share_excess": exposure,
                "exposure_adjustment": exposure_adjustment,
            },
        )


def validated_policy() -> ReputationPolicy:
    return ReputationPolicy(
        mode="reputation",
        weight=0.55,
        freshness_half_life_cycles=24.0,
        mass_gate=2.0,
        blend_skill=0.25,
        positive_weight=2.0,
        negative_weight=1.0,
        shift_reset=0.8,
    )


def raw_policy() -> ReputationPolicy:
    return ReputationPolicy(
        mode="reputation",
        weight=0.45,
        freshness_half_life_cycles=None,
        mass_gate=0.0,
        blend_skill=0.0,
        positive_weight=1.0,
        negative_weight=1.0,
        shift_reset=0.0,
    )


def _draw(seed: int, cycle: int, slot: int, label: str) -> float:
    digest = hashlib.sha256(f"{label}:{seed}:{cycle}:{slot}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / (2**64 - 1)


def _domain_index(seed: int, cycle: int, domain_count: int) -> int:
    digest = hashlib.sha256(f"domain:{seed}:{cycle}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % domain_count


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


def _trace_signal(
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


def _gini(values: Sequence[int]) -> float:
    if not values or sum(values) == 0:
        return 0.0
    ordered = sorted(values)
    count = len(ordered)
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    return (2 * weighted) / (count * sum(ordered)) - (count + 1) / count


def _mean_mapping(rows: Sequence[Mapping[str, float]]) -> dict[str, float]:
    keys = rows[0].keys()
    return {key: statistics.mean(float(row[key]) for row in rows) for key in keys}


def _arm_label_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value).replace(" ", "_")


def _requester_slot(env: IntegrationEnvironment, seed: int, cycle: int) -> int:
    ordinary = cycle % env.agents
    if env.requester_skew <= 0 or ordinary == 0:
        return ordinary
    return 0 if _draw(seed, cycle, 0, "requester-skew") < env.requester_skew else ordinary


def _run_invariants(
    connection: Connection[Any],
    *,
    task_ids: Sequence[UUID],
    agent_ids: Sequence[UUID],
    first_bid_id: UUID,
    first_score_id: UUID,
    expected_evidence: int,
) -> dict[str, bool]:
    total = connection.execute("SELECT SUM(balance) AS total FROM compute_accounts").fetchone()
    ledger_conserved = total is not None and int(total["total"]) == _TREASURY_TOTAL

    unbalanced = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT transaction_id
            FROM compute_postings
            GROUP BY transaction_id
            HAVING SUM(amount) <> 0
        ) broken
        """
    ).fetchone()
    balanced_ledger = unbalanced is not None and int(unbalanced["count"]) == 0

    escrow = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM market_tasks mt
        JOIN compute_accounts ca ON ca.account_id = mt.escrow_account_id
        WHERE mt.task_id = ANY(%s) AND mt.status = 'completed' AND ca.balance <> 0
        """,
        (list(task_ids),),
    ).fetchone()
    zero_completed_escrow = escrow is not None and int(escrow["count"]) == 0

    bid_count = connection.execute(
        "SELECT COUNT(*) AS count FROM market_bids WHERE task_id = ANY(%s)",
        (list(task_ids),),
    ).fetchone()
    score_count = connection.execute(
        "SELECT COUNT(*) AS count FROM market_auction_scores WHERE task_id = ANY(%s)",
        (list(task_ids),),
    ).fetchone()
    selected_count = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM market_auction_scores
        WHERE task_id = ANY(%s) AND selected
        """,
        (list(task_ids),),
    ).fetchone()
    score_coverage = (
        bid_count is not None
        and score_count is not None
        and int(bid_count["count"]) == int(score_count["count"])
        and selected_count is not None
        and int(selected_count["count"]) == len(task_ids)
    )

    evidence = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM reputation_evidence
        WHERE agent_id = ANY(%s)
          AND source_type IN ('integration_domain', 'integration_skill')
        """,
        (list(agent_ids),),
    ).fetchone()
    evidence_idempotent = evidence is not None and int(evidence["count"]) == expected_evidence

    bid_immutable = False
    try:
        connection.execute(
            "UPDATE market_bids SET confidence = 0.01 WHERE bid_id = %s",
            (first_bid_id,),
        )
    except psycopg.errors.RaiseException:
        bid_immutable = True

    score_immutable = False
    try:
        connection.execute(
            "UPDATE market_auction_scores SET total_score = 0 WHERE auction_score_id = %s",
            (first_score_id,),
        )
    except psycopg.errors.RaiseException:
        score_immutable = True

    reputation_spend = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM compute_transactions
        WHERE lower(reason) LIKE '%reputation%'
        """
    ).fetchone()
    reputation_nonspendable = reputation_spend is not None and int(reputation_spend["count"]) == 0

    return {
        "ledger_conserved": ledger_conserved,
        "balanced_ledger": balanced_ledger,
        "zero_completed_escrow": zero_completed_escrow,
        "score_provenance_complete": score_coverage,
        "reputation_evidence_idempotent": evidence_idempotent,
        "sealed_bids_immutable": bid_immutable,
        "score_provenance_immutable": score_immutable,
        "reputation_nonspendable": reputation_nonspendable,
    }


def run_integration_arm(
    connection: Connection[Any],
    *,
    config: IntegrationCampaignConfig,
    config_hash: str,
    experiment_number: int,
    arm: ArmSpec,
    seed: int,
    code_sha: str,
) -> dict[str, object]:
    if not connection.autocommit:
        raise ValueError("integration campaign requires autocommit")
    connection.row_factory = dict_row
    env = arm.environment
    run_id = uuid5(
        NAMESPACE_URL,
        f"integration:{code_sha}:{config_hash}:{experiment_number}:{arm.label}:{seed}",
    )
    start = _BASE_TIME + timedelta(days=experiment_number, hours=seed % 17)
    economy = PostgresEconomyRepository(connection)
    reputation = PostgresReputationRepository(connection)
    traces = PostgresTraceRepository(connection)
    agent_ids: list[UUID] = []
    practice: dict[tuple[int, str], int] = {}

    for slot in range(env.agents):
        agent_id = uuid5(run_id, f"agent:{slot}")
        economy.register_agent(
            agent_id,
            at=start,
            initial_credits=env.initial_credits,
        )
        agent_ids.append(agent_id)

    provider = None
    if arm.policy.mode == "reputation":
        provider = PostgresReputationBidSignalProvider(
            connection,
            policy=arm.policy,
            population=agent_ids,
            cycle_seconds=env.cycle_seconds,
        )
    market = PostgresMarketService(
        connection,
        economy,
        bid_signal_provider=provider,
    )

    rows: list[dict[str, object]] = []
    task_ids: list[UUID] = []
    first_bid_id: UUID | None = None
    first_score_id: UUID | None = None

    for cycle in range(env.cycles):
        task_at = start + timedelta(seconds=cycle * env.cycle_seconds)
        regime = cycle // env.shift_period
        regime_start_cycle = regime * env.shift_period
        regime_start_at = start + timedelta(seconds=regime_start_cycle * env.cycle_seconds)
        domain_index = _domain_index(seed, cycle, len(env.domains))
        task_domain = env.domains[domain_index]
        required_index = (domain_index + regime) % len(env.domains)
        required_skill = env.domains[required_index]
        requester_slot = _requester_slot(env, seed, cycle)
        requester_id = agent_ids[requester_slot]

        task = market.post_task(
            requester_id,
            description=f"Integration delegation for {task_domain}",
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
            candidate_id = agent_ids[candidate_slot]
            evidence_signal = _trace_signal(
                connection,
                agent_id=candidate_id,
                skill=required_skill,
                at=task_at,
            )
            confidence = (
                env.confidence_base
                + env.confidence_evidence_weight * evidence_signal
                + env.confidence_noise_weight * _draw(seed, cycle, candidate_slot, "confidence")
            )
            if evidence_signal < 0.20:
                confidence += env.confidence_inflation
            confidence = max(0.05, min(0.98, confidence))
            price_fraction = env.price_floor + env.price_span * _draw(
                seed,
                cycle,
                candidate_slot,
                "price",
            )
            price = max(1, min(env.task_budget, int(env.task_budget * min(0.95, price_fraction))))
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
                strategy_summary=f"generic integration bid slot {candidate_slot}",
                at=task_at + timedelta(microseconds=candidate_slot + 1),
            )
            if first_bid_id is None:
                first_bid_id = bid.bid_id

        award_at = task.deadline
        award = market.award(task.task_id, at=award_at)
        assert award is not None
        winner_id = award.winning_bid.bidder_agent_id
        winner_slot = agent_ids.index(winner_id)
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

        practiced = practice.get((winner_slot, required_skill), 0)
        success_probability = min(
            env.maximum_success_probability,
            env.base_success_probability + env.practice_gain * math.sqrt(practiced),
        )
        success = _draw(seed, cycle, winner_slot, "outcome") < success_probability
        noise_flip = _draw(seed, cycle, winner_slot, "evidence-noise") < env.evidence_noise
        recorded_positive = not success if noise_flip else success
        outcome_at = award_at + timedelta(seconds=1)

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
        practice[(winner_slot, required_skill)] = practiced + 1
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
                "success": success,
                "recorded_positive": recorded_positive,
                "reputation_score": reputation_score,
                "winning_price": award.winning_bid.price,
                "task_budget": env.task_budget,
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
        int(row["winning_price"]) / int(row["task_budget"]) for row in rows
    )
    balances = [economy.balance(agent_id) for agent_id in agent_ids]
    metrics: dict[str, float] = {
        **structural,
        "reputation_brier_score": brier,
        "mean_winning_price_fraction": price_fraction,
        "credit_gini": _gini(balances),
    }
    invariants = _run_invariants(
        connection,
        task_ids=task_ids,
        agent_ids=agent_ids,
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
                Jsonb(arm.policy.as_dict()),
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

    return {
        "run_id": str(run_id),
        "seed": seed,
        "arm_label": arm.label,
        "policy": arm.policy.as_dict(),
        "environment": env.as_dict(),
        "metrics": metrics,
        "invariants": invariants,
    }


def _aggregate_arm(cells: Sequence[Mapping[str, object]]) -> dict[str, object]:
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
        "environment": first["environment"],
        "metrics": metrics,
        "invariants": invariants,
        "run_ids": [cell["run_id"] for cell in cells],
    }


def _structure_score(metrics: Mapping[str, float], domain_count: int) -> float:
    normalized_mi = metrics["agent_domain_mutual_information"] / math.log(domain_count)
    return (
        0.55 * normalized_mi
        + 0.35 * metrics["mean_specialization"]
        - 0.20 * metrics["mean_winner_hhi"]
        + 0.10 * metrics["winner_replacement_rate"]
    )


def _feasible(
    arm: Mapping[str, object],
    control: Mapping[str, object],
    config: IntegrationCampaignConfig,
) -> bool:
    invariants = arm["invariants"]
    assert isinstance(invariants, Mapping)
    if not all(bool(value) for value in invariants.values()):
        return False
    metrics = arm["metrics"]
    control_metrics = control["metrics"]
    assert isinstance(metrics, Mapping) and isinstance(control_metrics, Mapping)
    return (
        float(metrics["success_rate"])
        >= float(control_metrics["success_rate"]) - config.success_tolerance
        and float(metrics["early_incumbent_share"])
        <= float(control_metrics["early_incumbent_share"]) + config.incumbent_tolerance
        and float(metrics["mean_winning_price_fraction"])
        <= float(control_metrics["mean_winning_price_fraction"]) + config.economic_tolerance
        and float(metrics["credit_gini"])
        <= float(control_metrics["credit_gini"]) + config.economic_tolerance
    )


def _utility(metrics: Mapping[str, float], domain_count: int) -> float:
    return (
        metrics["success_rate"]
        + 0.10 * _structure_score(metrics, domain_count)
        + 0.03 * metrics["winner_replacement_rate"]
        - 0.08 * metrics["early_incumbent_share"]
        - 0.04 * metrics["reputation_brier_score"]
        - 0.03 * metrics["mean_winning_price_fraction"]
        - 0.03 * metrics["credit_gini"]
    )


def _evaluate_arms(
    arms: Sequence[dict[str, object]],
    *,
    config: IntegrationCampaignConfig,
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    control = next(arm for arm in arms if arm["label"] == "no_reputation")
    domain_count = len(config.environment.domains)
    evaluated: list[dict[str, object]] = []
    for arm in arms:
        metrics = arm["metrics"]
        assert isinstance(metrics, Mapping)
        item = dict(arm)
        item["feasible"] = _feasible(arm, control, config)
        item["utility"] = _utility(metrics, domain_count)
        evaluated.append(item)

    reputation_candidates = [
        arm
        for arm in evaluated
        if arm["label"] != "no_reputation" and bool(arm["feasible"])
    ]
    pool = reputation_candidates or [arm for arm in evaluated if bool(arm["feasible"])]
    if not pool:
        pool = evaluated
    selected = max(pool, key=lambda item: (float(item["utility"]), str(item["label"])))
    return evaluated, selected, control


def _failure_mode(
    selected: Mapping[str, object],
    control: Mapping[str, object],
    config: IntegrationCampaignConfig,
) -> str:
    invariants = selected["invariants"]
    assert isinstance(invariants, Mapping)
    if not all(bool(value) for value in invariants.values()):
        return "integrity"
    metrics = selected["metrics"]
    baseline = control["metrics"]
    assert isinstance(metrics, Mapping) and isinstance(baseline, Mapping)
    if float(metrics["success_rate"]) < float(baseline["success_rate"]) - 0.005:
        return "quality"
    if float(metrics["early_incumbent_share"]) > float(baseline["early_incumbent_share"]) + 0.02:
        return "plasticity"
    if (
        float(metrics["mean_winning_price_fraction"])
        > float(baseline["mean_winning_price_fraction"]) + 0.03
        or float(metrics["credit_gini"]) > float(baseline["credit_gini"]) + 0.03
    ):
        return "economic"
    if float(metrics["reputation_brier_score"]) > float(baseline["reputation_brier_score"]) + 0.01:
        return "calibration"
    if float(metrics["mean_winner_hhi"]) > 0.18:
        return "concentration"
    if (
        float(metrics["agent_domain_mutual_information"])
        <= float(baseline["agent_domain_mutual_information"]) + 0.01
        and float(metrics["mean_specialization"])
        <= float(baseline["mean_specialization"]) + 0.01
    ):
        return "structure"
    return "robustness"


_DIMENSIONS = (
    "reputation_weight",
    "freshness",
    "blend_skill",
    "mass_gate",
    "positive_weight",
    "negative_weight",
    "shift_reset",
    "temperature",
    "score_cap",
    "uncertainty_prior",
    "exposure_penalty",
    "exposure_window",
    "candidate_count",
    "task_budget",
    "trace_half_life",
    "confidence_evidence",
    "confidence_noise",
    "practice_gain",
    "shift_period",
    "price_pressure",
    "speed_pressure",
    "evidence_noise",
    "requester_skew",
)

_PRIORITIES: dict[str, tuple[str, ...]] = {
    "quality": (
        "reputation_weight",
        "temperature",
        "score_cap",
        "uncertainty_prior",
        "confidence_evidence",
        "practice_gain",
        "candidate_count",
        "freshness",
    ),
    "plasticity": (
        "freshness",
        "shift_reset",
        "exposure_penalty",
        "exposure_window",
        "blend_skill",
        "negative_weight",
        "shift_period",
    ),
    "concentration": (
        "exposure_penalty",
        "exposure_window",
        "candidate_count",
        "requester_skew",
        "blend_skill",
        "shift_reset",
    ),
    "calibration": (
        "uncertainty_prior",
        "mass_gate",
        "positive_weight",
        "negative_weight",
        "freshness",
        "evidence_noise",
        "temperature",
    ),
    "economic": (
        "task_budget",
        "price_pressure",
        "score_cap",
        "candidate_count",
        "reputation_weight",
        "requester_skew",
    ),
    "structure": (
        "positive_weight",
        "blend_skill",
        "reputation_weight",
        "confidence_evidence",
        "trace_half_life",
        "practice_gain",
        "mass_gate",
    ),
    "integrity": (
        "score_cap",
        "mass_gate",
        "reputation_weight",
    ),
    "robustness": (
        "trace_half_life",
        "shift_period",
        "candidate_count",
        "evidence_noise",
        "confidence_noise",
        "price_pressure",
        "requester_skew",
    ),
}


def _choose_dimension(failure: str, tested: set[str]) -> str:
    for dimension in _PRIORITIES.get(failure, ()):
        if dimension not in tested:
            return dimension
    for dimension in _DIMENSIONS:
        if dimension not in tested:
            return dimension
    raise RuntimeError("all adaptive dimensions have already been tested")


def _replace_dimension(
    policy: ReputationPolicy,
    env: IntegrationEnvironment,
    dimension: str,
    value: float | int,
) -> tuple[ReputationPolicy, IntegrationEnvironment]:
    if dimension == "reputation_weight":
        return replace(policy, weight=float(value)), env
    if dimension == "freshness":
        return replace(policy, freshness_half_life_cycles=float(value)), env
    if dimension == "blend_skill":
        return replace(policy, blend_skill=float(value)), env
    if dimension == "mass_gate":
        return replace(policy, mass_gate=float(value)), env
    if dimension == "positive_weight":
        return replace(policy, positive_weight=float(value)), env
    if dimension == "negative_weight":
        return replace(policy, negative_weight=float(value)), env
    if dimension == "shift_reset":
        return replace(policy, shift_reset=float(value)), env
    if dimension == "temperature":
        return replace(policy, temperature=float(value)), env
    if dimension == "score_cap":
        return replace(policy, score_cap=float(value)), env
    if dimension == "uncertainty_prior":
        return replace(policy, uncertainty_prior=float(value)), env
    if dimension == "exposure_penalty":
        return replace(policy, exposure_penalty=float(value)), env
    if dimension == "exposure_window":
        return replace(policy, exposure_window=int(value)), env
    if dimension == "candidate_count":
        return policy, replace(env, candidate_count=int(value))
    if dimension == "task_budget":
        return policy, replace(env, task_budget=int(value))
    if dimension == "trace_half_life":
        return policy, replace(env, trace_half_life_cycles=float(value))
    if dimension == "confidence_evidence":
        return policy, replace(env, confidence_evidence_weight=float(value))
    if dimension == "confidence_noise":
        return policy, replace(env, confidence_noise_weight=float(value))
    if dimension == "practice_gain":
        return policy, replace(env, practice_gain=float(value))
    if dimension == "shift_period":
        return policy, replace(env, shift_period=int(value))
    if dimension == "price_pressure":
        return policy, replace(env, price_floor=float(value))
    if dimension == "speed_pressure":
        return policy, replace(env, completion_span_seconds=int(value))
    if dimension == "evidence_noise":
        return policy, replace(env, evidence_noise=float(value))
    if dimension == "requester_skew":
        return policy, replace(env, requester_skew=float(value))
    raise ValueError(f"unsupported dimension: {dimension}")


def _dimension_values(
    policy: ReputationPolicy,
    env: IntegrationEnvironment,
    dimension: str,
) -> tuple[float | int, float | int]:
    if dimension == "reputation_weight":
        return max(0.15, policy.weight - 0.10), min(0.75, policy.weight + 0.10)
    if dimension == "freshness":
        current = policy.freshness_half_life_cycles or 24.0
        return max(3.0, current / 2), min(96.0, current * 2)
    if dimension == "blend_skill":
        return max(0.0, policy.blend_skill - 0.25), min(1.0, policy.blend_skill + 0.25)
    if dimension == "mass_gate":
        return max(0.0, policy.mass_gate - 1.0), min(8.0, policy.mass_gate + 2.0)
    if dimension == "positive_weight":
        return max(0.5, policy.positive_weight - 0.5), min(4.0, policy.positive_weight + 1.0)
    if dimension == "negative_weight":
        return max(0.5, policy.negative_weight - 0.25), min(3.0, policy.negative_weight + 0.5)
    if dimension == "shift_reset":
        return max(0.0, policy.shift_reset - 0.20), min(1.0, policy.shift_reset + 0.10)
    if dimension == "temperature":
        return max(0.5, policy.temperature - 0.25), min(2.0, policy.temperature + 0.25)
    if dimension == "score_cap":
        return max(0.08, policy.score_cap - 0.10), min(0.50, policy.score_cap + 0.10)
    if dimension == "uncertainty_prior":
        return max(0.0, policy.uncertainty_prior - 2.0), min(10.0, policy.uncertainty_prior + 3.0)
    if dimension == "exposure_penalty":
        return max(0.0, policy.exposure_penalty - 0.03), min(0.15, policy.exposure_penalty + 0.04)
    if dimension == "exposure_window":
        return max(6, policy.exposure_window // 2), min(96, policy.exposure_window * 2)
    if dimension == "candidate_count":
        return max(2, env.candidate_count - 1), min(env.agents - 1, env.candidate_count + 2)
    if dimension == "task_budget":
        return max(6, env.task_budget - 3), min(24, env.task_budget + 4)
    if dimension == "trace_half_life":
        return max(2.0, env.trace_half_life_cycles / 2), min(32.0, env.trace_half_life_cycles * 2)
    if dimension == "confidence_evidence":
        return max(0.05, env.confidence_evidence_weight - 0.15), min(0.70, env.confidence_evidence_weight + 0.15)
    if dimension == "confidence_noise":
        return max(0.05, env.confidence_noise_weight - 0.08), min(0.45, env.confidence_noise_weight + 0.10)
    if dimension == "practice_gain":
        return max(0.02, env.practice_gain - 0.03), min(0.20, env.practice_gain + 0.04)
    if dimension == "shift_period":
        step_down = max(1, env.shift_period // 3)
        step_up = max(1, env.shift_period // 2)
        return (
            max(1, env.shift_period - step_down),
            min(env.cycles - 1, env.shift_period + step_up),
        )
    if dimension == "price_pressure":
        return max(0.25, env.price_floor - 0.10), min(0.70, env.price_floor + 0.10)
    if dimension == "speed_pressure":
        return max(4, env.completion_span_seconds - 4), min(24, env.completion_span_seconds + 6)
    if dimension == "evidence_noise":
        return max(0.0, env.evidence_noise - 0.05), min(0.25, env.evidence_noise + 0.07)
    if dimension == "requester_skew":
        return max(0.0, env.requester_skew - 0.10), min(0.50, env.requester_skew + 0.15)
    raise ValueError(dimension)


def _adaptive_arms(
    policy: ReputationPolicy,
    env: IntegrationEnvironment,
    dimension: str,
) -> list[ArmSpec]:
    low, high = _dimension_values(policy, env, dimension)
    low_policy, low_env = _replace_dimension(policy, env, dimension, low)
    high_policy, high_env = _replace_dimension(policy, env, dimension, high)
    return [
        ArmSpec("no_reputation", ReputationPolicy(), env),
        ArmSpec("incumbent", policy, env),
        ArmSpec(f"{dimension}-low-{_arm_label_value(low)}", low_policy, low_env),
        ArmSpec(f"{dimension}-high-{_arm_label_value(high)}", high_policy, high_env),
    ]


def _question(dimension: str, failure: str) -> str:
    readable = dimension.replace("_", " ")
    return (
        f"Can tuning {readable} reduce the current {failure} failure while preserving "
        "quality, plasticity, ledger conservation, and immutable provenance?"
    )


def _stress_name(failure: str) -> str:
    return {
        "quality": "thin_market",
        "plasticity": "rapid_regime_shift",
        "concentration": "rapid_regime_shift",
        "calibration": "evidence_corruption",
        "economic": "credit_scarcity",
        "integrity": "integrity_replay",
        "structure": "trace_memory_collapse",
        "robustness": "mixed_shock",
    }.get(failure, "mixed_shock")


def _stress_environment(env: IntegrationEnvironment, stress: str) -> IntegrationEnvironment:
    if stress == "thin_market":
        return replace(env, candidate_count=max(2, env.candidate_count - 2), confidence_noise_weight=0.30)
    if stress == "rapid_regime_shift":
        return replace(env, shift_period=max(12, env.shift_period // 2))
    if stress == "evidence_corruption":
        return replace(env, evidence_noise=max(0.12, env.evidence_noise))
    if stress == "credit_scarcity":
        return replace(env, task_budget=min(24, env.task_budget + 5), initial_credits=max(300, env.initial_credits // 2))
    if stress == "integrity_replay":
        return replace(env, requester_skew=max(0.25, env.requester_skew))
    if stress == "trace_memory_collapse":
        return replace(env, trace_half_life_cycles=2.0)
    return replace(
        env,
        shift_period=max(12, env.shift_period // 2),
        candidate_count=max(3, env.candidate_count - 1),
        evidence_noise=max(0.08, env.evidence_noise),
        confidence_inflation=max(0.08, env.confidence_inflation),
    )


def _rescue_policies(policy: ReputationPolicy, failure: str) -> tuple[ReputationPolicy, ReputationPolicy]:
    if failure in {"plasticity", "concentration"}:
        return (
            replace(policy, shift_reset=1.0, freshness_half_life_cycles=max(4.0, (policy.freshness_half_life_cycles or 24) / 2)),
            replace(policy, exposure_penalty=max(0.05, policy.exposure_penalty)),
        )
    if failure == "calibration":
        return (
            replace(policy, uncertainty_prior=max(3.0, policy.uncertainty_prior), mass_gate=max(3.0, policy.mass_gate)),
            replace(policy, temperature=max(1.25, policy.temperature), score_cap=min(0.20, policy.score_cap)),
        )
    if failure == "economic":
        return (
            replace(policy, weight=max(0.25, policy.weight - 0.15)),
            replace(policy, exposure_penalty=max(0.04, policy.exposure_penalty)),
        )
    if failure == "quality":
        return (
            replace(policy, weight=max(0.25, policy.weight - 0.10), temperature=max(1.20, policy.temperature)),
            replace(policy, uncertainty_prior=max(2.0, policy.uncertainty_prior)),
        )
    return (
        replace(policy, freshness_half_life_cycles=min(72.0, (policy.freshness_half_life_cycles or 24) * 1.5)),
        replace(policy, score_cap=min(0.22, policy.score_cap), uncertainty_prior=max(2.0, policy.uncertainty_prior)),
    )


def _stress_arms(
    policy: ReputationPolicy,
    env: IntegrationEnvironment,
    *,
    stress: str,
    failure: str,
) -> list[ArmSpec]:
    stressed = _stress_environment(env, stress)
    rescue_a, rescue_b = _rescue_policies(policy, failure)
    return [
        ArmSpec("no_reputation", ReputationPolicy(), stressed),
        ArmSpec("incumbent", policy, stressed),
        ArmSpec("rescue-a", rescue_a, stressed),
        ArmSpec("rescue-b", rescue_b, stressed),
    ]


def _replication_name(failure: str) -> str:
    return {
        "quality": "confidence_inflation",
        "plasticity": "incumbent_pressure",
        "concentration": "incumbent_pressure",
        "calibration": "label_noise",
        "economic": "price_shading",
        "integrity": "replay_pressure",
        "structure": "mixed_replication",
        "robustness": "mixed_replication",
    }.get(failure, "mixed_replication")


def _replication_environment(env: IntegrationEnvironment, scenario: str) -> IntegrationEnvironment:
    if scenario == "confidence_inflation":
        return replace(env, confidence_inflation=max(0.15, env.confidence_inflation))
    if scenario == "incumbent_pressure":
        return replace(env, requester_skew=max(0.30, env.requester_skew), shift_period=max(12, env.shift_period // 2))
    if scenario == "label_noise":
        return replace(env, evidence_noise=max(0.18, env.evidence_noise))
    if scenario == "price_shading":
        return replace(env, price_floor=max(0.60, env.price_floor))
    if scenario == "replay_pressure":
        return replace(env, requester_skew=max(0.35, env.requester_skew), evidence_noise=max(0.05, env.evidence_noise))
    return replace(
        env,
        evidence_noise=max(0.10, env.evidence_noise),
        confidence_inflation=max(0.10, env.confidence_inflation),
        requester_skew=max(0.20, env.requester_skew),
    )


def _run_experiment(
    connection: Connection[Any],
    *,
    config: IntegrationCampaignConfig,
    config_hash: str,
    number: int,
    arms: Sequence[ArmSpec],
    seeds: Sequence[int],
    code_sha: str,
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for arm in arms:
        cells = [
            run_integration_arm(
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
        summaries.append(_aggregate_arm(cells))
    return _evaluate_arms(summaries, config=config)


def _record(
    *,
    number: int,
    focus: str,
    question: str,
    motivating_failure: str,
    observed_failure: str | None,
    arms: Sequence[Mapping[str, object]],
    selected: Mapping[str, object],
    next_focus: str | None,
    validated: bool | None = None,
) -> dict[str, object]:
    selected_metrics = selected["metrics"]
    assert isinstance(selected_metrics, Mapping)
    decision = (
        f"Selected {selected['label']}: success={float(selected_metrics['success_rate']):.4f}, "
        f"incumbent={float(selected_metrics['early_incumbent_share']):.4f}, "
        f"MI={float(selected_metrics['agent_domain_mutual_information']):.4f}, "
        f"Brier={float(selected_metrics['reputation_brier_score']):.4f}."
    )
    if observed_failure is not None:
        decision += f" Dominant remaining failure mode: {observed_failure}."
    result: dict[str, object] = {
        "number": number,
        "focus": focus,
        "question": question,
        "motivating_failure": motivating_failure,
        "observed_failure": observed_failure,
        "selected_label": selected["label"],
        "selected_policy": selected["policy"],
        "selected_environment": selected["environment"],
        "arms": list(arms),
        "decision": decision,
        "next_experiment_focus": next_focus,
    }
    if validated is not None:
        result["validated"] = validated
    return result


def run_integration_campaign(
    connection: Connection[Any],
    *,
    config: IntegrationCampaignConfig,
    config_hash: str,
    code_sha: str,
    output_dir: str | Path,
) -> dict[str, object]:
    current_policy = validated_policy()
    current_env = config.environment
    experiments: list[dict[str, object]] = []

    arms_14 = [
        ArmSpec("no_reputation", ReputationPolicy(), current_env),
        ArmSpec("raw_persistent", raw_policy(), current_env),
        ArmSpec("validated_013", current_policy, current_env),
    ]
    evaluated, selected, control = _run_experiment(
        connection,
        config=config,
        config_hash=config_hash,
        number=14,
        arms=arms_14,
        seeds=config.seeds,
        code_sha=code_sha,
    )
    failure = _failure_mode(selected, control, config)
    if selected["label"] != "no_reputation":
        current_policy = ReputationPolicy(**selected["policy"])  # type: ignore[arg-type]
        current_env = IntegrationEnvironment(
            **{
                **selected["environment"],  # type: ignore[arg-type]
                "domains": tuple(selected["environment"]["domains"]),  # type: ignore[index]
            }
        )
    tested: set[str] = set()
    dimension = _choose_dimension(failure, tested)
    experiments.append(
        _record(
            number=14,
            focus="integration_bridge",
            question=(
                "Can the Experiment 013 policy preserve its advantage inside the real PostgreSQL "
                "sealed-bid market with escrow, settlement, persistent evidence, and score provenance?"
            ),
            motivating_failure="integration",
            observed_failure=failure,
            arms=evaluated,
            selected=selected,
            next_focus=dimension,
        )
    )

    for number in range(15, 38):
        motivating = failure
        arms = _adaptive_arms(current_policy, current_env, dimension)
        evaluated, selected, control = _run_experiment(
            connection,
            config=config,
            config_hash=config_hash,
            number=number,
            arms=arms,
            seeds=config.seeds,
            code_sha=code_sha,
        )
        failure = _failure_mode(selected, control, config)
        if selected["label"] != "no_reputation":
            current_policy = ReputationPolicy(**selected["policy"])  # type: ignore[arg-type]
            env_data = dict(selected["environment"])  # type: ignore[arg-type]
            env_data["domains"] = tuple(env_data["domains"])
            current_env = IntegrationEnvironment(**env_data)
        tested.add(dimension)
        next_focus: str
        if number == 37:
            next_focus = f"stress:{_stress_name(failure)}"
        else:
            next_focus = _choose_dimension(failure, tested)
        experiments.append(
            _record(
                number=number,
                focus=dimension,
                question=_question(dimension, motivating),
                motivating_failure=motivating,
                observed_failure=failure,
                arms=evaluated,
                selected=selected,
                next_focus=next_focus,
            )
        )
        if number < 37:
            dimension = next_focus

    stress = _stress_name(failure)
    motivating = failure
    evaluated, selected, control = _run_experiment(
        connection,
        config=config,
        config_hash=config_hash,
        number=38,
        arms=_stress_arms(
            current_policy,
            current_env,
            stress=stress,
            failure=motivating,
        ),
        seeds=config.seeds,
        code_sha=code_sha,
    )
    failure = _failure_mode(selected, control, config)
    if selected["label"] != "no_reputation":
        current_policy = ReputationPolicy(**selected["policy"])  # type: ignore[arg-type]
        env_data = dict(selected["environment"])  # type: ignore[arg-type]
        env_data["domains"] = tuple(env_data["domains"])
        current_env = IntegrationEnvironment(**env_data)
    replication = _replication_name(failure)
    experiments.append(
        _record(
            number=38,
            focus=stress,
            question=f"Does the selected policy survive the adaptively chosen {stress} stressor?",
            motivating_failure=motivating,
            observed_failure=failure,
            arms=evaluated,
            selected=selected,
            next_focus=f"replication:{replication}",
        )
    )

    motivating = failure
    replication_env = _replication_environment(current_env, replication)
    rescue_a, rescue_b = _rescue_policies(current_policy, motivating)
    evaluated, selected, control = _run_experiment(
        connection,
        config=config,
        config_hash=config_hash,
        number=39,
        arms=[
            ArmSpec("no_reputation", ReputationPolicy(), replication_env),
            ArmSpec("incumbent", current_policy, replication_env),
            ArmSpec("defense-a", rescue_a, replication_env),
            ArmSpec("defense-b", rescue_b, replication_env),
        ],
        seeds=config.seeds,
        code_sha=code_sha,
    )
    failure = _failure_mode(selected, control, config)
    if selected["label"] != "no_reputation":
        current_policy = ReputationPolicy(**selected["policy"])  # type: ignore[arg-type]
        env_data = dict(selected["environment"])  # type: ignore[arg-type]
        env_data["domains"] = tuple(env_data["domains"])
        current_env = IntegrationEnvironment(**env_data)
    holdout_shock = _stress_name(failure)
    experiments.append(
        _record(
            number=39,
            focus=replication,
            question=(
                f"Can the policy replicate under the adaptively chosen {replication} scenario "
                "without violating economic or provenance invariants?"
            ),
            motivating_failure=motivating,
            observed_failure=failure,
            arms=evaluated,
            selected=selected,
            next_focus=f"holdout:{holdout_shock}",
        )
    )

    holdout_base = replace(
        config.environment,
        cycles=config.holdout_cycles,
        shift_period=config.holdout_shift_period,
        candidate_count=config.holdout_candidate_count,
    )
    holdout_env = _stress_environment(holdout_base, holdout_shock)
    evaluated, selected, control = _run_experiment(
        connection,
        config=config,
        config_hash=config_hash,
        number=40,
        arms=[
            ArmSpec("no_reputation", ReputationPolicy(), holdout_env),
            ArmSpec("raw_persistent", raw_policy(), holdout_env),
            ArmSpec("final_policy", current_policy, holdout_env),
        ],
        seeds=config.holdout_seeds,
        code_sha=code_sha,
    )
    final_arm = next(arm for arm in evaluated if arm["label"] == "final_policy")
    final_metrics = final_arm["metrics"]
    control_metrics = control["metrics"]
    assert isinstance(final_metrics, Mapping) and isinstance(control_metrics, Mapping)
    validated = (
        bool(final_arm["feasible"])
        and float(final_arm["utility"]) >= float(control["utility"]) - 0.005
        and float(final_metrics["success_rate"])
        >= float(control_metrics["success_rate"]) - config.success_tolerance
    )
    observed = None if validated else _failure_mode(final_arm, control, config)
    experiments.append(
        _record(
            number=40,
            focus=f"holdout:{holdout_shock}",
            question=(
                "Does the policy selected by Experiments 014–039 generalize to unseen seeds "
                "inside the real PostgreSQL market under the independently selected holdout shock?"
            ),
            motivating_failure=failure,
            observed_failure=observed,
            arms=evaluated,
            selected=final_arm,
            next_focus=None,
            validated=validated,
        )
    )

    summary = {
        "campaign": config.name,
        "code_sha": code_sha,
        "config_hash": config_hash,
        "experiments": experiments,
        "final_policy": current_policy.as_dict(),
        "final_label": current_policy.label,
        "holdout_shock": holdout_shock,
        "validated": validated,
    }
    export_integration_campaign_artifacts(
        connection,
        config=config,
        output_dir=output_dir,
        summary=summary,
    )
    return summary


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
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else str(value)
                    if isinstance(value, (UUID, datetime))
                    else value
                    for key, value in row.items()
                }
            )


def export_integration_campaign_artifacts(
    connection: Connection[Any],
    *,
    config: IntegrationCampaignConfig,
    output_dir: str | Path,
    summary: Mapping[str, object],
) -> None:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "campaign.json").write_text(
        json.dumps(dict(summary), indent=2, sort_keys=True) + "\n"
    )
    experiments = summary["experiments"]
    assert isinstance(experiments, Sequence)
    arm_rows: list[dict[str, object]] = []
    for experiment in experiments:
        assert isinstance(experiment, Mapping)
        number = int(experiment["number"])
        (destination / f"experiment-{number:03d}.json").write_text(
            json.dumps(dict(experiment), indent=2, sort_keys=True) + "\n"
        )
        for arm in experiment["arms"]:  # type: ignore[index]
            arm_rows.append(
                {
                    "experiment_number": number,
                    "focus": experiment["focus"],
                    "motivating_failure": experiment["motivating_failure"],
                    "observed_failure": experiment["observed_failure"],
                    "selected": arm["label"] == experiment["selected_label"],
                    "label": arm["label"],
                    "feasible": arm["feasible"],
                    "utility": arm["utility"],
                    **arm["metrics"],
                }
            )
    _write_csv(destination / "experiment-arms.csv", arm_rows)

    queries = {
        "runs.csv": """
            SELECT * FROM integration_campaign_runs
            WHERE campaign_name = %s
            ORDER BY experiment_number, arm_label, seed
        """,
        "outcomes.csv": """
            SELECT o.*
            FROM integration_campaign_outcomes o
            JOIN integration_campaign_runs r ON r.run_id = o.run_id
            WHERE r.campaign_name = %s
            ORDER BY r.experiment_number, r.arm_label, r.seed, o.cycle
        """,
        "auction_scores.csv": """
            SELECT r.experiment_number, r.arm_label, r.seed, s.*
            FROM market_auction_scores s
            JOIN integration_campaign_outcomes o ON o.task_id = s.task_id
            JOIN integration_campaign_runs r ON r.run_id = o.run_id
            WHERE r.campaign_name = %s
            ORDER BY r.experiment_number, r.arm_label, r.seed, s.task_id, s.total_score DESC
        """,
        "reputation_evidence.csv": """
            SELECT r.experiment_number, r.arm_label, r.seed, e.*
            FROM reputation_evidence e
            JOIN integration_campaign_outcomes o ON o.task_id = e.source_id
            JOIN integration_campaign_runs r ON r.run_id = o.run_id
            WHERE r.campaign_name = %s
            ORDER BY r.experiment_number, r.arm_label, r.seed, e.created_at
        """,
        "compute_transactions.csv": """
            SELECT DISTINCT r.experiment_number, r.arm_label, r.seed, t.*
            FROM compute_transactions t
            JOIN integration_campaign_outcomes o ON o.task_id = t.reference_id
            JOIN integration_campaign_runs r ON r.run_id = o.run_id
            WHERE r.campaign_name = %s
            ORDER BY r.experiment_number, r.arm_label, r.seed, t.created_at
        """,
    }
    for filename, query in queries.items():
        rows = connection.execute(query, (config.name,)).fetchall()
        _write_csv(destination / filename, [dict(row) for row in rows])


def load_integration_campaign_config(
    path: str | Path,
) -> tuple[IntegrationCampaignConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    config = IntegrationCampaignConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()
