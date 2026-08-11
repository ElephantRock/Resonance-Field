"""Notebook and artifact rendering for Lifecycle & Succession Experiments 063–074."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path


def _metric(arm: Mapping[str, object], name: str) -> float:
    metrics = arm["metrics"]
    assert isinstance(metrics, Mapping)
    return float(metrics[name])


def _selected_arm(record: Mapping[str, object]) -> Mapping[str, object]:
    arms = record["arms"]
    assert isinstance(arms, Sequence)
    selected_label = str(record["selected_label"])
    for arm in arms:
        assert isinstance(arm, Mapping)
        if str(arm["label"]) == selected_label:
            return arm
    raise ValueError(f"selected arm {selected_label!r} is missing from record")


def render_record(record: Mapping[str, object]) -> str:
    number = int(record["number"])
    selected = _selected_arm(record)
    selected_metrics = selected["metrics"]
    selected_invariants = selected["invariants"]
    assert isinstance(selected_metrics, Mapping)
    assert isinstance(selected_invariants, Mapping)
    late_knowledge = selected_metrics.get(
        "late_public_knowledge_coverage",
        selected_metrics["public_knowledge_coverage"],
    )
    late_culture = selected_metrics.get(
        "late_cultural_lineage_hhi",
        selected_metrics["cultural_lineage_hhi"],
    )
    lines = [
        f"<!-- lifecycle-063-074:experiment-{number:03d} -->",
        f"## Experiment {number:03d} — completed",
        "",
        f"**Question:** {record['question']}",
        "",
        f"- Focus: `{record['focus']}`",
        f"- Selected arm: `{record['selected_label']}`",
        f"- Success: **{float(selected_metrics['success_rate']):.6f}**",
        f"- Logical-slot incumbent share: **{float(selected_metrics['early_incumbent_share']):.6f}**",
        f"- UUID incumbent share: **{float(selected_metrics['identity_early_incumbent_share']):.6f}**",
        f"- Winner HHI: **{float(selected_metrics['mean_winner_hhi']):.6f}**",
        f"- Late public knowledge coverage: **{float(late_knowledge):.6f}**",
        f"- Late cultural lineage HHI: **{float(late_culture):.6f}**",
        f"- Exit count: **{float(selected_metrics['exit_count']):.2f}**",
        f"- Hard invariants: **{all(bool(v) for v in selected_invariants.values())}**",
        f"- Next focus: `{record.get('next_experiment_focus')}`",
    ]
    if record.get("validated") is not None:
        lines.append(f"- Validated: **{bool(record['validated'])}**")
    extras = [
        "success_effect",
        "logical_incumbent_reduction",
        "identity_incumbent_reduction",
        "hhi_reduction",
        "knowledge_effect",
        "cultural_hhi_reduction",
        "exit_causal",
        "reputation_independent",
        "rapid_shift_validated",
        "synthesis_validated",
        "replication_validated",
        "diversification_selected",
        "death_minus_retirement_success",
        "retirement_consultation_weight",
    ]
    for name in extras:
        if name in record:
            lines.append(f"- {name}: **{record[name]}**")
    lines.extend(["", "Top arms:"])
    arms = record["arms"]
    assert isinstance(arms, Sequence)
    ranked = sorted(
        arms,
        key=lambda arm: (
            float(arm.get("utility", -1e9)),
            str(arm.get("label", "")),
        ),
        reverse=True,
    )
    for arm in ranked:
        assert isinstance(arm, Mapping)
        metrics = arm["metrics"]
        assert isinstance(metrics, Mapping)
        arm_late_knowledge = float(
            metrics.get("late_public_knowledge_coverage", metrics["public_knowledge_coverage"])
        )
        lines.append(
            f"- `{arm['label']}` — success {_metric(arm, 'success_rate'):.6f}; "
            f"logical incumbent {_metric(arm, 'early_incumbent_share'):.6f}; "
            f"UUID incumbent {_metric(arm, 'identity_early_incumbent_share'):.6f}; "
            f"HHI {_metric(arm, 'mean_winner_hhi'):.6f}; "
            f"late knowledge {arm_late_knowledge:.6f}; "
            f"feasible {arm.get('feasible', 'n/a')}; utility {arm.get('utility', 'n/a')}"
        )
    return "\n".join(lines) + "\n"


def render_synthesis(checkpoint: Mapping[str, object]) -> str:
    lifecycle = checkpoint.get("candidate_lifecycle")
    lines = [
        "<!-- lifecycle-063-074:synthesis -->",
        "## Lifecycle & Succession Campaign 063–074 — Final Synthesis",
        "",
        f"- Commit: `{checkpoint['code_sha']}`",
        f"- Config hash: `{checkpoint['config_hash']}`",
        f"- Exit causal: **{bool(checkpoint.get('exit_causal'))}**",
        f"- Selected exit mechanism: `{checkpoint.get('exit_mechanism')}`",
        f"- Reputation-independent effect: **{bool(checkpoint.get('reputation_independent'))}**",
        f"- Rapid-shift validation: **{bool(checkpoint.get('rapid_shift_validated'))}**",
        f"- Cultural diversification selected: **{bool(checkpoint.get('cultural_diversification_selected'))}**",
        f"- Candidate lifecycle: `{lifecycle}`",
        f"- Fast-learning synthesis validated: **{bool(checkpoint.get('synthesis_validated'))}**",
        f"- Independent replication: **{bool(checkpoint.get('replication_validated'))}**",
        f"- Holdout validated: **{bool(checkpoint.get('validated'))}**",
        "- Experiments completed: **12**",
        "",
        "The production market remains reputation-neutral regardless of campaign outcome.",
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
    (output / "experiment.json").write_text(json.dumps(record, indent=2, sort_keys=True, default=str))
    (output / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2, sort_keys=True, default=str))
    (output / "notebook.md").write_text(render_record(record))
    if int(record["number"]) == 74:
        (output / "campaign-summary.md").write_text(render_synthesis(checkpoint))
