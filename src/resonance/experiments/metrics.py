"""Quantitative emergence metrics derived from experiment evidence."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
import math
from uuid import UUID

from resonance.agents.actions import ActionType

_ACTION_SPACE_SIZE = len(ActionType)


def normalized_specialization(
    action_counts: Mapping[str, int], *, action_space_size: int = _ACTION_SPACE_SIZE
) -> float:
    """Return 1 - normalized action entropy for one agent."""
    total = sum(action_counts.values())
    if total <= 0:
        return 0.0
    if action_space_size <= 1:
        raise ValueError("action_space_size must exceed one")
    entropy = 0.0
    for count in action_counts.values():
        if count <= 0:
            continue
        probability = count / total
        entropy -= probability * math.log(probability)
    return 1.0 - entropy / math.log(action_space_size)


def agent_action_mutual_information(rows: Iterable[tuple[UUID, str]]) -> float:
    """Measure how informative agent identity is about action selection."""
    pairs = list(rows)
    if not pairs:
        return 0.0
    joint = Counter(pairs)
    agents = Counter(agent_id for agent_id, _ in pairs)
    actions = Counter(action for _, action in pairs)
    total = len(pairs)
    information = 0.0
    for (agent_id, action), count in joint.items():
        p_joint = count / total
        p_agent = agents[agent_id] / total
        p_action = actions[action] / total
        information += p_joint * math.log(p_joint / (p_agent * p_action))
    return information


def gini(values: Sequence[int]) -> float:
    """Return the Gini coefficient for non-negative balances."""
    if not values:
        return 0.0
    if any(value < 0 for value in values):
        raise ValueError("Gini values must be non-negative")
    ordered = sorted(values)
    total = sum(ordered)
    if total == 0:
        return 0.0
    n = len(ordered)
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    return (2 * weighted) / (n * total) - (n + 1) / n


def summarize_behavior(
    rows: Sequence[tuple[UUID, str, int]],
    balances: Mapping[UUID, int],
) -> dict[str, object]:
    """Summarize agent action distributions and compute inequality."""
    action_counts: dict[UUID, Counter[str]] = defaultdict(Counter)
    compute_by_agent: Counter[UUID] = Counter()
    action_pairs: list[tuple[UUID, str]] = []
    for agent_id, action, credits in rows:
        action_counts[agent_id][action] += 1
        compute_by_agent[agent_id] += credits
        action_pairs.append((agent_id, action))

    agent_metrics: list[dict[str, object]] = []
    for agent_id in sorted(balances, key=str):
        counts = action_counts.get(agent_id, Counter())
        total_actions = sum(counts.values())
        agent_metrics.append(
            {
                "agent_id": str(agent_id),
                "total_actions": total_actions,
                "specialization": normalized_specialization(counts),
                "compute_spent": compute_by_agent[agent_id],
                "ending_balance": balances[agent_id],
                "action_counts": dict(sorted(counts.items())),
                "market_actions": counts.get(ActionType.POST_TASK.value, 0)
                + counts.get(ActionType.BID_TASK.value, 0),
            }
        )

    specializations = [float(item["specialization"]) for item in agent_metrics]
    return {
        "agent_count": len(balances),
        "event_count": len(rows),
        "mean_specialization": (
            sum(specializations) / len(specializations) if specializations else 0.0
        ),
        "min_specialization": min(specializations, default=0.0),
        "max_specialization": max(specializations, default=0.0),
        "agent_action_mutual_information": agent_action_mutual_information(action_pairs),
        "compute_gini": gini(list(compute_by_agent.values())),
        "balance_gini": gini(list(balances.values())),
        "total_compute_spent": sum(compute_by_agent.values()),
        "agent_metrics": agent_metrics,
    }
