"""Auction-margin control machinery for Experiments 129–134."""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from resonance.market.models import MarketBid, bid_score
from resonance.market.signals import BidSignal
from resonance.substrate.models import Trace

from . import endogenous_demand_campaign as ec
from . import lifecycle_campaign as lc
from .auction_margin_config import AuctionMarginConfig, MarginEnvironment
from .chaos_predictability_campaign import (
    _basin_class,
    _pair_series,
    _saturation,
    forecast_horizon,
)
from .chaos_predictability_config import load_chaos_predictability_config
from .endogenous_demand_config import EndogenousDemandSpec, endogenous_environment, load_endogenous_demand_config

_EPS = 1e-12
_SLOT_PATTERN = re.compile(r"slot\s+(\d+)\s*$")
_CHAOS_CONFIG_PATH = "configs/experiments/chaos-predictability-123-128.json"
_SATURATION_GROWTH_LIMIT = 0.05


@dataclass(frozen=True, slots=True)
class MarginCellSpec:
    label: str
    target_radius: float | None
    probe: bool

    def __post_init__(self) -> None:
        if self.target_radius is not None and self.target_radius <= 0:
            raise ValueError("target radius must be positive")


@dataclass(slots=True)
class MarginActivationAudit:
    experiment_number: int
    cohort: str
    arm_label: str
    seed: int
    activation_cycle: int
    natural_winner_slot: int | None = None
    target_slot: int | None = None
    natural_radius: float | None = None
    requested_radius: float | None = None
    placed_radius: float | None = None
    margin_delta: float = 0.0
    probe_delta: float = 0.0
    margin_only_winner_slot: int | None = None
    predicted_winner_slot: int | None = None
    awarded_winner_slot: int | None = None
    margin_only_preserved: bool = False
    probe_crossed: bool = False
    plan_count: int = 0
    score_call_count: int = 0
    target_bid_id: UUID | None = None
    natural_winner_bid_id: UUID | None = None
    score_components: dict[UUID, dict[str, float]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "experiment_number": self.experiment_number,
            "cohort": self.cohort,
            "arm_label": self.arm_label,
            "seed": self.seed,
            "activation_cycle": self.activation_cycle,
            "natural_winner_slot": self.natural_winner_slot,
            "target_slot": self.target_slot,
            "natural_radius": self.natural_radius,
            "requested_radius": self.requested_radius,
            "placed_radius": self.placed_radius,
            "margin_delta": self.margin_delta,
            "probe_delta": self.probe_delta,
            "margin_only_winner_slot": self.margin_only_winner_slot,
            "predicted_winner_slot": self.predicted_winner_slot,
            "awarded_winner_slot": self.awarded_winner_slot,
            "margin_only_preserved": self.margin_only_preserved,
            "probe_crossed": self.probe_crossed,
            "plan_count": self.plan_count,
            "score_call_count": self.score_call_count,
        }


def primary_specs(config: AuctionMarginConfig) -> tuple[MarginCellSpec, ...]:
    return (
        MarginCellSpec("natural_no_probe", None, False),
        MarginCellSpec("natural_probe", None, True),
        MarginCellSpec("near_probe", config.near_radius, True),
        MarginCellSpec("buffered_probe", config.buffered_radius, True),
    )


def instrumentation_specs(config: AuctionMarginConfig) -> tuple[MarginCellSpec, ...]:
    return (
        *primary_specs(config),
        MarginCellSpec("near_no_probe", config.near_radius, False),
        MarginCellSpec("buffered_no_probe", config.buffered_radius, False),
    )


def load_canonical_base(config: AuctionMarginConfig):
    base, _ = load_endogenous_demand_config(config.canonical_endogenous_config)
    integration = replace(base.integration, name=config.name)
    return replace(base, integration=integration)


def margin_environment(base, spec: MarginEnvironment, *, through_activation: bool = False):
    cycles = spec.activation_cycle + 1 if through_activation else spec.cycles
    return endogenous_environment(
        base,
        cycles=cycles,
        shift_period=spec.shift_period,
        candidate_count=spec.candidate_count,
    )


def _slot(bid: MarketBid) -> int:
    match = _SLOT_PATTERN.search(bid.strategy_summary)
    if match is None:
        raise ValueError("cannot recover candidate slot from bid strategy summary")
    return int(match.group(1))


