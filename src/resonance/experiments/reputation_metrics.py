"""Metrics for specialization, delegation quality, and regime-shift plasticity."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from uuid import UUID


def mutual_information(pairs: Sequence[tuple[UUID, str]]) -> float:
    if not pairs:
        return 0.0
    joint = Counter(pairs)
    left = Counter(agent_id for agent_id, _ in pairs)
    right = Counter(domain for _, domain in pairs)
    total = len(pairs)
    result = 0.0
    for (agent_id, domain), count in joint.items():
        p_joint = count / total
        result += p_joint * math.log(
            p_joint / ((left[agent_id] / total) * (right[domain] / total))
        )
    return result


def _rate(rows: Sequence[Mapping[str, object]]) -> float:
    return sum(bool(row["success"]) for row in rows) / len(rows) if rows else 0.0


def _incumbents(
    rows: Sequence[Mapping[str, object]], domains: Sequence[str]
) -> dict[str, UUID]:
    counts: dict[str, Counter[UUID]] = defaultdict(Counter)
    for row in rows:
        counts[str(row["task_domain"])][row["winner_agent_id"]] += 1
    incumbents: dict[str, UUID] = {}
    for domain in domains:
        if not counts[domain]:
            continue
        highest = max(counts[domain].values())
        incumbents[domain] = min(
            (
                agent_id
                for agent_id, count in counts[domain].items()
                if count == highest
            ),
            key=str,
        )
    return incumbents


def _incumbent_share(
    rows: Sequence[Mapping[str, object]], incumbents: Mapping[str, UUID]
) -> float:
    if not rows:
        return 0.0
    retained = sum(
        incumbents.get(str(row["task_domain"])) == row["winner_agent_id"]
        for row in rows
    )
    return retained / len(rows)


def _mean_winner_hhi(
    rows: Sequence[Mapping[str, object]], domains: Sequence[str]
) -> float:
    values: list[float] = []
    for domain in domains:
        agents = Counter(
            row["winner_agent_id"]
            for row in rows
            if str(row["task_domain"]) == domain
        )
        total = sum(agents.values())
        if total:
            values.append(sum((count / total) ** 2 for count in agents.values()))
    return sum(values) / len(values) if values else 0.0


def _mean_agent_domain_specialization(
    rows: Sequence[Mapping[str, object]], domain_count: int
) -> float:
    if domain_count <= 1:
        return 0.0
    by_agent: dict[UUID, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_agent[row["winner_agent_id"]][str(row["task_domain"])] += 1
    values: list[float] = []
    for counts in by_agent.values():
        total = sum(counts.values())
        entropy = -sum(
            (count / total) * math.log(count / total)
            for count in counts.values()
            if count
        )
        values.append(1.0 - entropy / math.log(domain_count))
    return sum(values) / len(values) if values else 0.0


def summarize_reputation_experiment(
    rows: Sequence[Mapping[str, object]],
    *,
    domains: Sequence[str],
    shift_cycle: int,
    early_post_shift_cycles: int,
    late_post_shift_cycles: int,
) -> dict[str, object]:
    ordered = sorted(rows, key=lambda row: int(row["cycle"]))
    pre = [row for row in ordered if int(row["cycle"]) < shift_cycle]
    post = [row for row in ordered if int(row["cycle"]) >= shift_cycle]
    early = [
        row
        for row in post
        if int(row["cycle"]) < shift_cycle + early_post_shift_cycles
    ]
    if ordered:
        final_cycle = int(ordered[-1]["cycle"]) + 1
        late_start = max(shift_cycle, final_cycle - late_post_shift_cycles)
    else:
        late_start = shift_cycle
    late = [row for row in post if int(row["cycle"]) >= late_start]
    incumbents = _incumbents(pre, domains)

    post_incumbent_shares: list[tuple[int, float]] = []
    window = early_post_shift_cycles
    for index in range(window - 1, len(post)):
        slice_rows = post[index - window + 1 : index + 1]
        post_incumbent_shares.append(
            (int(slice_rows[-1]["cycle"]), _incumbent_share(slice_rows, incumbents))
        )
    latency = len(post)
    for cycle, share in post_incumbent_shares:
        if share <= 0.5:
            latency = cycle - shift_cycle + 1
            break

    pre_winners = _incumbents(pre, domains)
    post_winners = _incumbents(post, domains)
    comparable = [
        domain
        for domain in domains
        if domain in pre_winners and domain in post_winners
    ]
    replacements = sum(
        pre_winners[domain] != post_winners[domain] for domain in comparable
    )

    brier = (
        sum(
            (float(row["reputation_score"]) - float(bool(row["success"]))) ** 2
            for row in ordered
        )
        / len(ordered)
        if ordered
        else 0.0
    )
    pairs = [
        (row["winner_agent_id"], str(row["task_domain"])) for row in ordered
    ]
    return {
        "task_count": len(ordered),
        "overall_success_rate": _rate(ordered),
        "pre_shift_success_rate": _rate(pre),
        "early_post_shift_success_rate": _rate(early),
        "late_post_shift_success_rate": _rate(late),
        "agent_domain_mutual_information": mutual_information(pairs),
        "mean_agent_domain_specialization": _mean_agent_domain_specialization(
            ordered, len(domains)
        ),
        "mean_domain_winner_hhi": _mean_winner_hhi(ordered, domains),
        "unique_winners": len({row["winner_agent_id"] for row in ordered}),
        "reputation_brier_score": brier,
        "pre_shift_incumbent_share_early_post": _incumbent_share(
            early, incumbents
        ),
        "pre_shift_incumbent_share_late_post": _incumbent_share(late, incumbents),
        "incumbent_share_drop": (
            _incumbent_share(early, incumbents)
            - _incumbent_share(late, incumbents)
        ),
        "post_shift_winner_replacement_rate": (
            replacements / len(comparable) if comparable else 0.0
        ),
        "adaptation_latency_cycles": latency,
        "pre_shift_incumbents": {
            domain: str(agent_id) for domain, agent_id in incumbents.items()
        },
    }
