"""Notebook and artifacts for Endogenous Demand Feedback Experiments 105–110."""

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
        f"<!-- endogenous-demand-105-110:experiment-{number:03d} -->",
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
        f"- Feedback branch rate: **{float(metrics['feedback_branch_rate']):.6f}**",
        f"- Feedback override rate: **{float(metrics['feedback_override_rate']):.6f}**",
        (
            "- Success→same-domain follow-on alignment: "
            f"**{float(metrics['success_same_domain_follow_on_alignment']):.6f}**"
        ),
        f"- Generated-demand HHI: **{float(metrics['generated_demand_hhi']):.6f}**",
        f"- Demand adjacent-repeat rate: **{float(metrics['demand_adjacent_repeat_rate']):.6f}**",
        f"- Exit count: **{float(metrics.get('exit_count', 0.0)):.2f}**",
        f"- Hard invariants: **{all(bool(value) for value in invariants.values())}**",
        f"- Validated: **{bool(record['validated'])}**",
        f"- Next focus: `{record.get('next_experiment_focus')}`",
    ]
    for name in (
        "success_effect",
        "logical_incumbent_increase",
        "identity_incumbent_increase",
        "hhi_reduction",
        "knowledge_effect",
        "feedback_override_effect",
        "alignment_effect",
        "screen_validated",
        "decomposition_validated",
        "aligned_logical_increase",
        "permuted_logical_increase",
        "specificity_direction_validated",
        "response_validated",
        "activation_monotone",
        "logical_non_decreasing",
        "logical_span",
        "reversal_validated",
        "disable_logical_change",
        "restore_logical_rebound",
        "disable_winner_repeat_change",
        "restore_winner_repeat_rebound",
        "feedback_temporal_precedence",
        "replication_validated",
        "active_lock_in_predicted",
        "active_lock_in_observed",
        "relock_predicted",
        "relock_observed",
        "prediction_agreement",
        "strong_endogenous_demand_causal",
        "selected_strength",
    ):
        if name in record:
            lines.append(f"- {name}: **{record[name]}**")
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
        arm_late = float(
            arm_metrics.get(
                "late_public_knowledge_coverage",
                arm_metrics.get("public_knowledge_coverage", 0.0),
            )
        )
        lines.append(
            f"- `{arm['label']}` — success {_metric(arm, 'success_rate'):.6f}; "
            f"logical incumbent {_metric(arm, 'early_incumbent_share'):.6f}; "
            f"feedback override {_metric(arm, 'feedback_override_rate'):.6f}; "
            f"alignment {_metric(arm, 'success_same_domain_follow_on_alignment'):.6f}; "
            f"demand HHI {_metric(arm, 'generated_demand_hhi'):.6f}; "
            f"winner HHI {_metric(arm, 'mean_winner_hhi'):.6f}; "
            f"late knowledge {arm_late:.6f}; "
            f"feasible {arm.get('feasible', 'n/a')}; "
            f"hard gate {arm.get('hard_gate', 'n/a')}; utility {arm.get('utility', 'n/a')}"
        )
    return "\n".join(lines) + "\n"


def render_synthesis(checkpoint: Mapping[str, object]) -> str:
    validated = bool(checkpoint.get("validated"))
    strong = bool(checkpoint.get("strong_endogenous_demand_causal"))
    if validated and strong:
        conclusion = (
            "The success-reinforced endogenous-demand loop survived the full discovery gate. "
            "Under the tested conditions, completed work can reshape future demand in a way that "
            "reconstructs organizational incumbency: the organization participates in producing "
            "the environment that subsequently selects it."
        )
    elif validated:
        conclusion = (
            "The endogenous-demand family survived the preregistered discovery chain, but the "
            "stronger on/off/on re-lock interpretation remained incomplete."
        )
    else:
        conclusion = (
            "The preregistered success-reinforced endogenous-demand family did not survive the "
            "full discovery gate. Preserve this null. Do not run another feedback-strength sweep "
            "or return to retired identity, reputation, access, capability, topology, matching, "
            "or exogenous-order families; perform a fresh causal audit."
        )
    lines = [
        "<!-- endogenous-demand-105-110:synthesis -->",
        "## Endogenous Demand Feedback Campaign 105–110 — Final Synthesis",
        "",
        f"- Commit: `{checkpoint['code_sha']}`",
        f"- Config hash: `{checkpoint['config_hash']}`",
        f"- Selected feedback strength: `{checkpoint.get('selected_strength')}`",
        f"- Screen gate: **{bool(checkpoint.get('screen_validated'))}**",
        f"- Causal-link decomposition: **{bool(checkpoint.get('decomposition_validated'))}**",
        f"- Bounded strength response: **{bool(checkpoint.get('response_validated'))}**",
        f"- On/off/on reversal: **{bool(checkpoint.get('reversal_validated'))}**",
        f"- Independent replication: **{bool(checkpoint.get('replication_validated'))}**",
        f"- Holdout validated: **{validated}**",
        f"- Strong endogenous-demand causal result: **{strong}**",
        "- Experiments completed: **6**",
        "",
        conclusion,
        "",
        "Production behavior remains unchanged and reputation-neutral regardless of campaign outcome.",
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
    if int(record["number"]) == 110:
        (output / "campaign-summary.md").write_text(render_synthesis(checkpoint))