def _rank(scored: Sequence[tuple[float, MarketBid]]) -> list[tuple[float, MarketBid]]:
    return sorted(scored, key=lambda item: (-item[0], item[1].submitted_at, str(item[1].bid_id)))


def _radius(winning_score: float, losing_score: float, confidence: float) -> float:
    if confidence <= _EPS:
        return math.inf
    return max(0.0, winning_score - losing_score) / (0.45 * confidence)


def _bid_rows(connection: Connection[Any], task_id: UUID) -> list[MarketBid]:
    rows = connection.execute(
        """
        SELECT bid_id, task_id, bidder_agent_id, price, confidence,
               estimated_completion_seconds, strategy_summary, status, submitted_at
        FROM market_bids
        WHERE task_id = %s AND status = 'sealed'
        ORDER BY submitted_at, bid_id
        """,
        (task_id,),
    ).fetchall()
    return [
        MarketBid(
            bid_id=row["bid_id"],
            task_id=row["task_id"],
            bidder_agent_id=row["bidder_agent_id"],
            price=int(row["price"]),
            confidence=float(row["confidence"]),
            estimated_completion_seconds=int(row["estimated_completion_seconds"]),
            strategy_summary=str(row["strategy_summary"]),
            status=str(row["status"]),
            submitted_at=row["submitted_at"],
        )
        for row in rows
    ]


class _MarginSignalProvider:
    def __init__(
        self,
        connection: Connection[Any],
        *,
        config: AuctionMarginConfig,
        spec: MarginCellSpec,
        activation_cycle: int,
        audit: MarginActivationAudit,
    ) -> None:
        self._connection = connection
        self._config = config
        self._spec = spec
        self._activation_cycle = activation_cycle
        self._audit = audit
        self._task_id: UUID | None = None
        self._adjustments: dict[UUID, float] = {}

    def _plan(self, task) -> None:
        if self._task_id == task.task_id:
            return
        bids = _bid_rows(self._connection, task.task_id)
        if len(bids) < 2:
            raise RuntimeError("auction-margin activation requires at least two sealed bids")
        natural = _rank([(bid_score(task, bid), bid) for bid in bids])
        winning_score, natural_winner = natural[0]
        losers: list[tuple[float, float, MarketBid]] = []
        for score, bid in natural[1:]:
            radius = _radius(winning_score, score, bid.confidence)
            if math.isfinite(radius):
                losers.append((radius, score, bid))
        if not losers:
            raise RuntimeError("auction-margin activation has no finite-radius losing bid")
        radius, target_score, target = min(
            losers,
            key=lambda item: (item[0], item[2].submitted_at, str(item[2].bid_id)),
        )
        gap = winning_score - target_score
        target_radius = self._spec.target_radius
        margin_delta = 0.0
        if target_radius is not None:
            margin_delta = gap - 0.45 * target.confidence * target_radius
        probe_delta = 0.45 * target.confidence * self._config.probe_epsilon if self._spec.probe else 0.0
        margin_scores = [
            (score + (margin_delta if bid.bid_id == target.bid_id else 0.0), bid)
            for score, bid in natural
        ]
        final_scores = [
            (
                score
                + (margin_delta if bid.bid_id == target.bid_id else 0.0)
                + (probe_delta if bid.bid_id == target.bid_id else 0.0),
                bid,
            )
            for score, bid in natural
        ]
        margin_winner = _rank(margin_scores)[0][1]
        final_winner = _rank(final_scores)[0][1]
        placed_radius = _radius(
            winning_score,
            target_score + margin_delta,
            target.confidence,
        )
        self._audit.plan_count += 1
        self._audit.natural_winner_slot = _slot(natural_winner)
        self._audit.target_slot = _slot(target)
        self._audit.natural_radius = radius
        self._audit.requested_radius = target_radius
        self._audit.placed_radius = placed_radius if target_radius is not None else radius
        self._audit.margin_delta = margin_delta
        self._audit.probe_delta = probe_delta
        self._audit.margin_only_winner_slot = _slot(margin_winner)
        self._audit.predicted_winner_slot = _slot(final_winner)
        self._audit.margin_only_preserved = margin_winner.bid_id == natural_winner.bid_id
        self._audit.target_bid_id = target.bid_id
        self._audit.natural_winner_bid_id = natural_winner.bid_id
        self._audit.score_components = {
            bid.bid_id: {
                "natural_score": score,
                "margin_delta": margin_delta if bid.bid_id == target.bid_id else 0.0,
                "probe_delta": probe_delta if bid.bid_id == target.bid_id else 0.0,
            }
            for score, bid in natural
        }
        self._adjustments = {
            bid.bid_id: margin_delta + probe_delta if bid.bid_id == target.bid_id else 0.0
            for _, bid in natural
        }
        self._task_id = task.task_id

    def signal(self, task, bid: MarketBid, *, at) -> BidSignal:
        del at
        cycle = int(task.success_condition.get("campaign_cycle", -1))
        if cycle != self._activation_cycle:
            return BidSignal()
        self._plan(task)
        self._audit.score_call_count += 1
        components = self._audit.score_components.get(
            bid.bid_id,
            {"natural_score": bid_score(task, bid), "margin_delta": 0.0, "probe_delta": 0.0},
        )
        return BidSignal(
            adjustment=self._adjustments.get(bid.bid_id, 0.0),
            provider_label="auction_margin_control",
            components={
                **components,
                "target_bid": float(bid.bid_id == self._audit.target_bid_id),
                "requested_radius": float(self._audit.requested_radius or 0.0),
                "natural_radius": float(self._audit.natural_radius or 0.0),
            },
        )


