"""Retrieval-set correction for Lifecycle Experiment 071.

Diversified retrieval must report concentration over the same trace set that supplies
its public signal.  Measuring HHI on the pre-diversification ranking would make the
policy intervention and its cultural metric describe different evidence sets.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from psycopg import Connection

from . import lifecycle_corrections


def selected_public_trace_stats(
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
    """Return signal and concentration for the exact current-cell retrieval set."""
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

    if diversified:
        best_by_lineage: dict[int, Mapping[str, object]] = {}
        for row in rows:
            lineage = author_lineage[row["author_agent_id"]]
            if lineage not in best_by_lineage:
                best_by_lineage[lineage] = row
        selected_rows = sorted(
            best_by_lineage.values(),
            key=lambda row: float(row["energy"]),
            reverse=True,
        )[: min(top_k, diversified_lineages)]
        signal = statistics.mean(float(row["energy"]) for row in selected_rows)
    else:
        selected_rows = rows[:top_k]
        signal = max(float(row["energy"]) for row in selected_rows)

    selected_lineages = [author_lineage[row["author_agent_id"]] for row in selected_rows]
    counts = Counter(selected_lineages)
    total = len(selected_rows)
    hhi = sum((count / total) ** 2 for count in counts.values()) if total else 0.0
    departed_share = (
        sum(row["author_agent_id"] in departed_agents for row in selected_rows) / total
        if total
        else 0.0
    )
    return {
        "signal": max(0.0, min(1.0, signal)),
        "lineage_hhi": hhi,
        "departed_share": departed_share,
    }


def install_diversified_retrieval_fix() -> None:
    """Install the retrieval-set metric fix into the corrected lifecycle runner."""
    lifecycle_corrections._isolated_public_trace_stats = selected_public_trace_stats
