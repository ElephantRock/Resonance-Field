"""Notebook and artifacts for Demand-Structure Experiments 099–104."""

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
    late_knowledge = metrics.get("late_public_knowledge_coverage", metrics.get("public_knowledge_coverage", 0.0))
    lines = [
        f"<!-- demand-structure-099-104:experiment-{number:03d} -->",
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
        f"- Demand adjacent-repeat rate: **{float(metrics['demand_adjacent_repeat_rate']):.6f}**",
        f"- Demand mean run length: **{float(metrics['demand_mean_run_length']):.6f}**",
        f"- Demand order changed rate: **{float(metrics['demand_order_changed_rate']):.6f}**",
        f"- Exit count: **{float(metrics.get('exit_count', 0.0)):.2f}**",
        f"- Hard invariants: **{all(bool(value) for value in invariants.values())}**",
        f"- Validated: **{bool(record['validated'])}**",
        f"- Next focus: `{record.get('next_experiment_focus')}`",
    ]
    for name in (
        "success_effect", "logical_incumbent_reduction", "identity_incumbent_reduction",
        "hhi_reduction", "knowledge_effect", "persistence_reduction", "run_length_reduction",
        "order_changed_rate", "screen_validated", "decomposition_validated",
        "exact_task_multiset_validated", "response_validated", "persistence_span",
        "logical_span", "persistence_order_consistent", "reversal_validated",
        "unlock_winner_repeat_change", "relock_winner_repeat_rebound", "replication_validated",
        "relock_predicted", "relock_observed", "relock_prediction_agreement",
        "restoration_winner_rebound", "strong_demand_causal",
    ):
        if name in record:
            lines.append(f"- {name}: **{record[name]}**")
    if "selected_schedule" in record:
        lines.append(f"- Selected schedule: `{record['selected_schedule']}`")
    lines.extend(["", "Arms:"])
    arms = record["arms"]
    assert isinstance(arms, Sequence)
    ranked = sorted(
        arms,
        key=lambda arm: (bool(arm.get("hard_gate", False)), float(arm.get("utility", -1e9)), str(arm.get("label", ""))),
        reverse=True,
    )
    for arm in ranked:
        assert isinstance(arm, Mapping)
        arm_metrics = arm["metrics"]
        assert isinstance(arm_metrics, Mapping)
        arm_late_knowledge = float(arm_metrics.get("late_public_knowledge_coverage", arm_metrics.get("public_knowledge_coverage", 0.0)))
        lines.append(
            f"- `{arm['label']}` — success {_metric(arm, 'success_rate'):.6f}; "
            f"logical incumbent {_metric(arm, 'early_incumbent_share'):.6f}; "
            f"demand repeat {_metric(arm, 'demand_adjacent_repeat_rate'):.6f}; "
            f"run length {_metric(arm, 'demand_mean_run_length'):.6f}; "
            f"HHI {_metric(arm, 'mean_winner_hhi'):.6f}; late knowledge {arm_late_knowledge:.6f}; "
            f"feasible {arm.get('feasible', 'n/a')}; hard gate {arm.get('hard_gate', 'n/a')}; utility {arm.get('utility', 'n/a')}"
        )
    return "\n".join(lines) + "\n"


def render_synthesis(checkpoint: Mapping[str, object]) -> str:
    validated = bool(checkpoint.get("validated"))
    strong = bool(checkpoint.get("strong_demand_causal"))
    if validated and strong:
        conclusion = (
            "Demand ordering survived the full discovery gate. Reordering the same exogenous task packets was sufficient to increase organizational plasticity, and restoring clustered demand recreated winner reinforcement without resetting agents. Under the tested conditions, temporal demand structure is a primary carrier of organizational path dependence."
        )
    elif validated:
        conclusion = (
            "Demand ordering survived the full discovery gate. Reordering the same task multiset is sufficient to materially increase organizational plasticity under the tested conditions; the stronger clustering re-lock result remained inconclusive."
        )
    else:
        conclusion = (
            "The exogenous demand-order family did not survive the full discovery gate. Preserve this null and move next to endogenous demand feedback—completed work changing future task generation—rather than returning to agent-state, access, topology, matching-objective, or exogenous-order sweeps."
        )
    lines = [
        "<!-- demand-structure-099-104:synthesis -->",
        "## Demand-Structure Campaign 099–104 — Final Synthesis",
        "",
        f"- Commit: `{checkpoint['code_sha']}`",
        f"- Config hash: `{checkpoint['config_hash']}`",
        f"- Selected schedule: `{checkpoint.get('selected_schedule')}`",
        f"- Screen gate: **{bool(checkpoint.get('screen_validated'))}**",
        f"- Exact-task decomposition: **{bool(checkpoint.get('decomposition_validated'))}**",
        f"- Persistence-response gate: **{bool(checkpoint.get('response_validated'))}**",
        f"- Within-run reversal: **{bool(checkpoint.get('reversal_validated'))}**",
        f"- Independent replication: **{bool(checkpoint.get('replication_validated'))}**",
        f"- Holdout validated: **{validated}**",
        f"- Strong demand-causal result: **{strong}**",
        "- Experiments completed: **6**",
        "",
        conclusion,
        "",
        "Production behavior remains unchanged and reputation-neutral regardless of campaign outcome.",
    ]
    return "\n".join(lines) + "\n"


def write_step_artifacts(destination: str | Path, *, record: Mapping[str, object], checkpoint: Mapping[str, object]) -> None:
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    (output / "experiment.json").write_text(json.dumps(record, indent=2, sort_keys=True, default=str))
    (output / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2, sort_keys=True, default=str))
    (output / "notebook.md").write_text(render_record(record))
    if int(record["number"]) == 104:
        (output / "campaign-summary.md").write_text(render_synthesis(checkpoint))
