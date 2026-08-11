"""Coordination-topology machinery for Experiments 087–092.

The intervention changes only which immortal agents receive a pre-award opportunity to
bid. Agent identity, capability accumulation, reputation policy, public traces, pricing,
and market scoring remain unchanged.
"""

from __future__ import annotations

import hashlib
import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection

from . import lifecycle_campaign as lc
from .integration_campaign import ReputationPolicy
from .topology_config import TopologyConfig, TopologySpec, topology_environment

_BASELINE_CANDIDATE_SLOTS = lc._candidate_slots


def _gini_float(values: Sequence[float]) -> float:
    if not values or sum(values) <= 0:
        return 0.0
    ordered = sorted(float(value) for value in values)
    count = len(ordered)
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    return (2 * weighted) / (count * sum(ordered)) - (count + 1) / count


def _hhi(counts: Mapping[object, int]) -> float:
    total = sum(counts.values())
    if total <= 0:
        return 0.0
    return sum((count / total) ** 2 for count in counts.values())


def _entropy(counts: Mapping[object, int]) -> float:
    total = sum(counts.values())
    if total <= 0 or len(counts) <= 1:
        return 0.0
    raw = -sum(
        (count / total) * math.log(count / total)
        for count in counts.values()
        if count > 0
    )
    return raw / math.log(len(counts))


