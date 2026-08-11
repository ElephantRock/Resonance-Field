"""Notebook and issue artifacts for Chaos / Predictability-Decay Experiments 123–128."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path


def _flatten_lines(prefix: str, value: object, lines: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(item, Mapping):
                _flatten_lines(f"{prefix}{key}.", item, lines)
            elif not isinstance(item, (list, tuple)):
                lines.append(f"- {prefix}{key}: **{item}**")


def render_record(record: Mapping[str, object]) -> str:
    number = int(record["number"])
    lines = [
        f"<!-- chaos-predictability-123-128:experiment-{number:03d} -->",
        f"## Experiment {number:03d} — completed",
        "",
        f"**Question:** {record['question']}",
        "",
        f"- Focus: `{record['focus']}`",
        f"- Validated: **{bool(record['validated'])}**",
        f"- Next focus: `{record.get('next_experiment_focus')}`",
    ]
    simple_keys = (
        "zero_twin_exact",
        "candidate_set_equal",
        "hard_invariants",
        "bid_target_exact",
        "trace_target_exact",
        "embedding_negative_control_inert",
        "instrumentation_gate",
        "local_screen_validated",
        "passing_families",
        "scaling_families",
        "scaling_validated",
        "selected_family",
        "discovery_classification",
        "organizational_chaos_discovery",
        "replication_classification",
        "forecast_horizon_sign_agreement",
        "replication_validated",
        "holdout_classification",
        "holdout_classification_agreement",
        "organizational_chaos_validated",
        "canonical_classification",
    )
    for key in simple_keys:
        if key in record:
            lines.append(f"- {key}: **{record[key]}**")

    for nested_key in (
        "local_screen",
        "scaling_evaluation",
        "family_evaluations",
        "replication_evaluation",
        "holdout_evaluation",
    ):
        value = record.get(nested_key)
        if isinstance(value, Mapping):
            lines.extend(["", f"### {nested_key}"])
            _flatten_lines("", value, lines)

    occupancy = record.get("basin_occupancy")
    if isinstance(occupancy, Mapping):
        lines.extend(
            [
                "",
                "### Basin occupancy",
                "",
                "```json",
                json.dumps(occupancy, indent=2, sort_keys=True),
                "```",
            ]
        )
    return "\n".join(lines) + "\n"


def render_synthesis(checkpoint: Mapping[str, object]) -> str:
    canonical = str(checkpoint.get("canonical_classification"))
    org = bool(checkpoint.get("organizational_chaos_validated"))
    if org:
        conclusion = (
            "Organizational chaos survived instrumentation, finite-size scaling, boundedness, independent "
            "replication, and the unseen holdout. Issue #42 may now be redesigned and preregistered as a "
            "continuous causally independent perturbation boundary. Do not execute the old one-shot phase "
            "transition design."
        )
    elif canonical == "microscopic_chaos_with_organizational_predictability":
        conclusion = (
            "Sensitive dependence survived below the organizational scale, but macroscopic outcomes remained "
            "predictable. Preserve the distinction: Resonance Field may be microscopically chaotic without "
            "being organizationally chaotic. External-boundary execution remains blocked."
        )
    elif canonical == "basin_boundary_sensitivity_or_hidden_state_contingency":
        conclusion = (
            "The frozen finite-size scaling test did not establish chaos; the evidence is more consistent "
            "with threshold/basin sensitivity or unresolved microscopic state. Do not retune epsilon or "
            "forecast thresholds. External-boundary execution remains blocked."
        )
    elif canonical == "instability_not_chaos":
        conclusion = (
            "Divergence failed the bounded nontriviality requirement and is classified as instability rather "
            "than chaos. External-boundary execution remains blocked."
        )
    else:
        conclusion = (
            "No replicated chaos/predictability-decay classification survived the frozen chain. Do not retune "
            "epsilon, perturbation location, distance thresholds, or basin thresholds; inspect finer-grained "
            "latent state only under a new preregistration."
        )
    return "\n".join(
        [
            "<!-- chaos-predictability-123-128:synthesis -->",
            "## Chaos / Predictability-Decay Campaign 123–128 — Final Synthesis",
            "",
            f"- Commit: `{checkpoint['code_sha']}`",
            f"- Config hash: `{checkpoint['config_hash']}`",
            f"- Instrumentation: **{bool(checkpoint.get('instrumentation_validated'))}**",
            f"- Local divergence screen: **{bool(checkpoint.get('local_screen_validated'))}**",
            f"- Finite-size scaling: **{bool(checkpoint.get('scaling_validated'))}**",
            f"- Selected perturbation family: `{checkpoint.get('selected_family')}`",
            f"- Discovery classification: `{checkpoint.get('discovery_classification')}`",
            f"- Independent replication: **{bool(checkpoint.get('replication_validated'))}**",
            f"- Holdout agreement: **{bool(checkpoint.get('holdout_validated'))}**",
            f"- Organizational chaos validated: **{org}**",
            f"- Canonical classification: **`{canonical}`**",
            "- Experiments completed: **6**",
            "",
            conclusion,
            "",
            "Production behavior remains unchanged and reputation-neutral.",
        ]
    ) + "\n"


def render_boundary_update(checkpoint: Mapping[str, object]) -> str:
    if bool(checkpoint.get("organizational_chaos_validated")):
        message = (
            "Experiment 128 validated organizational chaos under the frozen finite-size, boundedness, "
            "replication, and holdout gates. #42 is unblocked for **redesign and preregistration only** as a "
            "continuous causally independent perturbation source. Do not execute the prior one-shot boundary "
            "design. Future emissions must be independently generated, precommitted, hidden until release, "
            "and causally independent of organizational state."
        )
    else:
        message = (
            f"Chaos campaign canonical classification: `{checkpoint.get('canonical_classification')}`. "
            "Organizational chaos did not validate through the frozen full chain, so external-boundary "
            "execution remains blocked. Do not retune the 123–128 epsilon grid, thresholds, or perturbation "
            "locations to force an unlock."
        )
    return (
        "<!-- external-boundary:chaos-predictability-123-128 -->\n"
        "## Chaos / predictability-decay dependency\n\n"
        "Source: #48.\n\n"
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
    (output / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2, sort_keys=True, default=str))
    (output / "notebook.md").write_text(render_record(record))
    if int(record["number"]) == 128:
        (output / "campaign-summary.md").write_text(render_synthesis(checkpoint))
        (output / "boundary-update.md").write_text(render_boundary_update(checkpoint))


__all__ = ["render_boundary_update", "render_record", "render_synthesis", "write_step_artifacts"]
