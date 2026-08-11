"""Notebook and issue artifacts for Trajectory/Hysteresis Experiments 117–122."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path


def _history_summary(records: Sequence[Mapping[str, object]]) -> list[str]:
    histories = (
        "smooth_reference",
        "aligned_history",
        "counter_history",
        "annealed_history",
    )
    lines = [
        "| History | N | Mean ΔI | Positive | Neutral | Negative | Mean history override |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for history in histories:
        subset = [record for record in records if str(record.get("history_kind")) == history]
        deltas = [float(record["delta_incumbency"]) for record in subset if "delta_incumbency" in record]
        counts = Counter(
            "positive" if value > 0.005 else ("negative" if value < -0.005 else "neutral")
            for value in deltas
        )
        mean_delta = statistics.mean(deltas) if deltas else 0.0
        override = (
            statistics.mean(float(record.get("history_override_rate", 0.0)) for record in subset)
            if subset
            else 0.0
        )
        lines.append(
            f"| `{history}` | {len(subset)} | {mean_delta:+.6f} | "
            f"{counts['positive']} | {counts['neutral']} | {counts['negative']} | {override:.6f} |"
        )
    return lines


def render_record(record: Mapping[str, object]) -> str:
    number = int(record["number"])
    lines = [
        f"<!-- trajectory-hysteresis-117-122:experiment-{number:03d} -->",
        f"## Experiment {number:03d} — completed",
        "",
        f"**Question:** {record['question']}",
        "",
        f"- Focus: `{record['focus']}`",
        f"- Validated: **{bool(record['validated'])}**",
        f"- Next focus: `{record.get('next_experiment_focus')}`",
    ]
    keys = (
        "instrumentation_gate",
        "exact_pairing",
        "history_manipulation_material",
        "structured_support",
        "mean_path_length_gap",
        "basin_transition_discordance",
        "mean_momentum_gap",
        "trajectory_separation",
        "mean_absolute_effect_gap",
        "sign_discordance",
        "quality_gate",
        "hysteresis_gate",
        "annealing_support",
        "smooth_sign_concentration",
        "annealed_sign_concentration",
        "sign_concentration_gain",
        "smooth_sign_entropy",
        "annealed_sign_entropy",
        "sign_entropy_reduction",
        "annealing_gate",
        "discovery_hysteresis_validated",
        "discovery_annealing_validated",
        "trajectory_predictor_selected",
        "replication_validated",
        "replication_annealing_validated",
        "timing_validated",
        "timing_annealing_validated",
        "holdout_validated",
        "hysteresis_validated",
        "annealing_validated",
        "predictor_available",
        "predictor_feature",
        "predictor_accuracy",
        "predictor_balanced_accuracy",
        "predictor_directional_separation",
        "predictor_validation_gate",
        "conclusion",
    )
    for key in keys:
        if key in record:
            lines.append(f"- {key}: **{record[key]}**")

    if "history_intervention_rates" in record:
        lines.extend(["", "History intervention rates:"])
        rates = record["history_intervention_rates"]
        assert isinstance(rates, Mapping)
        for history, value in rates.items():
            lines.append(f"- `{history}`: **{float(value):.6f}**")

    if "evaluations" in record:
        evaluations = record["evaluations"]
        assert isinstance(evaluations, Sequence)
        lines.extend(
            [
                "",
                "Trajectory predictor tests:",
                "",
                "| Feature | ρ(ΔI) | LOO accuracy | LOO balanced | FWER p | Stable | Qualifies |",
                "|---|---:|---:|---:|---:|---|---|",
            ]
        )
        for item in evaluations:
            assert isinstance(item, Mapping)
            lines.append(
                f"| `{item['feature']}` | {float(item['spearman_delta_incumbency']):+.3f} | "
                f"{float(item['loo_accuracy']):.3f} | {float(item['loo_balanced_accuracy']):.3f} | "
                f"{float(item['familywise_permutation_p']):.3f} | "
                f"{bool(item['loo_direction_stable'])} | {bool(item['qualifies'])} |"
            )

    records = record.get("records")
    if isinstance(records, Sequence) and records:
        typed = [item for item in records if isinstance(item, Mapping)]
        lines.extend(["", "History-level outcomes:", "", *_history_summary(typed)])
    return "\n".join(lines) + "\n"


def render_synthesis(checkpoint: Mapping[str, object]) -> str:
    hysteresis = bool(checkpoint.get("hysteresis_validated"))
    annealing = bool(checkpoint.get("annealing_validated"))
    predictor = checkpoint.get("trajectory_predictor")
    if hysteresis and annealing:
        conclusion = (
            "Matched-endpoint history dependence survived discovery, replication, timing control, and "
            "holdout, and the preregistered annealing-consistency prediction also survived. The next "
            "campaign should be a dedicated noise/annealing campaign varying perturbation magnitude and "
            "correlation structure; do not return to retired mechanism sweeps."
        )
    elif hysteresis:
        conclusion = (
            "Matched-endpoint history dependence survived the full campaign, but the preregistered "
            "annealing-consistency prediction did not. The next model should retain explicit trajectory/"
            "hysteresis state and test noise as a separate intervention family without treating the glassy "
            "interpretation as established."
        )
    else:
        conclusion = (
            "The frozen matched-endpoint hysteresis design did not survive the full discovery chain. Do "
            "not retune endpoint tolerances or trajectory thresholds. The next preregistered hypothesis "
            "should test chaos / rapid predictability decay using divergence-rate and forecast-horizon "
            "diagnostics."
        )
    lines = [
        "<!-- trajectory-hysteresis-117-122:synthesis -->",
        "## Trajectory/Hysteresis Campaign 117–122 — Final Synthesis",
        "",
        f"- Commit: `{checkpoint['code_sha']}`",
        f"- Config hash: `{checkpoint['config_hash']}`",
        f"- Instrumentation: **{bool(checkpoint.get('instrumentation_validated'))}**",
        f"- Discovery hysteresis: **{bool(checkpoint.get('discovery_hysteresis_validated'))}**",
        f"- Trajectory predictor selected: **{bool(checkpoint.get('trajectory_predictor_selected'))}**",
        f"- Frozen trajectory predictor: `{predictor}`",
        f"- Independent replication: **{bool(checkpoint.get('replication_validated'))}**",
        f"- Mid-regime timing transfer: **{bool(checkpoint.get('timing_validated'))}**",
        f"- Holdout / full hysteresis: **{hysteresis}**",
        f"- Full annealing-consistency result: **{annealing}**",
        "- Experiments completed: **6**",
        "",
        conclusion,
        "",
        "Production behavior remains unchanged and reputation-neutral.",
    ]
    return "\n".join(lines) + "\n"


def render_boundary_update(checkpoint: Mapping[str, object]) -> str:
    hysteresis = bool(checkpoint.get("hysteresis_validated"))
    if hysteresis:
        message = (
            "Trajectory/hysteresis validated under the frozen matched-endpoint protocol. External-boundary "
            "execution remains blocked: first freeze a prospective trajectory/history representation and "
            "complete the next noise/annealing characterization before crossing the boundary."
        )
    else:
        message = (
            "Trajectory/hysteresis did not validate under the frozen matched-endpoint protocol. External-"
            "boundary execution remains blocked. Do not retune endpoint tolerances; move next to an explicit "
            "chaos / predictability-decay preregistration."
        )
    return (
        "<!-- external-boundary:trajectory-hysteresis-117-122 -->\n"
        "## Trajectory/hysteresis dependency\n\n"
        "Source: #46.\n\n"
        f"{message}\n"
    )


def write_step_artifacts(
    destination: str | Path,
    *,
    record: Mapping[str, object],
    checkpoint: Mapping[str, object],
) -> None:
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    (output / "experiment.json").write_text(json.dumps(record, indent=2, sort_keys=True, default=str))
    (output / "checkpoint.json").write_text(
        json.dumps(checkpoint, indent=2, sort_keys=True, default=str)
    )
    (output / "notebook.md").write_text(render_record(record))
    if int(record["number"]) == 122:
        (output / "campaign-summary.md").write_text(render_synthesis(checkpoint))
        (output / "boundary-update.md").write_text(render_boundary_update(checkpoint))


__all__ = ["render_boundary_update", "render_record", "render_synthesis", "write_step_artifacts"]