class TopologySelector:
    """Stateful, auditable candidate-routing policy invoked before each award."""

    def __init__(
        self,
        connection: Connection[Any],
        *,
        config_hash: str,
        code_sha: str,
        experiment_number: int,
        arm_label: str,
        seed: int,
        environment,
        spec: TopologySpec,
    ) -> None:
        self.connection = connection
        self.config_hash = config_hash
        self.code_sha = code_sha
        self.experiment_number = experiment_number
        self.arm_label = arm_label
        self.seed = seed
        self.environment = environment
        self.spec = spec
        self.run_id = uuid5(
            NAMESPACE_URL,
            f"lifecycle:{code_sha}:{config_hash}:{experiment_number}:{arm_label}:{seed}",
        )
        self.start = lc._BASE_TIME + timedelta(days=experiment_number, hours=seed % 17)
        self.agent_ids = tuple(
            uuid5(self.run_id, f"agent:{slot}:generation:0")
            for slot in range(environment.agents)
        )
        self.slot_by_agent = {agent_id: slot for slot, agent_id in enumerate(self.agent_ids)}
        self.total_exposure: Counter[int] = Counter()
        self.domain_exposure: Counter[tuple[int, int]] = Counter()
        self.records: list[dict[str, object]] = []
        self.cycle_records: list[dict[str, object]] = []
        self._last_reset_regime = 0

    def _prior_awards(self) -> list[tuple[int, str, int]]:
        rows = self.connection.execute(
            """
            SELECT awarded_agent_id,
                   success_condition->>'task_domain' AS task_domain,
                   created_at
            FROM market_tasks
            WHERE awarded_agent_id = ANY(%s)
              AND awarded_at IS NOT NULL
            ORDER BY created_at, task_id
            """,
            (list(self.agent_ids),),
        ).fetchall()
        result: list[tuple[int, str, int]] = []
        for row in rows:
            agent_id = row["awarded_agent_id"]
            if agent_id not in self.slot_by_agent:
                continue
            cycle = int(
                round(
                    (row["created_at"] - self.start).total_seconds()
                    / self.environment.cycle_seconds
                )
            )
            result.append((cycle, str(row["task_domain"]), self.slot_by_agent[agent_id]))
        return result

    def _winner_context(self, cycle: int, domain_index: int) -> tuple[set[int], int | None]:
        domain = self.environment.domains[domain_index]
        awards = self._prior_awards()
        recent = {
            slot
            for won_cycle, won_domain, slot in awards
            if won_domain == domain
            and 0 < cycle - won_cycle <= max(1, self.spec.cooldown_cycles)
        }
        regime = cycle // self.environment.shift_period
        if regime <= 0:
            return recent, None
        prior_start = (regime - 1) * self.environment.shift_period
        prior_end = regime * self.environment.shift_period
        counts = Counter(
            slot
            for won_cycle, won_domain, slot in awards
            if won_domain == domain and prior_start <= won_cycle < prior_end
        )
        if not counts:
            return recent, None
        high = max(counts.values())
        incumbent = min(slot for slot, value in counts.items() if value == high)
        return recent, incumbent

    def _tie(self, cycle: int, slot: int) -> bytes:
        return hashlib.sha256(
            f"topology:{self.seed}:{cycle}:{slot}".encode()
        ).digest()

    def _structured_order(
        self,
        *,
        mode: str,
        cycle: int,
        domain_index: int,
        eligible: Sequence[int],
        recent_winners: set[int],
    ) -> list[int]:
        if mode == "global_balance":
            return sorted(
                eligible,
                key=lambda slot: (self.total_exposure[slot], self._tie(cycle, slot), slot),
            )
        if mode == "domain_balance":
            return sorted(
                eligible,
                key=lambda slot: (
                    self.domain_exposure[(domain_index, slot)],
                    self.total_exposure[slot],
                    self._tie(cycle, slot),
                    slot,
                ),
            )
        if mode == "winner_cooldown":
            return sorted(
                eligible,
                key=lambda slot: (
                    slot in recent_winners,
                    self._tie(cycle, slot),
                    slot,
                ),
            )
        if mode == "hybrid":
            return sorted(
                eligible,
                key=lambda slot: (
                    slot in recent_winners,
                    self.domain_exposure[(domain_index, slot)],
                    self.total_exposure[slot],
                    self._tie(cycle, slot),
                    slot,
                ),
            )
        return list(eligible)

    def __call__(
        self,
        seed: int,
        cycle: int,
        *,
        agents: int,
        requester_slot: int,
        count: int,
    ) -> list[int]:
        if seed != self.seed or agents != self.environment.agents:
            raise ValueError("topology selector invoked outside its experimental cell")
        regime = cycle // self.environment.shift_period
        if (
            self.spec.reset_each_regime
            and regime != self._last_reset_regime
            and cycle % self.environment.shift_period == 0
        ):
            self.total_exposure.clear()
            self.domain_exposure.clear()
            self._last_reset_regime = regime

        domain_index = lc._domain_index(seed, cycle, len(self.environment.domains))
        recent_winners, prior_incumbent = self._winner_context(cycle, domain_index)
        baseline = _BASELINE_CANDIDATE_SLOTS(
            seed,
            cycle,
            agents=agents,
            requester_slot=requester_slot,
            count=count,
        )
        restored = (
            self.spec.restore_after_cycle is not None
            and cycle >= self.spec.restore_after_cycle
        )
        applied_mode = "baseline" if restored else self.spec.mode
        if applied_mode == "baseline":
            selected = list(baseline)
            structured_slots: set[int] = set()
        else:
            eligible = [slot for slot in range(agents) if slot != requester_slot]
            ordered = self._structured_order(
                mode=applied_mode,
                cycle=cycle,
                domain_index=domain_index,
                eligible=eligible,
                recent_winners=recent_winners,
            )
            structured_count = min(
                count,
                max(1, int(round(count * self.spec.structured_fraction))),
            )
            chosen = ordered[:structured_count]
            structured_slots = set(chosen)
            selected = list(chosen)
            selected.extend(slot for slot in baseline if slot not in structured_slots)
            if len(selected) < count:
                selected.extend(slot for slot in ordered if slot not in selected)
            selected = selected[:count]

        if len(selected) != count or len(set(selected)) != count:
            raise RuntimeError("topology selector produced an invalid candidate set")
        if requester_slot in selected:
            raise RuntimeError("requester cannot be a candidate")

        for rank, slot in enumerate(selected):
            self.records.append(
                {
                    "cycle": cycle,
                    "regime": regime,
                    "domain_index": domain_index,
                    "candidate_slot": slot,
                    "candidate_rank": rank,
                    "routing_mode": applied_mode,
                    "structured": slot in structured_slots,
                    "prior_incumbent": slot == prior_incumbent,
                }
            )
            self.total_exposure[slot] += 1
            self.domain_exposure[(domain_index, slot)] += 1
        self.cycle_records.append(
            {
                "cycle": cycle,
                "regime": regime,
                "domain_index": domain_index,
                "requester_slot": requester_slot,
                "candidates": tuple(selected),
                "prior_incumbent": prior_incumbent,
                "routing_mode": applied_mode,
            }
        )
        return selected

    @staticmethod
    def _incumbent_share(rows: Sequence[Mapping[str, object]]) -> float:
        eligible = [row for row in rows if row.get("prior_incumbent") is not None]
        if not eligible:
            return 0.0
        return statistics.mean(
            float(int(row["prior_incumbent"]) in row["candidates"])  # type: ignore[arg-type]
            for row in eligible
        )

    def metrics(self) -> dict[str, float]:
        agent_counts = Counter(int(row["candidate_slot"]) for row in self.records)
        edge_counts = Counter(
            (int(row["domain_index"]), int(row["candidate_slot"]))
            for row in self.records
        )
        total_edges = len(self.records)
        repeated = 0
        last_edge: dict[tuple[int, int], int] = {}
        repeat_window = max(1, self.spec.cooldown_cycles or self.environment.shift_period)
        for row in self.records:
            key = (int(row["domain_index"]), int(row["candidate_slot"]))
            cycle = int(row["cycle"])
            if key in last_edge and cycle - last_edge[key] <= repeat_window:
                repeated += 1
            last_edge[key] = cycle
        metrics = {
            "opportunity_agent_gini": _gini_float(
                [agent_counts.get(slot, 0) for slot in range(self.environment.agents)]
            ),
            "opportunity_edge_hhi": _hhi(edge_counts),
            "opportunity_edge_entropy": _entropy(edge_counts),
            "opportunity_repeat_rate": repeated / max(1, total_edges),
            "incumbent_opportunity_share": self._incumbent_share(self.cycle_records),
            "structured_edge_share": statistics.mean(
                float(bool(row["structured"])) for row in self.records
            )
            if self.records
            else 0.0,
            "topology_observation_cycles": float(len(self.cycle_records)),
        }
        restore = self.spec.restore_after_cycle
        if restore is not None:
            width = self.environment.shift_period
            before = [
                row
                for row in self.cycle_records
                if max(0, restore - width) <= int(row["cycle"]) < restore
            ]
            after = [
                row
                for row in self.cycle_records
                if restore <= int(row["cycle"]) < min(self.environment.cycles, restore + width)
            ]
            before_share = self._incumbent_share(before)
            after_share = self._incumbent_share(after)
            metrics.update(
                {
                    "pre_restore_incumbent_opportunity_share": before_share,
                    "post_restore_incumbent_opportunity_share": after_share,
                    "restoration_opportunity_rebound": after_share - before_share,
                }
            )
        else:
            metrics.update(
                {
                    "pre_restore_incumbent_opportunity_share": 0.0,
                    "post_restore_incumbent_opportunity_share": 0.0,
                    "restoration_opportunity_rebound": 0.0,
                }
            )
        return metrics

    def observation_complete(self) -> bool:
        if len(self.cycle_records) != self.environment.cycles:
            return False
        return all(
            len(row["candidates"]) == self.environment.candidate_count  # type: ignore[arg-type]
            and int(row["requester_slot"]) not in row["candidates"]  # type: ignore[operator]
            for row in self.cycle_records
        )