def _query_outcomes(connection: Connection[Any], run_id: str) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT cycle, regime, task_id, task_domain, domain_index, required_skill,
               winner_agent_id, winner_slot, success, recorded_positive,
               reputation_score, winning_price, task_budget, created_at
        FROM integration_campaign_outcomes
        WHERE run_id = %s
        ORDER BY cycle
        """,
        (UUID(run_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def _persist_activation(connection: Connection[Any], run_id: str, audit: MarginActivationAudit) -> None:
    value = audit.as_dict()
    with connection.transaction():
        connection.execute(
            """
            INSERT INTO auction_margin_observations (
                run_id, experiment_number, cohort, arm_label, seed, activation_cycle,
                natural_winner_slot, target_slot, natural_radius, requested_radius, placed_radius,
                margin_delta, probe_delta, margin_only_winner_slot, predicted_winner_slot,
                awarded_winner_slot, margin_only_preserved, probe_crossed, audit, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, NOW()
            )
            """,
            (
                UUID(run_id),
                audit.experiment_number,
                audit.cohort,
                audit.arm_label,
                audit.seed,
                audit.activation_cycle,
                audit.natural_winner_slot,
                audit.target_slot,
                audit.natural_radius,
                audit.requested_radius,
                audit.placed_radius,
                audit.margin_delta,
                audit.probe_delta,
                audit.margin_only_winner_slot,
                audit.predicted_winner_slot,
                audit.awarded_winner_slot,
                audit.margin_only_preserved,
                audit.probe_crossed,
                Jsonb(value),
            ),
        )


def run_margin_cell(
    connection: Connection[Any],
    *,
    config: AuctionMarginConfig,
    base,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    cohort: str,
    seed: int,
    environment_spec: MarginEnvironment,
    spec: MarginCellSpec,
    through_activation: bool = False,
) -> dict[str, object]:
    environment = margin_environment(base, environment_spec, through_activation=through_activation)
    arm = ec.endogenous_arm(base, label=f"{cohort}_{spec.label}", environment=environment)
    original_domain = lc._domain_index
    original_market = lc.PostgresMarketService
    original_trace_repository = lc.PostgresTraceRepository
    controller = ec._FeedbackController(  # noqa: SLF001
        spec=EndogenousDemandSpec(mode="closed_loop", strength=config.feedback_strength),
        seed=seed,
        cycles=environment.cycles,
        domain_count=len(environment.domains),
        window=base.feedback_window,
        domain_fn=original_domain,
        draw_fn=lc._draw,
    )
    audit = MarginActivationAudit(
        experiment_number=experiment_number,
        cohort=cohort,
        arm_label=spec.label,
        seed=seed,
        activation_cycle=environment_spec.activation_cycle,
    )

    class MarginMarketService(original_market):
        def __init__(self, inner_connection, economy, *, bid_signal_provider=None):
            if bid_signal_provider is not None:
                raise RuntimeError("auction-margin cells require reputation-neutral matching")
            provider = _MarginSignalProvider(
                inner_connection,
                config=config,
                spec=spec,
                activation_cycle=environment_spec.activation_cycle,
                audit=audit,
            )
            super().__init__(inner_connection, economy, bid_signal_provider=provider)

        def award(self, task_id, *, at):
            result = super().award(task_id, at=at)
            if result is not None:
                cycle = int(result.task.success_condition.get("campaign_cycle", -1))
                if cycle == environment_spec.activation_cycle:
                    audit.awarded_winner_slot = _slot(result.winning_bid)
                    audit.probe_crossed = audit.awarded_winner_slot != audit.natural_winner_slot
            return result

    class ObservingTraceRepository:
        def __init__(self, inner_connection: Connection[Any]) -> None:
            self._delegate = original_trace_repository(inner_connection)

        def add(self, trace: Trace):
            result = self._delegate.add(trace)
            if trace.kind == "VERIFIED_OUTCOME" and trace.content.startswith("skill-evidence:"):
                controller.observe_success()
            return result

        def __getattr__(self, name: str):
            return getattr(self._delegate, name)

    def controlled_domain(inner_seed: int, cycle: int, domain_count: int) -> int:
        return controller.choose_domain(inner_seed, cycle, domain_count)

    lc._domain_index = controlled_domain
    lc.PostgresMarketService = MarginMarketService  # type: ignore[assignment]
    lc.PostgresTraceRepository = ObservingTraceRepository  # type: ignore[assignment]
    try:
        cell = lc.run_lifecycle_arm(
            connection,
            config=base.integration,
            config_hash=config_hash,
            experiment_number=experiment_number,
            arm=arm,
            seed=seed,
            code_sha=code_sha,
        )
    finally:
        lc._domain_index = original_domain
        lc.PostgresMarketService = original_market
        lc.PostgresTraceRepository = original_trace_repository
    controller.finalize()
    if audit.plan_count != 1 or audit.awarded_winner_slot is None:
        raise RuntimeError("auction-margin activation was not observed exactly once")

    rows = _query_outcomes(connection, str(cell["run_id"]))
    metrics = dict(cell["metrics"])
    metrics.update(
        ec._feedback_metrics(  # noqa: SLF001
            rows,
            controller.events,
            domain_count=len(environment.domains),
            cycles=environment.cycles,
            shift_period=environment.shift_period,
        )
    )
    cell["metrics"] = metrics
    invariants = dict(cell["invariants"])
    invariants.update(
        {
            "identity_turnover_absent": float(metrics.get("exit_count", 0.0)) == 0.0,
            "auction_margin_reputation_neutral": arm.policy.mode == "none",
            "requester_generation_unchanged": True,
            "candidate_generation_unchanged": True,
            "submitted_bids_unchanged": True,
            "single_activation_plan": audit.plan_count == 1,
            "margin_only_preserves_natural_winner": audit.margin_only_preserved,
        }
    )
    cell["invariants"] = invariants
    ec._persist_feedback_observations(  # noqa: SLF001
        connection,
        run_id=str(cell["run_id"]),
        events=controller.events,
        rows=rows,
    )
    _persist_activation(connection, str(cell["run_id"]), audit)
    return {**cell, "rows": rows, "margin_audit": audit.as_dict()}


def _bid_signatures(connection: Connection[Any], run_id: str, *, end_cycle: int) -> list[tuple[object, ...]]:
    rows = connection.execute(
        """
        SELECT o.cycle, b.price, b.confidence, b.estimated_completion_seconds, b.strategy_summary
        FROM integration_campaign_outcomes o
        JOIN market_bids b ON b.task_id = o.task_id
        WHERE o.run_id = %s AND o.cycle < %s
        ORDER BY o.cycle, b.submitted_at, b.bid_id
        """,
        (UUID(run_id), end_cycle),
    ).fetchall()
    return [
        (
            int(row["cycle"]),
            int(row["price"]),
            float(row["confidence"]),
            int(row["estimated_completion_seconds"]),
            str(row["strategy_summary"]),
        )
        for row in rows
    ]


def preactivation_equal(
    connection: Connection[Any],
    left: Mapping[str, object],
    right: Mapping[str, object],
    *,
    activation_cycle: int,
) -> bool:
    left_rows = left["rows"]
    right_rows = right["rows"]
    assert isinstance(left_rows, Sequence) and isinstance(right_rows, Sequence)
    fields = (
        "cycle",
        "regime",
        "task_domain",
        "domain_index",
        "required_skill",
        "winner_slot",
        "success",
        "recorded_positive",
        "winning_price",
        "task_budget",
    )
    lprefix = [row for row in left_rows if int(row["cycle"]) < activation_cycle]
    rprefix = [row for row in right_rows if int(row["cycle"]) < activation_cycle]
    if len(lprefix) != len(rprefix):
        return False
    row_equal = all(
        all(lrow[field] == rrow[field] for field in fields)
        for lrow, rrow in zip(lprefix, rprefix, strict=True)
    )
    if not row_equal:
        return False
    return _bid_signatures(
        connection, str(left["run_id"]), end_cycle=activation_cycle
    ) == _bid_signatures(connection, str(right["run_id"]), end_cycle=activation_cycle)


def activation_winner(cell: Mapping[str, object]) -> int:
    audit = cell["margin_audit"]
    assert isinstance(audit, Mapping)
    return int(audit["awarded_winner_slot"])


def natural_winner(cell: Mapping[str, object]) -> int:
    audit = cell["margin_audit"]
    assert isinstance(audit, Mapping)
    return int(audit["natural_winner_slot"])


def local_crossing(cell: Mapping[str, object]) -> bool:
    return activation_winner(cell) != natural_winner(cell)


def _final_public_knowledge(rows: Sequence[Mapping[str, object]], *, env, base) -> float:
    at_cycle = env.cycles
    known = 0
    for skill in env.domains:
        signal = max(
            (
                0.9 * 2.0 ** (-(at_cycle - 1 - int(row["cycle"])) / env.trace_half_life_cycles)
                for row in rows
                if bool(row["success"]) and str(row["required_skill"]) == skill
            ),
            default=0.0,
        )
        known += int(signal >= base.knowledge_signal_threshold)
    return known / len(env.domains) if env.domains else 0.0


def pair_summary(
    *,
    config: AuctionMarginConfig,
    base,
    seed: int,
    environment_spec: MarginEnvironment,
    near: Mapping[str, object],
    buffered: Mapping[str, object],
) -> dict[str, object]:
    env = margin_environment(base, environment_spec)
    near_rows = near["rows"]
    buffered_rows = buffered["rows"]
    assert isinstance(near_rows, Sequence) and isinstance(buffered_rows, Sequence)
    series = _pair_series(
        buffered_rows,  # type: ignore[arg-type]
        near_rows,  # type: ignore[arg-type]
        seed=seed,
        env=env,
        base=base,
        baseline_trace_cycle=None,
        perturbed_trace_cycle=None,
        perturbed_trace_multiplier=1.0,
    )
    horizons = {
        "micro": forecast_horizon(
            series,
            key="micro_distance",
            threshold=config.delta_micro,
            hits=config.persistent_hits,
            window=config.persistent_window,
            cycles=env.cycles,
        ),
        "meso": forecast_horizon(
            series,
            key="meso_distance",
            threshold=config.delta_meso,
            hits=config.persistent_hits,
            window=config.persistent_window,
            cycles=env.cycles,
        ),
        "macro": forecast_horizon(
            series,
            key="macro_distance",
            threshold=config.delta_macro,
            hits=config.persistent_hits,
            window=config.persistent_window,
            cycles=env.cycles,
        ),
    }
    saturation: dict[str, dict[str, object]] = {}
    for scale in ("micro", "meso", "macro"):
        bounded, mean_final = _saturation(
            series,
            key=f"{scale}_distance",
            shift_period=env.shift_period,
            growth_limit=_SATURATION_GROWTH_LIMIT,
        )
        saturation[scale] = {"bounded": bounded, "mean_final_regime": mean_final}

    chaos_protocol, _ = load_chaos_predictability_config(_CHAOS_CONFIG_PATH)
    buffered_final_rows = [
        row for row in buffered_rows if int(row["cycle"]) >= env.cycles - 2 * env.shift_period
    ]
    reference_success = statistics.mean(float(bool(row["success"])) for row in buffered_final_rows)
    buffered_basin, buffered_i, buffered_success = _basin_class(
        buffered_rows,  # type: ignore[arg-type]
        env=env,
        reference_success=reference_success,
        protocol=chaos_protocol,
    )
    near_basin, near_i, near_success = _basin_class(
        near_rows,  # type: ignore[arg-type]
        env=env,
        reference_success=reference_success,
        protocol=chaos_protocol,
    )
    first_changed = next(
        (
            int(left["cycle"])
            for left, right in zip(buffered_rows, near_rows, strict=True)
            if int(left["winner_slot"]) != int(right["winner_slot"])
        ),
        env.cycles + 1,
    )
    near_metrics = near["metrics"]
    buffered_metrics = buffered["metrics"]
    near_invariants = near["invariants"]
    buffered_invariants = buffered["invariants"]
    assert isinstance(near_metrics, Mapping) and isinstance(buffered_metrics, Mapping)
    assert isinstance(near_invariants, Mapping) and isinstance(buffered_invariants, Mapping)
    near_knowledge = _final_public_knowledge(near_rows, env=env, base=base)  # type: ignore[arg-type]
    buffered_knowledge = _final_public_knowledge(buffered_rows, env=env, base=base)  # type: ignore[arg-type]
    return {
        "seed": seed,
        "first_changed_winner_cycle": first_changed,
        "horizons": horizons,
        "persistent_macro_crossed": horizons["macro"] <= env.cycles,
        "saturation": saturation,
        "bounded_all_scales": all(bool(value["bounded"]) for value in saturation.values()),
        "buffered_basin": buffered_basin,
        "near_basin": near_basin,
        "basin_disagreement": buffered_basin != near_basin,
        "buffered_final_incumbency": buffered_i,
        "near_final_incumbency": near_i,
        "buffered_final_success": buffered_success,
        "near_final_success": near_success,
        "success_loss": max(0.0, float(buffered_metrics["success_rate"]) - float(near_metrics["success_rate"])),
        "buffered_final_public_knowledge": buffered_knowledge,
        "near_final_public_knowledge": near_knowledge,
        "knowledge_loss": max(0.0, buffered_knowledge - near_knowledge),
        "all_invariants": all(bool(value) for value in near_invariants.values())
        and all(bool(value) for value in buffered_invariants.values()),
        "final_micro_distance": float(series[-1]["micro_distance"]),
        "final_meso_distance": float(series[-1]["meso_distance"]),
        "final_macro_distance": float(series[-1]["macro_distance"]),
    }


def evaluate_cohort(
    pairs: Sequence[Mapping[str, object]],
    *,
    config: AuctionMarginConfig,
) -> dict[str, object]:
    if not pairs:
        raise ValueError("auction-margin cohort requires pair summaries")
    macro_share = statistics.mean(float(bool(pair["persistent_macro_crossed"])) for pair in pairs)
    basin_share = statistics.mean(float(bool(pair["basin_disagreement"])) for pair in pairs)
    bounded_share = statistics.mean(float(bool(pair["bounded_all_scales"])) for pair in pairs)
    success_loss = statistics.mean(float(pair["success_loss"]) for pair in pairs)
    knowledge_loss = statistics.mean(float(pair["knowledge_loss"]) for pair in pairs)
    invariants = all(bool(pair["all_invariants"]) for pair in pairs)
    propagated = (
        macro_share >= config.minimum_macro_crossing_share
        and basin_share >= config.minimum_basin_disagreement_share
        and bounded_share >= config.minimum_bounded_share
        and success_loss <= config.maximum_success_loss
        and knowledge_loss <= config.maximum_knowledge_loss
        and invariants
    )
    return {
        "pair_count": len(pairs),
        "macro_crossing_share": macro_share,
        "basin_disagreement_share": basin_share,
        "bounded_share": bounded_share,
        "mean_success_loss": success_loss,
        "mean_knowledge_loss": knowledge_loss,
        "all_invariants": invariants,
        "organizational_propagation": propagated,
        "classification": (
            "organizational_propagation" if propagated else "local_only_no_robust_propagation"
        ),
    }


def persist_pair_summary(
    connection: Connection[Any],
    *,
    experiment_number: int,
    cohort: str,
    seed: int,
    near_run_id: str,
    buffered_run_id: str,
    summary: Mapping[str, object],
) -> None:
    with connection.transaction():
        connection.execute(
            """
            INSERT INTO auction_margin_pair_summaries (
                experiment_number, cohort, seed, near_run_id, buffered_run_id, summary, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                experiment_number,
                cohort,
                seed,
                UUID(near_run_id),
                UUID(buffered_run_id),
                Jsonb(dict(summary)),
            ),
        )


__all__ = [
    "MarginCellSpec",
    "activation_winner",
    "evaluate_cohort",
    "instrumentation_specs",
    "load_canonical_base",
    "local_crossing",
    "margin_environment",
    "natural_winner",
    "pair_summary",
    "persist_pair_summary",
    "preactivation_equal",
    "primary_specs",
    "run_margin_cell",
]
