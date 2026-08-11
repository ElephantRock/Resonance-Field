"""Notebook and artifacts for Capability-Preserving Access Experiments 075–080."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path


def _selected_arm(record: Mapping[str, object]) -> Mapping[str, object]:
    arms = record["arms"]
    assert isinstance(arms, Sequence)
    selected_label = str(record["selected_label"])
    for arm in arms:
        assert isinstance(arm, Mapping)
        if str(arm["label"]) == selected_label:
            return arm
    raise ValueError(f"selected arm {selected_label!r} is missing from record")


def _metric(arm: Mapping[str, object], name: str) -> float:
    metrics = arm["metrics"]
    assert isinstance(metrics, Mapping)
    return float(metrics[name])


def render_record(record: Mapping[str, object]) -> str:
    number = int(record["number"])
    selected = _selected_arm(record)
    metrics = selected["metrics"]
    invariants = selected["invariants"]
    assert isinstance(metrics, Mapping) and isinstance(invariants, Mapping)
    late_knowledge = metrics.get(
        "late_public_knowledge_coverage",
        metrics["public_knowledge_coverage"],
    )
    lines = [
        f"<!-- access-075-080:experiment-{number:03d} -->",
        f"## Experiment {number:03d} — completed",
        "",
        f"**Question:** {record['question']}",
        "",
        f"- Focus: `{record['focus']}`",
        f"- Selected arm: `{record['selected_label']}`",
        f"- Success: **{float(metrics['success_rate']):.6f}**",
        f"- Logical incumbent share: **{float(metrics['early_incumbent_share']):.6f}**",
        f"- Winner HHI: **{float(metrics['mean_winner_hhi']):.6f}**",
        f"- Late public knowledge coverage: **{float(late_knowledge):.6f}**",
        f"- Exit count: **{float(metrics['exit_count']):.2f}**",
        f"- Hard invariants: **{all(bool(value) for value in invariants.values())}**",
        f"- Validated: **{bool(record['validated'])}**",
        f"- Next focus: `{record.get('next_experiment_focus')}`",
    ]
    for name in (
        "success_effect",
        "logical_incumbent_reduction",
        "identity_incumbent_reduction",
        "hhi_reduction",
        "knowledge_effect",
        "cultural_hhi_reduction",
        "screen_validated",
        "decomposition_validated",
        "response_validated",
        "rapid_shift_validated",
        "replication_validated",
        "passing_settings",
    ):
        if name in record:
            lines.append(f"- {name}: **{record[name]}**")
    if "selected_mechanism" in record:
        lines.append(f"- Selected mechanism: `{record['selected_mechanism']}`")
    if "holdout_mechanism" in record:
        lines.append(f"- Holdout mechanism: `{record['holdout_mechanism']}`")

    lines.extend(["", "Arms:"])
    arms = record["arms"]
    assert isinstance(arms, Sequence)
    ranked = sorted(
        arms,
        key=lambda arm: (
            bool(arm.get("hard_gate", False)),
            float(arm.get("utility", -1e9)),
            str(arm.get("label", "")),
        ),
        reverse=True,
    )
    for arm in ranked:
        assert isinstance(arm, Mapping)
        arm_metrics = arm["metrics"]
        assert isinstance(arm_metrics, Mapping)
        arm_late_knowledge = float(
            arm_metrics.get(
                "late_public_knowledge_coverage",
                arm_metrics["public_knowledge_coverage"],
            )
        )
        lines.append(
            f"- `{arm['label']}` — success {_metric(arm, 'success_rate'):.6f}; "
            f"logical incumbent {_metric(arm, 'early_incumbent_share'):.6f}; "
            f"HHI {_metric(arm, 'mean_winner_hhi'):.6f}; "
            f"late knowledge {arm_late_knowledge:.6f}; "
            f"feasible {arm.get('feasible', 'n/a')}; "
            f"hard gate {arm.get('hard_gate', 'n/a')}; "
            f"utility {arm.get('utility', 'n/a')}"
        )
    return "\n".join(lines) + "\n"


def render_synthesis(checkpoint: Mapping[str, object]) -> str:
    validated = bool(checkpoint.get("validated"))
    conclusion = (
        "A capability-preserving access mechanism survived the full discovery gate."
        if validated
        else (
            "No capability-preserving access mechanism survived the full discovery gate. "
            "Per the predeclared hard stop, retire succession/access-control as the anti-lock-in "
            "research family rather than extending it with further parameter sweeps."
        )
    )
    lines = [
        "<!-- access-075-080:synthesis -->",
        "## Capability-Preserving Access Campaign 075–080 — Final Synthesis",
        "",
        f"- Commit: `{checkpoint['code_sha']}`",
        f"- Config hash: `{checkpoint['config_hash']}`",
        f"- Selected mechanism: `{checkpoint.get('selected_mechanism')}`",
        f"- Screen gate: **{bool(checkpoint.get('screen_validated'))}**",
        f"- Decomposition gate: **{bool(checkpoint.get('decomposition_validated'))}**",
        f"- Bounded-response gate: **{bool(checkpoint.get('response_validated'))}**",
        f"- Rapid-shift gate: **{bool(checkpoint.get('rapid_shift_validated'))}**",
        f"- Independent replication: **{bool(checkpoint.get('replication_validated'))}**",
        f"- Holdout validated: **{validated}**",
        "- Experiments completed: **6**",
        "",
        conclusion,
        "",
        "Production remains reputation-neutral regardless of campaign outcome.",
    ]
    return "\n".join(lines) + "\n"


def write_step_artifacts(
    destination: str | Path,
    *,
    record: Mapping[str, object],
    checkpoint: Mapping[str, object],
) -> None:
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    (output / "experiment.json").write_text(
        json.dumps(record, indent=2, sort_keys=True, default=str)
    )
    (output / "checkpoint.json").write_text(
        json.dumps(checkpoint, indent=2, sort_keys=True, default=str)
    )
    (output / "notebook.md").write_text(render_record(record))
    if int(record["number"]) == 80:
        (output / "campaign-summary.md").write_text(render_synthesis(checkpoint))