def _winner_repeat_metrics(
    connection: Connection[Any],
    *,
    run_id: str,
    restore_after_cycle: int | None,
    shift_period: int,
) -> dict[str, float]:
    if restore_after_cycle is None:
        return {
            "pre_restore_winner_repeat_rate": 0.0,
            "post_restore_winner_repeat_rate": 0.0,
            "restoration_winner_rebound": 0.0,
        }
    rows = connection.execute(
        """
        SELECT cycle, domain_index, winner_slot
        FROM integration_campaign_outcomes
        WHERE run_id = %s
        ORDER BY cycle
        """,
        (UUID(run_id),),
    ).fetchall()
    repeats: list[tuple[int, float]] = []
    previous: dict[int, int] = {}
    for row in rows:
        domain = int(row["domain_index"])
        winner = int(row["winner_slot"])
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
    pre_rate = statistics.mean(pre) if pre else 0.0
    post_rate = statistics.mean(post) if post else 0.0
    return {
        "pre_restore_winner_repeat_rate": pre_rate,
        "post_restore_winner_repeat_rate": post_rate,
        "restoration_winner_rebound": post_rate - pre_rate,
    }


def _persist_observations(
    connection: Connection[Any],
    *,
    run_id: str,
    selector: TopologySelector,
) -> None:
    with connection.transaction():
        for row in selector.records:
            created_at = selector.start + timedelta(
                seconds=int(row["cycle"]) * selector.environment.cycle_seconds
            )
            connection.execute(
                """
                INSERT INTO topology_opportunity_observations (
                    run_id, cycle, regime, domain_index, candidate_slot, candidate_rank,
                    routing_mode, structured, prior_incumbent, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    UUID(run_id),
                    row["cycle"],
                    row["regime"],
                    row["domain_index"],
                    row["candidate_slot"],
                    row["candidate_rank"],
                    row["routing_mode"],
                    row["structured"],
                    row["prior_incumbent"],
                    created_at,
                ),
            )


def topology_arm(
    config: TopologyConfig,
    *,
    label: str,
    spec: TopologySpec,
    environment=None,
) -> lc.LifecycleArmSpec:
    env = environment if environment is not None else topology_environment(config)
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


def run_topology_cell(
    connection: Connection[Any],
    *,
    config: TopologyConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    label: str,
    spec: TopologySpec,
    seed: int,
    environment=None,
) -> dict[str, object]:
    arm = topology_arm(config, label=label, spec=spec, environment=environment)
    selector = TopologySelector(
        connection,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=experiment_number,
        arm_label=label,
        seed=seed,
        environment=arm.environment,
        spec=spec,
    )
    original = lc._candidate_slots
    lc._candidate_slots = selector
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
        lc._candidate_slots = original

    metrics = dict(cell["metrics"])
    metrics.update(selector.metrics())
    metrics.update(
        _winner_repeat_metrics(
            connection,
            run_id=str(cell["run_id"]),
            restore_after_cycle=spec.restore_after_cycle,
            shift_period=arm.environment.shift_period,
        )
    )
    cell["metrics"] = metrics
    invariants = dict(cell["invariants"])
    invariants["topology_observation_complete"] = selector.observation_complete()
    invariants["identity_turnover_absent"] = float(metrics.get("exit_count", 0.0)) == 0.0
    cell["invariants"] = invariants
    cell["topology"] = spec.as_dict()
    _persist_observations(connection, run_id=str(cell["run_id"]), selector=selector)
    return cell


def run_topology_arm(
    connection: Connection[Any],
    *,
    config: TopologyConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    label: str,
    spec: TopologySpec,
    seeds: Sequence[int],
    environment=None,
) -> dict[str, object]:
    cells = [
        run_topology_cell(
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
    aggregate["topology"] = spec.as_dict()
    return aggregate


def run_topology_arms(
    connection: Connection[Any],
    *,
    config: TopologyConfig,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    specs: Sequence[tuple[str, TopologySpec]],
    seeds: Sequence[int] | None = None,
    environment=None,
) -> list[dict[str, object]]:
    actual_seeds = seeds if seeds is not None else config.integration.seeds
    return [
        run_topology_arm(
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
    "TopologySelector",
    "run_topology_arm",
    "run_topology_arms",
    "run_topology_cell",
    "topology_arm",
]
