"""Metrics that make trace-decay effects directly observable."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
import math
from uuid import UUID


def jaccard_turnover(previous: Sequence[UUID], current: Sequence[UUID]) -> float:
    left = set(previous)
    right = set(current)
    if not left and not right:
        return 0.0
    union = left | right
    return 1.0 - len(left & right) / len(union)


def mean_rank_displacement(previous: Sequence[UUID], current: Sequence[UUID]) -> float:
    previous_rank = {trace_id: index for index, trace_id in enumerate(previous, start=1)}
    current_rank = {trace_id: index for index, trace_id in enumerate(current, start=1)}
    shared = previous_rank.keys() & current_rank.keys()
    if not shared:
        return float(max(len(previous), len(current)))
    return sum(abs(previous_rank[item] - current_rank[item]) for item in shared) / len(shared)


def entropy(values: Sequence[UUID]) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    total = len(values)
    return -sum((count / total) * math.log(count / total) for count in counts.values())


def summarize_decay_observations(
    rows: Sequence[Mapping[str, object]],
    *,
    old_age_seconds: float,
    resurrection_rows: Sequence[Mapping[str, object]] = (),
) -> dict[str, float | int]:
    """Summarize post-cycle turnover plus same-cycle pre/post action effects."""
    if old_age_seconds <= 0:
        raise ValueError("old_age_seconds must be positive")

    grouped: dict[tuple[int, str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["cycle"]), str(row["phase"]), str(row["neighborhood"]))].append(row)
    for items in grouped.values():
        items.sort(key=lambda row: int(row["rank"]))

    post_keys = sorted(key for key in grouped if key[1] == "post")
    post_by_neighborhood: dict[str, list[tuple[int, list[Mapping[str, object]]]]] = defaultdict(list)
    for cycle, _, neighborhood in post_keys:
        post_by_neighborhood[neighborhood].append((cycle, grouped[(cycle, "post", neighborhood)]))

    top_changes = 0
    transitions = 0
    jaccard_values: list[float] = []
    displacement_values: list[float] = []
    top_ids: list[UUID] = []
    top_ages: list[float] = []
    retrieved_ages: list[float] = []
    old_retrieved = 0
    retrieved_total = 0

    for observations in post_by_neighborhood.values():
        previous_ids: list[UUID] | None = None
        previous_top: UUID | None = None
        for _, items in observations:
            ids = [row["trace_id"] for row in items]
            if not ids:
                continue
            top = ids[0]
            top_ids.append(top)
            top_ages.append(float(items[0]["trace_age_seconds"]))
            for row in items:
                age = float(row["trace_age_seconds"])
                retrieved_ages.append(age)
                retrieved_total += 1
                if age >= old_age_seconds:
                    old_retrieved += 1
            if previous_ids is not None and previous_top is not None:
                transitions += 1
                if top != previous_top:
                    top_changes += 1
                jaccard_values.append(jaccard_turnover(previous_ids, ids))
                displacement_values.append(mean_rank_displacement(previous_ids, ids))
            previous_ids = ids
            previous_top = top

    same_cycle_changes = 0
    same_cycle_pairs = 0
    for cycle, _, neighborhood in post_keys:
        pre = grouped.get((cycle, "pre", neighborhood))
        post = grouped[(cycle, "post", neighborhood)]
        if pre and post:
            same_cycle_pairs += 1
            if pre[0]["trace_id"] != post[0]["trace_id"]:
                same_cycle_changes += 1

    confirmed = sum(bool(row["confirmed"]) for row in resurrection_rows)
    resurrection_total = len(resurrection_rows)

    return {
        "top_turnover_rate": top_changes / transitions if transitions else 0.0,
        "top_k_jaccard_turnover": (
            sum(jaccard_values) / len(jaccard_values) if jaccard_values else 0.0
        ),
        "mean_rank_displacement": (
            sum(displacement_values) / len(displacement_values)
            if displacement_values
            else 0.0
        ),
        "same_cycle_top_change_rate": (
            same_cycle_changes / same_cycle_pairs if same_cycle_pairs else 0.0
        ),
        "mean_top_trace_age_seconds": sum(top_ages) / len(top_ages) if top_ages else 0.0,
        "mean_retrieved_trace_age_seconds": (
            sum(retrieved_ages) / len(retrieved_ages) if retrieved_ages else 0.0
        ),
        "old_trace_retrieval_share": old_retrieved / retrieved_total if retrieved_total else 0.0,
        "unique_top_traces": len(set(top_ids)),
        "top_trace_entropy": entropy(top_ids),
        "resurrection_attempts": resurrection_total,
        "confirmed_resurrections": confirmed,
        "resurrection_confirmation_rate": (
            confirmed / resurrection_total if resurrection_total else 0.0
        ),
    }
