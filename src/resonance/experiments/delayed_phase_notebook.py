"""Notebook rendering for Delayed-Onset Phase Observability Experiments 111–116."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _records_table(records: Sequence[Mapping[str, object]]) -> list[str]:
    if not records:
        return []
    lines = [
        "",
        "Seed-level pairs:",
        "",
        "| Seed | Exact | State exact | ΔI | Δsuccess | Δknowledge |",
        "|---:|---|---|---:|---:|---:|",
    ]
    for record in records:
        delta = record.get("delta_incumbency")
        success = record.get("success_effect")
        knowledge = record.get("knowledge_effect")
        lines.append(
            f"| {record['seed']} | {bool(record['preactivation_exact'])} | "
            f"{bool(record['state_features_exact'])} | "
            f"{_fmt(delta) if delta is not None else 'n/a'} | "
            f"{_fmt(success) if success is not None else 'n/a'} | "
            f"{_fmt(knowledge) if knowledge is not None else 'n/a'} |"
        )
    return lines


def render_record(record: Mapping[str, object]) -> str:
    number = int(record["number"])
    lines = [
        f"<!-- delayed-phase-111-116:experiment-{number:03d} -->",
        f"## Experiment {number:03d} — completed",
        "",
        f"**Question:** {record['question']}",
        "",
        f"- Focus: `{record['focus']}`",
        f"- Validated: **{bool(record['validated'])}**",
        f"- Next focus: `{record.get('next_experiment_focus')}`",
    ]
    ordered = (
        "equivalence_validated",
        "activation_cycle",
        "seed_count",
        "positive_signs",
        "negative_signs",
        "neutral_signs",
        "delta_min",
        "delta_max",
        "delta_mean",
        "heterogeneity_gate",
        "integrity",
        "success_effect",
        "knowledge_effect",
        "quality_gate",
        "heterogeneity_validated",
        "phase_condition_selected",
        "conclusion",
        "classifier_available",
        "feature",
        "threshold",
        "direction",
        "accuracy",
        "balanced_accuracy",
        "predicted_lock_in_count",
        "observed_lock_in_count",
        "predicted_lock_in_mean_delta",
        "predicted_plasticity_mean_delta",
        "directional_separation",
        "validation_gate",
        "replication_validated",
        "timing_transfer_validated",
        "holdout_validated",
        "prospective_phase_condition",
    )
    for key in ordered:
        if key in record:
            lines.append(f"- {key}: **{_fmt(record[key])}**")

    classifier = record.get("classifier")
    if isinstance(classifier, Mapping):
        lines.extend(
            [
                "",
                "Frozen classifier:",
                f"- feature: `{classifier['feature']}`",
                f"- direction: `{classifier['direction']}`",
                f"- threshold: `{float(classifier['threshold']):.6f}`",
                f"- discovery LOO balanced accuracy: `{float(classifier['loo_balanced_accuracy']):.6f}`",
                f"- discovery family-wise p: `{float(classifier['familywise_permutation_p']):.6f}`",
            ]
        )

    evaluations = record.get("evaluations")
    if isinstance(evaluations, Sequence) and evaluations:
        lines.extend(
            [
                "",
                "Discovery feature tests:",
                "",
                "| Feature | ρ(ΔI) | LOO accuracy | LOO balanced | FWER p | Stable | Qualifies |",
                "|---|---:|---:|---:|---:|---|---|",
            ]
        )
        for item in evaluations:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"| `{item['feature']}` | {float(item['spearman_delta_incumbency']):+.3f} | "
                f"{float(item['loo_accuracy']):.3f} | {float(item['loo_balanced_accuracy']):.3f} | "
                f"{float(item['familywise_permutation_p']):.3f} | "
                f"{bool(item['loo_direction_stable'])} | {bool(item['qualifies'])} |"
            )

    records = record.get("records")
    if isinstance(records, Sequence):
        clean = [item for item in records if isinstance(item, Mapping)]
        lines.extend(_records_table(clean))
    return "\n".join(lines) + "\n"


def render_synthesis(checkpoint: Mapping[str, object]) -> str:
    validated = bool(checkpoint.get("prospective_phase_condition"))
    classifier = checkpoint.get("classifier")
    if validated and isinstance(classifier, Mapping):
        conclusion = (
            "A preregistered scalar pre-treatment phase condition survived discovery, independent "
            "replication, activation-time transfer, and unseen-environment holdout. The external-boundary "
            "architecture may now be updated with this frozen state crossing prediction, but the boundary "
            "experiment remains separately preregistered and unexecuted."
        )
    elif isinstance(classifier, Mapping):
        conclusion = (
            "A discovery phase threshold was found but failed at least one prospective validation gate. "
            "Preserve it as a failed hypothesis and do not retune. Instantaneous scalar state observability "
            "is not established."
        )
    else:
        conclusion = (
            "No preregistered scalar state variable localized a prospective phase condition. Do not search "
            "additional thresholds. The next scientific model should represent trajectory/history or hysteresis "
            "explicitly before executing the external-boundary architecture."
        )
    lines = [
        "<!-- delayed-phase-111-116:synthesis -->",
        "## Delayed-Onset Phase Observability Campaign 111–116 — Final Synthesis",
        "",
        f"- Commit: `{checkpoint['code_sha']}`",
        f"- Config hash: `{checkpoint['config_hash']}`",
        f"- Equivalence: **{bool(checkpoint.get('equivalence_validated'))}**",
        f"- Discovery heterogeneity: **{bool(checkpoint.get('heterogeneity_validated'))}**",
        f"- Phase condition selected: **{bool(checkpoint.get('phase_condition_selected'))}**",
        f"- Independent replication: **{bool(checkpoint.get('replication_validated'))}**",
        f"- Activation-time transfer: **{bool(checkpoint.get('timing_transfer_validated'))}**",
        f"- Unseen holdout / full prospective phase condition: **{validated}**",
        "- Experiments completed: **6**",
    ]
    if isinstance(classifier, Mapping):
        lines.extend(
            [
                f"- Frozen feature: `{classifier['feature']}`",
                f"- Frozen direction: `{classifier['direction']}`",
                f"- Frozen threshold: `{float(classifier['threshold']):.6f}`",
            ]
        )
    lines.extend(["", conclusion, "", "Production behavior remains unchanged and reputation-neutral."])
    return "\n".join(lines) + "\n"


def render_boundary_update(checkpoint: Mapping[str, object]) -> str:
    classifier = checkpoint.get("classifier")
    validated = bool(checkpoint.get("prospective_phase_condition"))
    lines = [
        "<!-- external-boundary:delayed-phase-111-116 -->",
        "## Delayed-onset phase-observability dependency",
        "",
        "Source: #44.",
        "",
    ]
    if validated and isinstance(classifier, Mapping):
        side = "at or above" if classifier["direction"] == "positive_if_high" else "at or below"
        lines.extend(
            [
                "A prospective scalar phase condition **validated** across discovery, replication, timing transfer, and holdout.",
                "",
                f"- State variable: `{classifier['feature']}`",
                f"- Threshold: `{float(classifier['threshold']):.6f}`",
                f"- Lock-in side: {side} the threshold",
                "- Internal mechanism: aligned endogenous demand feedback λ=0.5",
                "",
                "The external-boundary architecture may now preregister a causal state-crossing experiment using this fixed condition. This update does not itself authorize or launch that experiment.",
            ]
        )
    else:
        lines.extend(
            [
                "No prospective scalar phase condition validated under the frozen protocol.",
                "",
                "The external-boundary architecture remains blocked from execution. Do not search more scalar thresholds; first develop and preregister an explicit trajectory/hysteresis observable.",
            ]
        )
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
    if int(record["number"]) == 116:
        (output / "campaign-summary.md").write_text(render_synthesis(checkpoint))
        (output / "boundary-update.md").write_text(render_boundary_update(checkpoint))
