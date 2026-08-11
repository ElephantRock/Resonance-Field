"""Notebook and artifacts for Matching Objective Experiments 093–098."""

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
        f"<!-- matching-objective-093-098:experiment-{number:03d} -->",
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
        f"- Objective override rate: **{float(metrics['objective_override_rate']):.6f}**",
        f"- Same-bid logical improvement: **{float(metrics['same_bid_logical_improvement']):.6f}**",
        f"- Baseline replay incumbent share: **{float(metrics['baseline_replay_incumbent_share']):.6f}**",
        f"- Objective replay incumbent share: **{float(metrics['objective_replay_incumbent_share']):.6f}**",
        f"- Objective replay exact rate: **{float(metrics['objective_replay_exact_rate']):.6f}**",
        f"- Selected max-confidence share: **{float(metrics['selected_max_confidence_share']):.6f}**",
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
        "objective_override_rate",
        "same_bid_logical_improvement",
        "selected_confidence_reduction",
        "max_confidence_selection_reduction",
        "screen_validated",
        "decomposition_validated",
        "same_bid_causal_validated",
        "response_validated",
        "rapid_shift_validated",
        "reversal_validated",
        "replication_validated",
        "passing_settings",
        "restore_after_cycle",
        "pre_restore_objective_override_rate",
        "post_restore_objective_override_rate",
        "restoration_winner_rebound",
        "relock_predicted",
        "relock_observed",
        "relock_prediction_agreement",
        "strong_matching_causal",
    ):
        if name in record:
            lines.append(f"- {name}: **{record[name]}**")
    if "selected_objective" in record:
        lines.append(f"- Selected objective: `{record['selected_objective']}`")

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
            f"same-bid improvement {_metric(arm, 'same_bid_logical_improvement'):.6f}; "
            f"override {_metric(arm, 'objective_override_rate'):.6f}; "
            f"HHI {_metric(arm, 'mean_winner_hhi'):.6f}; "
            f"late knowledge {arm_late_knowledge:.6f}; "
            f"feasible {arm.get('feasible', 'n/a')}; "
            f"hard gate {arm.get('hard_gate', 'n/a')}; "
            f"utility {arm.get('utility', 'n/a')}"
        )
    return "\n".join(lines) + "\n"


def render_synthesis(checkpoint: Mapping[str, object]) -> str:
    validated = bool(checkpoint.get("validated"))
    strong = bool(checkpoint.get("strong_matching_causal"))
    if validated and strong:
        conclusion = (
            "The matching objective survived the full discovery gate, exact-bid replay localized "
            "the effect to the assignment function, and restoring the baseline objective recreated "
            "lock-in without restoring prior agent state. Under the tested conditions, this is "
            "strong causal evidence that the assignment rule is a primary carrier of organizational memory."
        )
    elif validated:
        conclusion = (
            "The matching objective survived the full discovery gate. Changing only the sealed-bid "
            "assignment function is sufficient to materially increase plasticity under the tested "
            "conditions; the stronger restoration/re-lock result remained inconclusive."
        )
    else:
        conclusion = (
            "The matching-objective family did not survive the full discovery gate. Preserve this "
            "null and move next to task-generation / endogenous-demand structure rather than returning "
            "to identity, reputation, access, capability-decay, candidate-topology, or objective sweeps."
        )
    lines = [
        "<!-- matching-objective-093-098:synthesis -->",
        "## Matching Objective Campaign 093–098 — Final Synthesis",
        "",
        f"- Commit: `{checkpoint['code_sha']}`",
        f"- Config hash: `{checkpoint['config_hash']}`",
        f"- Selected objective: `{checkpoint.get('selected_objective')}`",
        f"- Screen gate: **{bool(checkpoint.get('screen_validated'))}**",
        f"- Decomposition gate: **{bool(checkpoint.get('decomposition_validated'))}**",
        f"- Exact-bid causal replay: **{bool(checkpoint.get('same_bid_causal_validated'))}**",
        f"- Bounded-response gate: **{bool(checkpoint.get('response_validated'))}**",
        f"- Rapid-shift gate: **{bool(checkpoint.get('rapid_shift_validated'))}**",
        f"- Baseline-objective restoration re-lock: **{bool(checkpoint.get('reversal_validated'))}**",
        f"- Independent replication: **{bool(checkpoint.get('replication_validated'))}**",
        f"- Holdout validated: **{validated}**",
        f"- Strong matching-causal result: **{strong}**",
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
    if int(record["number"]) == 98:
        (output / "campaign-summary.md").write_text(render_synthesis(checkpoint))
