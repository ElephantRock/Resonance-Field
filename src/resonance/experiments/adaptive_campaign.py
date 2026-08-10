"""Adaptive reputation campaign for Experiments 004 through 013.

Experiment 003 validated the persistent PostgreSQL reputation ledger. This module
isolates allocation-policy dynamics so sequential policy experiments can run quickly
and reproducibly before any scorer is considered for production integration.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CampaignPolicy:
    mode: str = "none"
    weight: float = 0.0
    freshness_half_life: float | None = None
    mass_gate: float = 0.0
    context_mode: str = "domain"
    blend_skill: float = 0.5
    positive_weight: float = 1.0
    negative_weight: float = 1.0
    shift_reset: float = 0.0

    def __post_init__(self) -> None:
        if self.mode not in {"none", "reputation"}:
            raise ValueError("mode must be none or reputation")
        if not 0.0 <= self.weight <= 0.75:
            raise ValueError("weight must be in [0, 0.75]")
        if self.freshness_half_life is not None and self.freshness_half_life <= 0:
            raise ValueError("freshness_half_life must be positive")
        if self.mass_gate < 0:
            raise ValueError("mass_gate must be non-negative")
        if self.context_mode not in {"domain", "skill", "blend"}:
            raise ValueError("unsupported context_mode")
        if not 0.0 <= self.blend_skill <= 1.0:
            raise ValueError("blend_skill must be in [0, 1]")
        if self.positive_weight <= 0 or self.negative_weight <= 0:
            raise ValueError("evidence weights must be positive")
        if not 0.0 <= self.shift_reset <= 1.0:
            raise ValueError("shift_reset must be in [0, 1]")

    @property
    def label(self) -> str:
        if self.mode == "none":
            return "no_reputation"
        freshness = (
            "raw"
            if self.freshness_half_life is None
            else f"fresh{self.freshness_half_life:g}"
        )
        return (
            f"{self.context_mode}-w{self.weight:.2f}-{freshness}"
            f"-g{self.mass_gate:g}-p{self.positive_weight:g}"
            f"-n{self.negative_weight:g}-r{self.shift_reset:g}"
            f"-b{self.blend_skill:g}"
        )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CampaignConfig:
    name: str
    agents: int
    domain_count: int
    cycles: int
    shift_period: int
    trace_half_lives: tuple[float, ...]
    candidate_count: int
    task_budget: int
    bid_deadline_seconds: int
    base_success_probability: float
    maximum_success_probability: float
    practice_scale: float
    seeds: tuple[int, ...]
    holdout_seeds: tuple[int, ...]
    holdout_cycles: int
    holdout_shift_period: int
    holdout_trace_half_lives: tuple[float, ...]
    holdout_candidate_count: int
    success_tolerance: float
    incumbent_tolerance: float

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name is required")
        if self.agents <= 1 or self.domain_count <= 1:
            raise ValueError("agents and domain_count must exceed one")
        if self.cycles <= self.shift_period or self.shift_period <= 0:
            raise ValueError("training horizon must contain at least one shift")
        if self.holdout_cycles <= self.holdout_shift_period:
            raise ValueError("holdout horizon must contain at least one shift")
        if not self.trace_half_lives or not self.holdout_trace_half_lives:
            raise ValueError("trace half-life sets must not be empty")
        if any(value <= 0 for value in self.trace_half_lives):
            raise ValueError("training trace half-lives must be positive")
        if any(value <= 0 for value in self.holdout_trace_half_lives):
            raise ValueError("holdout trace half-lives must be positive")
        if not 1 <= self.candidate_count < self.agents:
            raise ValueError("candidate_count must be smaller than population")
        if not 1 <= self.holdout_candidate_count < self.agents:
            raise ValueError("holdout_candidate_count must be smaller than population")
        if self.task_budget <= 0 or self.bid_deadline_seconds <= 0:
            raise ValueError("task market bounds must be positive")
        if not 0 <= self.base_success_probability <= 1:
            raise ValueError("base_success_probability must be in [0, 1]")
        if not self.base_success_probability <= self.maximum_success_probability <= 1:
            raise ValueError("maximum_success_probability must be in [base, 1]")
        if self.practice_scale <= 0:
            raise ValueError("practice_scale must be positive")
        if not self.seeds or not self.holdout_seeds:
            raise ValueError("training and holdout seeds are required")
        if self.success_tolerance < 0 or self.incumbent_tolerance < 0:
            raise ValueError("selection tolerances must be non-negative")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CampaignConfig:
        return cls(
            name=str(value["name"]),
            agents=int(value["agents"]),
            domain_count=int(value["domain_count"]),
            cycles=int(value["cycles"]),
            shift_period=int(value["shift_period"]),
            trace_half_lives=tuple(float(v) for v in value["trace_half_lives"]),
            candidate_count=int(value["candidate_count"]),
            task_budget=int(value["task_budget"]),
            bid_deadline_seconds=int(value["bid_deadline_seconds"]),
            base_success_probability=float(value["base_success_probability"]),
            maximum_success_probability=float(value["maximum_success_probability"]),
            practice_scale=float(value["practice_scale"]),
            seeds=tuple(int(v) for v in value["seeds"]),
            holdout_seeds=tuple(int(v) for v in value["holdout_seeds"]),
            holdout_cycles=int(value["holdout_cycles"]),
            holdout_shift_period=int(value["holdout_shift_period"]),
            holdout_trace_half_lives=tuple(
                float(v) for v in value["holdout_trace_half_lives"]
            ),
            holdout_candidate_count=int(value["holdout_candidate_count"]),
            success_tolerance=float(value["success_tolerance"]),
            incumbent_tolerance=float(value["incumbent_tolerance"]),
        )


@dataclass(frozen=True, slots=True)
class Environment:
    cycles: int
    shift_period: int
    trace_half_lives: tuple[float, ...]
    candidate_count: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


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


def baseline_bid_score(
    *,
    confidence: float,
    price: int,
    budget: int,
    completion_seconds: int,
    available_seconds: int,
) -> float:
    """Mirror the production market score for campaign simulations."""
    price_efficiency = 1.0 - (price / budget)
    speed = 1.0 - min(1.0, completion_seconds / max(1.0, available_seconds))
    return 0.45 * confidence + 0.35 * price_efficiency + 0.20 * speed


def _reputation_signal(
    state: tuple[float, float],
    last_evidence_cycle: int | None,
    cycle: int,
    policy: CampaignPolicy,
) -> float:
    alpha, beta = state
    raw = alpha / (alpha + beta)
    if policy.freshness_half_life is None:
        freshness = 1.0
    elif last_evidence_cycle is None:
        freshness = 0.0
    else:
        freshness = 2 ** (
            -(cycle - last_evidence_cycle) / policy.freshness_half_life
        )
    evidence_mass = max(0.0, alpha + beta - 2.0)
    mass_factor = (
        1.0
        if policy.mass_gate <= 0
        else evidence_mass / (evidence_mass + policy.mass_gate)
    )
    return 0.5 + (raw - 0.5) * freshness * mass_factor


def _mutual_information(pairs: Sequence[tuple[int, int]]) -> float:
    if not pairs:
        return 0.0
    joint = Counter(pairs)
    agents = Counter(agent for agent, _ in pairs)
    domains = Counter(domain for _, domain in pairs)
    total = len(pairs)
    result = 0.0
    for (agent, domain), count in joint.items():
        p_joint = count / total
        result += p_joint * math.log(
            p_joint / ((agents[agent] / total) * (domains[domain] / total))
        )
    return result


def _incumbents(
    rows: Sequence[Mapping[str, object]],
    domain_count: int,
) -> dict[int, int]:
    result: dict[int, int] = {}
    for domain in range(domain_count):
        counts = Counter(
            int(row["winner"])
            for row in rows
            if int(row["domain"]) == domain
        )
        if not counts:
            continue
        highest = max(counts.values())
        result[domain] = min(
            agent for agent, count in counts.items() if count == highest
        )
    return result


def _summarize_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    domain_count: int,
    shift_period: int,
) -> dict[str, float]:
    success = sum(bool(row["success"]) for row in rows) / len(rows)
    pairs = [(int(row["winner"]), int(row["domain"])) for row in rows]

    by_agent: dict[int, Counter[int]] = defaultdict(Counter)
    for agent, domain in pairs:
        by_agent[agent][domain] += 1
    specializations: list[float] = []
    for counts in by_agent.values():
        total = sum(counts.values())
        entropy = -sum(
            (count / total) * math.log(count / total)
            for count in counts.values()
            if count
        )
        specializations.append(1.0 - entropy / math.log(domain_count))

    hhis: list[float] = []
    for domain in range(domain_count):
        counts = Counter(
            int(row["winner"])
            for row in rows
            if int(row["domain"]) == domain
        )
        total = sum(counts.values())
        if total:
            hhis.append(sum((count / total) ** 2 for count in counts.values()))

    incumbent_shares: list[float] = []
    replacements: list[float] = []
    window = min(20, shift_period)
    for shift in range(shift_period, len(rows), shift_period):
        pre = rows[max(0, shift - shift_period) : shift]
        early = rows[shift : min(len(rows), shift + window)]
        post = rows[shift : min(len(rows), shift + shift_period)]
        if not early or not post:
            continue
        old = _incumbents(pre, domain_count)
        new = _incumbents(post, domain_count)
        incumbent_shares.append(
            sum(
                old.get(int(row["domain"])) == int(row["winner"])
                for row in early
            )
            / len(early)
        )
        comparable = [domain for domain in old if domain in new]
        replacements.append(
            sum(old[domain] != new[domain] for domain in comparable)
            / len(comparable)
            if comparable
            else 0.0
        )

    return {
        "success_rate": success,
        "agent_domain_mutual_information": _mutual_information(pairs),
        "mean_specialization": statistics.mean(specializations),
        "mean_winner_hhi": statistics.mean(hhis),
        "early_incumbent_share": statistics.mean(incumbent_shares),
        "winner_replacement_rate": statistics.mean(replacements),
    }


def _active_reputation(
    *,
    policy: CampaignPolicy,
    domain_state: tuple[float, float],
    domain_last: int | None,
    skill_state: tuple[float, float],
    skill_last: int | None,
    cycle: int,
) -> float:
    if policy.mode == "none":
        return 0.5
    domain_score = _reputation_signal(
        domain_state,
        domain_last,
        cycle,
        policy,
    )
    skill_score = _reputation_signal(
        skill_state,
        skill_last,
        cycle,
        policy,
    )
    if policy.context_mode == "domain":
        return domain_score
    if policy.context_mode == "skill":
        return skill_score
    return (
        (1.0 - policy.blend_skill) * domain_score
        + policy.blend_skill * skill_score
    )


def run_cell(
    config: CampaignConfig,
    *,
    policy: CampaignPolicy,
    seed: int,
    trace_half_life: float,
    environment: Environment,
) -> dict[str, float]:
    agents = config.agents
    domains = config.domain_count
    practice = [[0 for _ in range(domains)] for _ in range(agents)]
    last_success: list[list[int | None]] = [
        [None for _ in range(domains)] for _ in range(agents)
    ]
    domain_state = {
        (agent, domain): [1.0, 1.0]
        for agent in range(agents)
        for domain in range(domains)
    }
    skill_state = {
        (agent, skill): [1.0, 1.0]
        for agent in range(agents)
        for skill in range(domains)
    }
    domain_last: dict[tuple[int, int], int | None] = {
        key: None for key in domain_state
    }
    skill_last: dict[tuple[int, int], int | None] = {
        key: None for key in skill_state
    }
    rows: list[dict[str, object]] = []
    previous_regime = 0

    for cycle in range(environment.cycles):
        regime = cycle // environment.shift_period
        if regime != previous_regime:
            if policy.mode == "reputation" and policy.shift_reset > 0:
                for state in domain_state.values():
                    state[0] = 1.0 + (state[0] - 1.0) * (1.0 - policy.shift_reset)
                    state[1] = 1.0 + (state[1] - 1.0) * (1.0 - policy.shift_reset)
            previous_regime = regime

        domain = _domain_index(seed, cycle, domains)
        required_skill = (domain + regime) % domains
        requester = cycle % agents
        bids: list[tuple[float, int, int]] = []
        candidates = _candidate_slots(
            seed,
            cycle,
            agents=agents,
            requester_slot=requester,
            count=environment.candidate_count,
        )
        for slot in candidates:
            last = last_success[slot][required_skill]
            evidence_signal = (
                0.0
                if last is None
                else 0.9 * 2 ** (-(cycle - last) / trace_half_life)
            )
            confidence = min(
                0.98,
                0.35
                + 0.45 * evidence_signal
                + 0.20 * _draw(seed, cycle, slot, "confidence"),
            )
            price_fraction = 0.45 + 0.35 * _draw(seed, cycle, slot, "price")
            price = max(
                1,
                min(config.task_budget, int(config.task_budget * price_fraction)),
            )
            completion = 5 + int(_draw(seed, cycle, slot, "speed") * 12)
            baseline = baseline_bid_score(
                confidence=confidence,
                price=price,
                budget=config.task_budget,
                completion_seconds=completion,
                available_seconds=config.bid_deadline_seconds,
            )
            reputation = _active_reputation(
                policy=policy,
                domain_state=tuple(domain_state[(slot, domain)]),
                domain_last=domain_last[(slot, domain)],
                skill_state=tuple(skill_state[(slot, required_skill)]),
                skill_last=skill_last[(slot, required_skill)],
                cycle=cycle,
            )
            total = baseline + policy.weight * (reputation - 0.5)
            bids.append((total, -slot, slot))

        _, _, winner = max(bids)
        practice_count = practice[winner][required_skill]
        probability = config.base_success_probability + (
            config.maximum_success_probability - config.base_success_probability
        ) * (1.0 - math.exp(-practice_count / config.practice_scale))
        succeeded = _draw(seed, cycle, winner, "outcome") < probability
        practice[winner][required_skill] += 1
        if succeeded:
            last_success[winner][required_skill] = cycle
            domain_state[(winner, domain)][0] += policy.positive_weight
            skill_state[(winner, required_skill)][0] += policy.positive_weight
        else:
            domain_state[(winner, domain)][1] += policy.negative_weight
            skill_state[(winner, required_skill)][1] += policy.negative_weight
        domain_last[(winner, domain)] = cycle
        skill_last[(winner, required_skill)] = cycle
        rows.append(
            {
                "cycle": cycle,
                "regime": regime,
                "domain": domain,
                "required_skill": required_skill,
                "winner": winner,
                "success": succeeded,
            }
        )

    return _summarize_rows(
        rows,
        domain_count=domains,
        shift_period=environment.shift_period,
    )


def _average_metrics(rows: Sequence[Mapping[str, float]]) -> dict[str, float]:
    keys = rows[0].keys()
    return {key: statistics.mean(row[key] for row in rows) for key in keys}


def evaluate_policy(
    config: CampaignConfig,
    *,
    policy: CampaignPolicy,
    seeds: Sequence[int],
    environment: Environment,
) -> tuple[dict[str, float], list[dict[str, object]]]:
    cells: list[dict[str, object]] = []
    metrics: list[dict[str, float]] = []
    for seed in seeds:
        for trace_half_life in environment.trace_half_lives:
            cell = run_cell(
                config,
                policy=policy,
                seed=seed,
                trace_half_life=trace_half_life,
                environment=environment,
            )
            metrics.append(cell)
            cells.append(
                {
                    "seed": seed,
                    "trace_half_life": trace_half_life,
                    **cell,
                }
            )
    return _average_metrics(metrics), cells


def structure_score(metrics: Mapping[str, float], domain_count: int) -> float:
    normalized_mi = metrics["agent_domain_mutual_information"] / math.log(domain_count)
    return (
        0.60 * normalized_mi
        + 0.40 * metrics["mean_specialization"]
        - 0.20 * metrics["mean_winner_hhi"]
    )


def selection_utility(metrics: Mapping[str, float], domain_count: int) -> float:
    return (
        metrics["success_rate"]
        + 0.10 * structure_score(metrics, domain_count)
        + 0.05 * metrics["winner_replacement_rate"]
        - 0.08 * metrics["early_incumbent_share"]
    )


def is_feasible(
    metrics: Mapping[str, float],
    control: Mapping[str, float],
    config: CampaignConfig,
) -> bool:
    return (
        metrics["success_rate"] >= control["success_rate"] - config.success_tolerance
        and metrics["early_incumbent_share"]
        <= control["early_incumbent_share"] + config.incumbent_tolerance
    )


def _unique_policies(policies: Sequence[CampaignPolicy]) -> list[CampaignPolicy]:
    seen: set[str] = set()
    result: list[CampaignPolicy] = []
    for policy in policies:
        key = json.dumps(policy.as_dict(), sort_keys=True)
        if key not in seen:
            seen.add(key)
            result.append(policy)
    return result


def _raw_policy() -> CampaignPolicy:
    return CampaignPolicy(
        mode="reputation",
        weight=0.45,
        freshness_half_life=None,
        context_mode="domain",
    )


def _experiment_004_candidates() -> list[CampaignPolicy]:
    return [
        CampaignPolicy(),
        _raw_policy(),
        CampaignPolicy("reputation", 0.45, 6.0, context_mode="domain"),
        CampaignPolicy("reputation", 0.45, 12.0, context_mode="domain"),
        CampaignPolicy("reputation", 0.45, 24.0, context_mode="domain"),
        CampaignPolicy("reputation", 0.45, 48.0, context_mode="domain"),
    ]


def _active_weight(policy: CampaignPolicy) -> float:
    return max(0.10, policy.weight or 0.35)


def _variants(policy: CampaignPolicy, dimension: str) -> list[CampaignPolicy]:
    weight = _active_weight(policy)
    if dimension == "weight":
        values = {
            0.0,
            max(0.0, policy.weight - 0.10),
            policy.weight,
            min(0.75, policy.weight + 0.10),
            min(0.75, policy.weight + 0.20),
        }
        return [
            CampaignPolicy()
            if value == 0
            else replace(policy, mode="reputation", weight=value)
            for value in sorted(values)
        ]
    if dimension == "freshness":
        base = policy.freshness_half_life or 24.0
        values: set[float | None] = {
            policy.freshness_half_life,
            max(2.0, base / 2.0),
            min(120.0, base * 2.0),
            6.0,
            12.0,
            24.0,
            None,
        }
        return [
            replace(
                policy,
                mode="reputation",
                weight=weight,
                freshness_half_life=value,
            )
            for value in values
        ]
    if dimension == "context":
        return [
            replace(policy, mode="reputation", weight=weight, context_mode=value)
            for value in ("domain", "skill", "blend")
        ]
    if dimension == "blend":
        base = replace(
            policy,
            mode="reputation",
            weight=weight,
            context_mode="blend",
        )
        return [replace(base, blend_skill=value) for value in (0.25, 0.50, 0.75)]
    if dimension == "mass_gate":
        return [
            replace(policy, mode="reputation", weight=weight, mass_gate=value)
            for value in (0.0, 1.0, 2.0, 4.0, 8.0)
        ]
    if dimension == "positive_weight":
        return [
            replace(policy, mode="reputation", weight=weight, positive_weight=value)
            for value in (0.50, 0.75, 1.0, 1.50, 2.0)
        ]
    if dimension == "negative_weight":
        return [
            replace(policy, mode="reputation", weight=weight, negative_weight=value)
            for value in (0.50, 0.75, 1.0, 1.50, 2.0)
        ]
    if dimension == "shift_reset":
        return [
            replace(policy, mode="reputation", weight=weight, shift_reset=value)
            for value in (0.0, 0.20, 0.40, 0.60, 0.80)
        ]
    raise ValueError(f"unknown dimension: {dimension}")


def _select_policy(
    config: CampaignConfig,
    *,
    candidates: Sequence[CampaignPolicy],
    seeds: Sequence[int],
    environment: Environment,
) -> tuple[CampaignPolicy, list[dict[str, object]], dict[str, float]]:
    control = CampaignPolicy()
    control_metrics, _ = evaluate_policy(
        config,
        policy=control,
        seeds=seeds,
        environment=environment,
    )
    arms: list[dict[str, object]] = []
    for policy in _unique_policies(candidates):
        metrics, cells = evaluate_policy(
            config,
            policy=policy,
            seeds=seeds,
            environment=environment,
        )
        arms.append(
            {
                "policy": policy.as_dict(),
                "label": policy.label,
                "metrics": metrics,
                "cells": cells,
                "feasible": is_feasible(metrics, control_metrics, config),
                "structure_score": structure_score(metrics, config.domain_count),
                "utility": selection_utility(metrics, config.domain_count),
            }
        )
    feasible_arms = [arm for arm in arms if bool(arm["feasible"])]
    pool = feasible_arms or arms
    selected = max(
        pool,
        key=lambda arm: (
            float(arm["utility"]),
            float(arm["metrics"]["success_rate"]),
            -float(arm["metrics"]["early_incumbent_share"]),
            float(arm["structure_score"]),
            str(arm["label"]),
        ),
    )
    return CampaignPolicy(**selected["policy"]), arms, control_metrics


def _dominant_failure(
    config: CampaignConfig,
    selected: Mapping[str, float],
    control: Mapping[str, float],
) -> str:
    quality_deficit = control["success_rate"] - selected["success_rate"]
    incumbent_excess = (
        selected["early_incumbent_share"] - control["early_incumbent_share"]
    )
    structure_gain = structure_score(
        selected,
        config.domain_count,
    ) - structure_score(control, config.domain_count)
    if incumbent_excess > 0.025:
        return "plasticity"
    if quality_deficit > 0.005:
        return "quality"
    if structure_gain < 0.02:
        return "structure"
    return "calibration"


def _next_dimension(failure: str, tested: set[str]) -> str:
    orders = {
        "plasticity": (
            "freshness",
            "shift_reset",
            "context",
            "weight",
            "mass_gate",
            "negative_weight",
            "positive_weight",
            "blend",
        ),
        "quality": (
            "weight",
            "context",
            "freshness",
            "negative_weight",
            "positive_weight",
            "mass_gate",
            "shift_reset",
            "blend",
        ),
        "structure": (
            "weight",
            "context",
            "freshness",
            "blend",
            "positive_weight",
            "mass_gate",
            "negative_weight",
            "shift_reset",
        ),
        "calibration": (
            "mass_gate",
            "negative_weight",
            "positive_weight",
            "shift_reset",
            "context",
            "weight",
            "freshness",
            "blend",
        ),
    }
    for dimension in orders[failure]:
        if dimension not in tested:
            return dimension
    raise ValueError("all adaptive dimensions have already been tested")


def _question_for_dimension(dimension: str, failure: str) -> str:
    labels = {
        "weight": "reputation influence strength",
        "freshness": "reputation freshness horizon",
        "context": "domain-versus-skill reputation context",
        "blend": "domain/skill context blending",
        "mass_gate": "minimum evidence mass",
        "positive_weight": "positive-evidence strength",
        "negative_weight": "negative-evidence strength",
        "shift_reset": "partial domain-memory reset at regime changes",
    }
    return (
        f"Can tuning {labels[dimension]} improve the current policy's "
        f"{failure} tradeoff without violating quality/plasticity constraints?"
    )


def _stress_environment(
    config: CampaignConfig,
    failure: str,
) -> tuple[str, Environment]:
    if failure == "plasticity":
        return (
            "accelerated_regime_shifts",
            Environment(
                cycles=config.cycles,
                shift_period=max(24, config.shift_period // 2),
                trace_half_lives=config.trace_half_lives,
                candidate_count=config.candidate_count,
            ),
        )
    if failure == "quality":
        return (
            "thin_candidate_market",
            Environment(
                cycles=config.cycles,
                shift_period=config.shift_period,
                trace_half_lives=config.trace_half_lives,
                candidate_count=max(3, config.candidate_count - 3),
            ),
        )
    if failure == "structure":
        return (
            "trace_memory_collapse",
            Environment(
                cycles=config.cycles,
                shift_period=config.shift_period,
                trace_half_lives=(1.5, 3.0),
                candidate_count=config.candidate_count,
            ),
        )
    return (
        "mixed_memory_pressure",
        Environment(
            cycles=config.cycles,
            shift_period=max(36, config.shift_period - 12),
            trace_half_lives=(2.0, 8.0, 24.0),
            candidate_count=config.candidate_count,
        ),
    )


def _stress_candidates(
    policy: CampaignPolicy,
    failure: str,
) -> list[CampaignPolicy]:
    candidates = [CampaignPolicy(), _raw_policy(), policy]
    if failure == "plasticity":
        candidates.extend(_variants(policy, "shift_reset"))
        candidates.extend(_variants(policy, "freshness"))
    elif failure == "quality":
        candidates.extend(_variants(policy, "weight"))
        candidates.extend(_variants(policy, "context"))
    elif failure == "structure":
        candidates.extend(_variants(policy, "freshness"))
        candidates.extend(_variants(policy, "weight"))
    else:
        candidates.extend(_variants(policy, "mass_gate"))
        candidates.extend(_variants(policy, "negative_weight"))
    return _unique_policies(candidates)


def _holdout_environment(
    config: CampaignConfig,
    failure: str,
) -> tuple[str, Environment]:
    shift_period = config.holdout_shift_period
    trace_half_lives = config.holdout_trace_half_lives
    candidate_count = config.holdout_candidate_count
    if failure == "plasticity":
        shift_period = max(24, shift_period - 12)
    elif failure == "quality":
        candidate_count = max(3, candidate_count - 2)
    elif failure == "structure":
        trace_half_lives = tuple(sorted({2.0, *trace_half_lives}))
    return (
        f"holdout_{failure}",
        Environment(
            cycles=config.holdout_cycles,
            shift_period=shift_period,
            trace_half_lives=trace_half_lives,
            candidate_count=candidate_count,
        ),
    )


def _selected_arm(
    arms: Sequence[Mapping[str, object]],
    label: str,
) -> Mapping[str, object]:
    return next(arm for arm in arms if arm["label"] == label)


def _decision_text(
    selected: CampaignPolicy,
    arms: Sequence[Mapping[str, object]],
    failure: str,
) -> str:
    metrics = _selected_arm(arms, selected.label)["metrics"]
    return (
        f"Selected {selected.label}: success={metrics['success_rate']:.4f}, "
        f"incumbent={metrics['early_incumbent_share']:.4f}, "
        f"MI={metrics['agent_domain_mutual_information']:.4f}. "
        f"Dominant remaining failure mode: {failure}."
    )


def run_campaign(
    config: CampaignConfig,
    *,
    code_sha: str,
    output_dir: str | Path,
) -> dict[str, object]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    training_environment = Environment(
        cycles=config.cycles,
        shift_period=config.shift_period,
        trace_half_lives=config.trace_half_lives,
        candidate_count=config.candidate_count,
    )
    experiments: list[dict[str, object]] = []

    selected, arms, control = _select_policy(
        config,
        candidates=_experiment_004_candidates(),
        seeds=config.seeds,
        environment=training_environment,
    )
    selected_metrics = _selected_arm(arms, selected.label)["metrics"]
    failure = _dominant_failure(config, selected_metrics, control)
    tested: set[str] = {"freshness"}
    next_dimension = _next_dimension(failure, tested)
    experiments.append(
        {
            "number": 4,
            "question": (
                "Can freshness-aware reputation preserve useful organizational memory "
                "while reducing stale-incumbent retention under repeated context shifts?"
            ),
            "focus": "freshness_screen",
            "motivating_failure": "plasticity",
            "observed_failure": failure,
            "environment": training_environment.as_dict(),
            "arms": arms,
            "selected_policy": selected.as_dict(),
            "selected_label": selected.label,
            "decision": _decision_text(selected, arms, failure),
            "next_experiment_focus": next_dimension,
        }
    )

    for number in range(5, 12):
        motivating_failure = failure
        dimension = next_dimension
        tested.add(dimension)
        candidates = [CampaignPolicy(), selected, *_variants(selected, dimension)]
        selected, arms, control = _select_policy(
            config,
            candidates=candidates,
            seeds=config.seeds,
            environment=training_environment,
        )
        selected_metrics = _selected_arm(arms, selected.label)["metrics"]
        failure = _dominant_failure(config, selected_metrics, control)
        if number < 11:
            next_dimension = _next_dimension(failure, tested)
            next_focus = next_dimension
        else:
            next_focus = f"stress:{_stress_environment(config, failure)[0]}"
        experiments.append(
            {
                "number": number,
                "question": _question_for_dimension(dimension, motivating_failure),
                "focus": dimension,
                "motivating_failure": motivating_failure,
                "observed_failure": failure,
                "environment": training_environment.as_dict(),
                "arms": arms,
                "selected_policy": selected.as_dict(),
                "selected_label": selected.label,
                "decision": _decision_text(selected, arms, failure),
                "next_experiment_focus": next_focus,
            }
        )

    stress_motivation = failure
    stress_name, stress_environment = _stress_environment(config, stress_motivation)
    selected, arms, control = _select_policy(
        config,
        candidates=_stress_candidates(selected, stress_motivation),
        seeds=config.seeds,
        environment=stress_environment,
    )
    selected_metrics = _selected_arm(arms, selected.label)["metrics"]
    failure = _dominant_failure(config, selected_metrics, control)
    holdout_name, holdout_environment = _holdout_environment(config, failure)
    experiments.append(
        {
            "number": 12,
            "question": (
                f"Does the selected policy survive {stress_name.replace('_', ' ')} "
                "without losing quality or plasticity?"
            ),
            "focus": stress_name,
            "motivating_failure": stress_motivation,
            "observed_failure": failure,
            "environment": stress_environment.as_dict(),
            "arms": arms,
            "selected_policy": selected.as_dict(),
            "selected_label": selected.label,
            "decision": _decision_text(selected, arms, failure),
            "next_experiment_focus": holdout_name,
        }
    )

    final_policy = selected
    holdout_candidates = [CampaignPolicy(), _raw_policy(), final_policy]
    holdout_best, arms, holdout_control = _select_policy(
        config,
        candidates=holdout_candidates,
        seeds=config.holdout_seeds,
        environment=holdout_environment,
    )
    final_arm = _selected_arm(arms, final_policy.label)
    control_arm = _selected_arm(arms, CampaignPolicy().label)
    validated = (
        is_feasible(final_arm["metrics"], holdout_control, config)
        and float(final_arm["utility"]) >= float(control_arm["utility"]) - 0.005
    )
    experiments.append(
        {
            "number": 13,
            "question": (
                "Does the policy selected by Experiments 004–012 generalize to unseen "
                "seeds and an independently selected shock schedule?"
            ),
            "focus": holdout_name,
            "motivating_failure": failure,
            "observed_failure": None,
            "environment": holdout_environment.as_dict(),
            "arms": arms,
            "selected_policy": final_policy.as_dict(),
            "selected_label": final_policy.label,
            "holdout_best_label": holdout_best.label,
            "validated": validated,
            "decision": (
                f"Final policy {'validated' if validated else 'did not validate'} on holdout. "
                f"Final utility={float(final_arm['utility']):.4f}; "
                f"control utility={float(control_arm['utility']):.4f}."
            ),
            "next_experiment_focus": None,
        }
    )

    summary = {
        "name": config.name,
        "code_sha": code_sha,
        "experiment_numbers": list(range(4, 14)),
        "final_policy": final_policy.as_dict(),
        "final_label": final_policy.label,
        "validated": validated,
        "experiments": experiments,
    }
    (destination / "campaign.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    _write_artifacts(destination, experiments)
    return summary


def _write_artifacts(
    destination: Path,
    experiments: Sequence[Mapping[str, object]],
) -> None:
    summary_rows: list[dict[str, object]] = []
    cell_rows: list[dict[str, object]] = []
    for experiment in experiments:
        number = int(experiment["number"])
        (destination / f"experiment-{number:03d}.json").write_text(
            json.dumps(dict(experiment), indent=2, sort_keys=True) + "\n"
        )
        for arm in experiment["arms"]:
            metrics = arm["metrics"]
            summary_rows.append(
                {
                    "experiment": number,
                    "focus": experiment["focus"],
                    "label": arm["label"],
                    "feasible": arm["feasible"],
                    "utility": arm["utility"],
                    "structure_score": arm["structure_score"],
                    **metrics,
                }
            )
            for cell in arm["cells"]:
                cell_rows.append(
                    {
                        "experiment": number,
                        "focus": experiment["focus"],
                        "label": arm["label"],
                        **cell,
                    }
                )
    _write_csv(destination / "experiment-arms.csv", summary_rows)
    _write_csv(destination / "cells.csv", cell_rows)


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_campaign_config(path: str | Path) -> tuple[CampaignConfig, str]:
    raw = Path(path).read_bytes()
    value: Any = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("campaign config must contain a JSON object")
    return CampaignConfig.from_mapping(value), hashlib.sha256(raw).hexdigest()
