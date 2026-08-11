"""Notebook and artifacts for Capability Decay Experiments 081–086."""

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
    lines = [
        f"<!-- capability-decay-081-086:experiment-{number:03d} -->",
        f"## Experiment {number:03d} — completed",
        "",
        f"**Question:** {record['question']}",
        "",
        f"- Focus: `{record['focus']}`",
        f"- Selected arm: `{record['selected_label']}`",
        f"- Success: **{float(metrics['success_rate']):.6f}**",
        f"- Logical incumbent share: **{float(metrics['early_incumbent_share']):.6f}**",
        f"- Winner HHI: **{float(metrics['mean_winner_hhi']):.6f}**",
        (
            "- Late public knowledge coverage: "
            f"**{float(metrics['late_public_knowledge_coverage']):.6f}**"
        ),
        f"- Dormant effective/cumulative ratio: **{float(metrics['dormant_effective_ratio']):.6f}**",
        f"- Effective-practice Gini: **{float(metrics['mean_effective_practice_gini']):.6f}**",
        f"- Skill-rank turnover: **{float(metrics['skill_rank_turnover']):.6f}**",
        f"- Winner effective advantage: **{float(metrics['mean_winner_effective_advantage']):.6f}**",
        f"- Incumbent refresh feedback: **{float(metrics['incumbent_refresh_feedback']):.6f}**",
        f"- tau_F: **{float(metrics['tau_f']):.3f}**",
        f"- tau_D_assoc: **{float(metrics['tau_d_assoc']):.3f}**",
        f"- tau_visit: **{float(metrics['tau_visit']):.3f}**",
        f"- tau_D_skill: **{float(metrics['tau_d_skill']):.3f}**",
        f"- empirical tau_D_skill: **{float(metrics['tau_d_skill_empirical']):.3f}**",
        f"- Clock window inside: **{bool(float(metrics['clock_window_inside']))}**",
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
        "dormant_erosion",
        "skill_rank_turnover_effect",
        "refresh_feedback_effect",
        "screen_validated",
        "decomposition_validated",
        "response_validated",
        "rapid_shift_validated",
        "replication_validated",
        "passing_settings",
        "clock_prediction_inside",
        "clock_prediction_agreement",
        "holdout_observed_healthy",
    ):
        if name in record:
            lines.append(f"- {name}: **{record[name]}**")
    if "selected_decay" in record:
        lines.append(f"- Selected decay: `{record['selected_decay']}`")
    if "clock_reference" in record:
        lines.append(f"- Clock reference: `{record['clock_reference']}`")
    if "prediction_clocks" in record:
        lines.append(f"- Prediction clocks: `{record['prediction_clocks']}`")

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
        lines.append(
            f"- `{arm['label']}` — success {_metric(arm, 'success_rate'):.6f}; "
            f"logical incumbent {_metric(arm, 'early_incumbent_share'):.6f}; "
            f"HHI {_metric(arm, 'mean_winner_hhi'):.6f}; "
            f"late knowledge {_metric(arm, 'late_public_knowledge_coverage'):.6f}; "
            f"dormant ratio {_metric(arm, 'dormant_effective_ratio'):.6f}; "
            f"tau_skill {_metric(arm, 'tau_d_skill_empirical'):.3f}; "
            f"feasible {arm.get('feasible', 'n/a')}; "
            f"hard gate {arm.get('hard_gate', 'n/a')}; "
            f"utility {arm.get('utility', 'n/a')}"
        )
    return "\n".join(lines) + "\n"


def render_synthesis(checkpoint: Mapping[str, object]) -> str:
    validated = bool(checkpoint.get("validated"))
    if validated:
        conclusion = (
            "Capability decay survived the full discovery gate. Under the tested conditions, "
            "perishable private skill is sufficient to increase organizational plasticity while "
            "preserving identity and public knowledge."
        )
    else:
        conclusion = (
            "Capability decay did not survive the full discovery gate. Treat this as a null result "
            "for the tested capability-memory family and move next to endogenous allocation "
            "topology / task-exposure reinforcement rather than another decay-rate sweep."
        )
    lines = [
        "<!-- capability-decay-081-086:synthesis -->",
        "## Capability Decay Campaign 081–086 — Final Synthesis",
        "",
        f"- Commit: `{checkpoint['code_sha']}`",
        f"- Config hash: `{checkpoint['config_hash']}`",
        f"- Selected decay: `{checkpoint.get('selected_decay')}`",
        f"- Screen gate: **{bool(checkpoint.get('screen_validated'))}**",
        f"- Decomposition gate: **{bool(checkpoint.get('decomposition_validated'))}**",
        f"- Bounded-response gate: **{bool(checkpoint.get('response_validated'))}**",
        f"- Rapid-shift gate: **{bool(checkpoint.get('rapid_shift_validated'))}**",
        f"- Independent replication: **{bool(checkpoint.get('replication_validated'))}**",
        f"- Clock prediction inside window: **{bool(checkpoint.get('clock_prediction_inside'))}**",
        (
            "- Clock prediction agreement: "
            f"**{bool(checkpoint.get('clock_prediction_agreement'))}**"
        ),
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
    if int(record["number"]) == 86:
        (output / "campaign-summary.md").write_text(render_synthesis(checkpoint))
