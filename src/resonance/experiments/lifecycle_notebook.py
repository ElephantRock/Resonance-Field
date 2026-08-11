"""Notebook and artifact rendering for Lifecycle & Succession Experiments 063–074."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path


def _metric(arm: Mapping[str, object], name: str) -> float:
    metrics = arm["metrics"]
    assert isinstance(metrics, Mapping)
    return float(metrics[name])


def render_record(record: Mapping[str, object]) -> str:
    number = int(record["number"])
    lines = [
        f"<!-- lifecycle-063-074:experiment-{number:03d} -->",
        f"## Experiment {number:03d} — completed",
        "",
        f"**Question:** {record['question']}",
        "",
        f"- Focus: `{record['focus']}`",
        f"- Selected arm: `{record['selected_label']}`",
        f"- Success: **{float(record['selected_metrics']['success_rate']):.6f}**",
        f"- Identity incumbent share: **{float(record['selected_metrics']['identity_early_incumbent_share']):.6f}**",
        f"- Winner HHI: **{float(record['selected_metrics']['mean_winner_hhi']):.6f}**",
        f"- Public knowledge coverage: **{float(record['selected_metrics']['public_knowledge_coverage']):.6f}**",
        f"- Cultural lineage HHI: **{float(record['selected_metrics']['cultural_lineage_hhi']):.6f}**",
        f"- Exit count: **{float(record['selected_metrics']['exit_count']):.2f}**",
        f"- Hard invariants: **{all(bool(v) for v in record['selected_invariants'].values())}**",
        f"- Next focus: `{record.get('next_focus')}`",
    ]
    if record.get("validated") is not None:
        lines.append(f"- Validated: **{bool(record['validated'])}**")
    extras = [
        "success_effect",
        "identity_incumbent_reduction",
        "hhi_reduction",
        "knowledge_effect",
        "exit_causal",
        "reputation_independent",
        "rapid_shift_validated",
        "synthesis_validated",
        "replication_validated",
        "diversification_selected",
        "death_minus_retirement_success",
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
        lines.append(
            f"- `{arm['label']}` — success {_metric(arm, 'success_rate'):.6f}; "
            f"identity incumbent {_metric(arm, 'identity_early_incumbent_share'):.6f}; "
            f"HHI {_metric(arm, 'mean_winner_hhi'):.6f}; "
            f"knowledge {_metric(arm, 'public_knowledge_coverage'):.6f}; "
            f"culture HHI {_metric(arm, 'cultural_lineage_hhi'):.6f}; "
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
