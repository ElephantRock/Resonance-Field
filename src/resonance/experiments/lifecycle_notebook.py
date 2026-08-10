"""Notebook and artifact rendering for Experiments 063–074."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from psycopg import Connection

from .integration_campaign import export_integration_campaign_artifacts


def _selected_arm(record: Mapping[str, object]) -> Mapping[str, object]:
    arms = record["arms"]
    assert isinstance(arms, Sequence)
    return next(
        arm
        for arm in arms
        if isinstance(arm, Mapping) and arm["label"] == record["selected_label"]
    )


def render_experiment_comment(
    record: Mapping[str, object],
    *,
    config_hash: str,
    code_sha: str,
) -> str:
    number = int(record["number"])
    selected = _selected_arm(record)
    metrics = selected["metrics"]
    invariants = selected["invariants"]
    assert isinstance(metrics, Mapping) and isinstance(invariants, Mapping)
    lines = [
        f"<!-- lifecycle-063-074:experiment-{number:03d} -->",
        f"## Experiment {number:03d} — completed",
        "",
        f"**Question:** {record['question']}",
        "",
        f"- Commit: `{code_sha}`",
        f"- Config hash: `{config_hash}`",
        f"- Focus: `{record['focus']}`",
        f"- Selected arm: `{record['selected_label']}`",
        f"- Success: **{float(metrics['success_rate']):.6f}**",
        f"- Actor incumbency: **{float(metrics['early_actor_incumbent_share']):.6f}**",
        f"- Lineage incumbency: **{float(metrics['early_incumbent_share']):.6f}**",
        f"- Turnover events: **{float(metrics['turnover_events']):.1f}**",
        f"- Public knowledge signal: **{float(metrics['mean_public_knowledge_signal']):.6f}**",
        f"- Retrieval lineage HHI: **{float(metrics['mean_retrieval_lineage_hhi']):.6f}**",
        f"- Predecessor-lineage retrieval: **{float(metrics['mean_predecessor_lineage_share']):.6f}**",
        f"- Newborn success: **{float(metrics['newborn_success_rate']):.6f}**",
        f"- Hard invariants: **{all(bool(value) for value in invariants.values())}**",
        f"- Next focus: `{record['next_experiment_focus']}`",
    ]
    keys = (
        "lifecycle_validated",
        "success_delta",
        "actor_incumbency_reduction",
        "lineage_incumbency_delta",
        "knowledge_retention_ratio",
        "selected_lifetime",
        "selected_mode",
        "selected_disposition",
        "death_retirement_distance",
        "death_retirement_equivalent",
        "advisor_effect",
        "lifecycle_reputation_interaction",
        "cultural_hhi_reduction",
        "mechanism_validated",
        "replication_validated",
    )
    for key in keys:
        if key in record:
            lines.append(f"- {key}: **{record[key]}**")
    if "validated" in record:
        lines.append(f"- Validated: **{record['validated']}**")
    lines.extend(["", "Arms:"])
    arms = record["arms"]
    assert isinstance(arms, Sequence)
    for arm in sorted(
        (item for item in arms if isinstance(item, Mapping)),
        key=lambda item: float(item["utility"]),
        reverse=True,
    ):
        arm_metrics = arm["metrics"]
        assert isinstance(arm_metrics, Mapping)
        lines.append(
            f"- `{arm['label']}` — utility {float(arm['utility']):.6f}; "
            f"success {float(arm_metrics['success_rate']):.6f}; "
            f"actor-inc {float(arm_metrics['early_actor_incumbent_share']):.6f}; "
            f"lineage-inc {float(arm_metrics['early_incumbent_share']):.6f}; "
            f"knowledge {float(arm_metrics['mean_public_knowledge_signal']):.6f}"
        )
    return "\n".join(lines) + "\n"


def render_synthesis(checkpoint: Mapping[str, object]) -> str:
    return "\n".join(
        [
            "<!-- lifecycle-063-074:synthesis -->",
            "## Lifecycle Campaign 063–074 — Final Synthesis",
            "",
            f"- Commit: `{checkpoint['code_sha']}`",
            f"- Config hash: `{checkpoint['config_hash']}`",
            f"- Competitive exit causal effect: **{bool(checkpoint['exit_validated'])}**",
            f"- Selected lifecycle: `{checkpoint['candidate_lifecycle']}`",
            f"- Selected policy: `{checkpoint['candidate_policy']}`",
            f"- Death/retirement equivalent: **{checkpoint['death_retirement_equivalent']}**",
            f"- Advisory result: `{checkpoint['advisory_result']}`",
            f"- Reputation interaction: `{checkpoint['reputation_interaction']}`",
            "- Cultural diversification selected: "
            f"**{bool(checkpoint['cultural_diversification_selected'])}**",
            f"- Synthesis mechanism validated: **{bool(checkpoint['mechanism_validated'])}**",
            f"- Independent replication: **{bool(checkpoint['replication_validated'])}**",
            f"- Holdout validated: **{bool(checkpoint['validated'])}**",
            "- Experiments completed: **12**",
            "",
            "Each experiment has its own checkpoint and raw real-market evidence artifact.",
        ]
    ) + "\n"


def write_step_artifacts(
    connection: Connection[Any],
    *,
    config,
    config_hash: str,
    code_sha: str,
    output_dir: str | Path,
    record: Mapping[str, object],
    checkpoint: Mapping[str, object],
) -> None:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    summary = {
        "campaign": config.integration.name,
        "code_sha": code_sha,
        "config_hash": config_hash,
        "experiments": [dict(record)],
        "checkpoint": dict(checkpoint),
    }
    export_integration_campaign_artifacts(
        connection,
        config=config.integration,
        output_dir=destination,
        summary=summary,
    )
    events = connection.execute(
        """
        SELECT run_id, cycle, slot, generation, event_type,
               old_agent_id, new_agent_id, created_at
        FROM succession_events
        WHERE run_id = ANY(%s)
        ORDER BY run_id, cycle, slot
        """,
        (
            [
                run_id
                for arm in record["arms"]  # type: ignore[index]
                for run_id in arm["run_ids"]  # type: ignore[index]
            ],
        ),
    ).fetchall()
    (destination / "succession-events.json").write_text(
        json.dumps([dict(row) for row in events], default=str, indent=2, sort_keys=True) + "\n"
    )
    (destination / "checkpoint.json").write_text(
        json.dumps(dict(checkpoint), indent=2, sort_keys=True) + "\n"
    )
    (destination / "notebook.md").write_text(
        render_experiment_comment(record, config_hash=config_hash, code_sha=code_sha)
    )
    if int(record["number"]) == 74:
        (destination / "campaign-summary.md").write_text(render_synthesis(checkpoint))
