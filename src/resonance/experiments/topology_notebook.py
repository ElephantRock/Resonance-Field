"""Notebook and artifacts for Coordination Topology Experiments 087–092."""

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
        metrics.get("public_knowledge_coverage", 0.0),
    )
    lines = [
        f"<!-- topology-087-092:experiment-{number:03d} -->",
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
        f"- Incumbent opportunity share: **{float(metrics['incumbent_opportunity_share']):.6f}**",
        f"- Opportunity-agent Gini: **{float(metrics['opportunity_agent_gini']):.6f}**",
        f"- Opportunity edge HHI: **{float(metrics['opportunity_edge_hhi']):.6f}**",
        f"- Opportunity edge entropy: **{float(metrics['opportunity_edge_entropy']):.6f}**",
        f"- Opportunity repeat rate: **{float(metrics['opportunity_repeat_rate']):.6f}**",
        f"- Structured edge share: **{float(metrics['structured_edge_share']):.6f}**",
        f"- Exit count: **{float(metrics.get('exit_count', 0.0)):.2f}**",
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
        "incumbent_opportunity_reduction",
        "opportunity_gini_reduction",
        "opportunity_edge_hhi_reduction",
        "opportunity_repeat_reduction",
        "screen_validated",
        "decomposition_validated",
        "temporal_precedence_validated",
        "response_validated",
        "rapid_shift_validated",
        "reversal_validated",
        "replication_validated",
        "passing_settings",
        "restore_after_cycle",
        "restoration_opportunity_rebound",
        "restoration_winner_rebound",
        "relock_predicted",
        "relock_observed",
        "relock_prediction_agreement",
        "strong_coordination_causal",
    ):
        if name in record:
            lines.append(f"- {name}: **{record[name]}**")
    if "selected_topology" in record:
        lines.append(f"- Selected topology: `{record['selected_topology']}`")

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
                arm_metrics.get("public_knowledge_coverage", 0.0),
            )
        )
        lines.append(
            f"- `{arm['label']}` — success {_metric(arm, 'success_rate'):.6f}; "
            f"logical incumbent {_metric(arm, 'early_incumbent_share'):.6f}; "
            f"incumbent opportunity {_metric(arm, 'incumbent_opportunity_share'):.6f}; "
            f"opportunity Gini {_metric(arm, 'opportunity_agent_gini'):.6f}; "
            f"HHI {_metric(arm, 'mean_winner_hhi'):.6f}; "
            f"late knowledge {arm_late_knowledge:.6f}; "
            f"feasible {arm.get('feasible', 'n/a')}; "
            f"hard gate {arm.get('hard_gate', 'n/a')}; "
            f"utility {arm.get('utility', 'n/a')}"
        )
    return "\n".join(lines) + "\n"


def render_synthesis(checkpoint: Mapping[str, object]) -> str:
    validated = bool(checkpoint.get("validated"))
    strong = bool(checkpoint.get("strong_coordination_causal"))
    if validated and strong:
        conclusion = (
            "Coordination topology survived the full discovery gate, and restoring the baseline "
            "routing rule recreated lock-in without restoring prior agent state. Under the tested "
            "conditions, this is strong causal evidence that organizational lock-in is generated "
            "primarily by the coordination mechanism rather than persistent agent properties."
        )
    elif validated:
        conclusion = (
            "Coordination topology survived the full discovery gate. This establishes that changing "
            "only pre-award opportunity structure is sufficient to materially increase plasticity "
            "under the tested conditions; the stronger restoration/re-lock causal test remained "
            "inconclusive."
        )
    else:
        conclusion = (
            "Coordination topology did not survive the full discovery gate. Preserve this null and "
            "move next to task-generation / matching-objective structure rather than returning to "
            "identity, reputation, access-penalty, or capability-decay sweeps."
        )
    lines = [
        "<!-- topology-087-092:synthesis -->",
        "## Coordination Topology Campaign 087–092 — Final Synthesis",
        "",
        f"- Commit: `{checkpoint['code_sha']}`",
        f"- Config hash: `{checkpoint['config_hash']}`",
        f"- Selected topology: `{checkpoint.get('selected_topology')}`",
        f"- Screen gate: **{bool(checkpoint.get('screen_validated'))}**",
        f"- Decomposition gate: **{bool(checkpoint.get('decomposition_validated'))}**",
        f"- Topology-before-allocation: **{bool(checkpoint.get('temporal_precedence_validated'))}**",
        f"- Bounded-response gate: **{bool(checkpoint.get('response_validated'))}**",
        f"- Rapid-shift gate: **{bool(checkpoint.get('rapid_shift_validated'))}**",
        f"- Baseline-restoration re-lock: **{bool(checkpoint.get('reversal_validated'))}**",
        f"- Independent replication: **{bool(checkpoint.get('replication_validated'))}**",
        f"- Holdout validated: **{validated}**",
        f"- Strong coordination-causal result: **{strong}**",
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
    if int(record["number"]) == 92:
        (output / "campaign-summary.md").write_text(render_synthesis(checkpoint))
