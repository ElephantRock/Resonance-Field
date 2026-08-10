"""Notebook and artifact rendering for Experiments 053–062."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from psycopg import Connection

from .integration_campaign import export_integration_campaign_artifacts
from .two_timescale_config import TwoTimescaleConfig


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
        f"<!-- two-timescale-053-062:experiment-{number:03d} -->",
        f"## Experiment {number:03d} — completed",
        "",
        f"**Question:** {record['question']}",
        "",
        f"- Commit: `{code_sha}`",
        f"- Config hash: `{config_hash}`",
        f"- Focus: `{record['focus']}`",
        f"- Selected arm: `{record['selected_label']}`",
        f"- Success: **{float(metrics['success_rate']):.6f}**",
        f"- Agent/domain MI: **{float(metrics['agent_domain_mutual_information']):.6f}**",
        f"- Specialization: **{float(metrics['mean_specialization']):.6f}**",
        f"- Early incumbent share: **{float(metrics['early_incumbent_share']):.6f}**",
        f"- Hard invariants: **{all(bool(value) for value in invariants.values())}**",
        f"- Next focus: `{record['next_experiment_focus']}`",
    ]
    keys = (
        "practice_gain",
        "tau_f",
        "control_tau_f",
        "tau_d",
        "control_tau_d",
        "pre_incumbent_share",
        "late_incumbent_share",
        "reference_effect",
        "reference_sign",
        "theta_f",
        "theta_d",
        "model_accuracy",
        "model_score",
        "predicted_reference_sign",
        "observed_reference_sign",
        "test_shift_period",
        "gate_scale",
        "candidate_effect",
    )
    for key in keys:
        if key in record:
            lines.append(f"- {key}: **{record[key]}**")
    if "validated" in record:
        lines.append(f"- Validated: **{record['validated']}**")
    lines.extend(["", "Top arms:"])
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
            f"incumbent {float(arm_metrics['early_incumbent_share']):.6f}; "
            f"feasible {bool(arm['feasible'])}"
        )
    return "\n".join(lines) + "\n"


def render_synthesis(checkpoint: Mapping[str, object]) -> str:
    return "\n".join(
        [
            "<!-- two-timescale-053-062:synthesis -->",
            "## Two-Timescale Campaign 053–062 — Final Synthesis",
            "",
            f"- Commit: `{checkpoint['code_sha']}`",
            f"- Config hash: `{checkpoint['config_hash']}`",
            f"- Measurements: `{checkpoint['measurements']}`",
            f"- Model: `{checkpoint['model']}`",
            f"- Model test validated: **{bool(checkpoint['model_test_validated'])}**",
            f"- Derived mechanism validated: **{bool(checkpoint['mechanism_validated'])}**",
            f"- Candidate policy: `{checkpoint['candidate_policy']}`",
            f"- Replication validated: **{bool(checkpoint['replication_validated'])}**",
            f"- Holdout validated: **{bool(checkpoint['validated'])}**",
            "- Experiments completed: **10**",
            "",
            "Each experiment has its own checkpoint and raw real-market evidence artifact.",
        ]
    ) + "\n"


def write_step_artifacts(
    connection: Connection[Any],
    *,
    config: TwoTimescaleConfig,
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
    (destination / "checkpoint.json").write_text(
        json.dumps(dict(checkpoint), indent=2, sort_keys=True) + "\n"
    )
    (destination / "notebook.md").write_text(
        render_experiment_comment(record, config_hash=config_hash, code_sha=code_sha)
    )
    if int(record["number"]) == 62:
        (destination / "campaign-summary.md").write_text(render_synthesis(checkpoint))
