"""Notebook artifacts for Auction Margin Control Experiments 129–134."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path


def _scalar_lines(value: Mapping[str, object]) -> list[str]:
    lines: list[str] = []
    for key, item in value.items():
        if isinstance(item, (str, int, float, bool)) or item is None:
            lines.append(f"- {key}: **{item}**")
    return lines


def render_record(record: Mapping[str, object]) -> str:
    number = int(record["number"])
    lines = [
        f"<!-- auction-margin-129-134:experiment-{number:03d} -->",
        f"## Experiment {number:03d} — completed",
        "",
        f"**Question:** {record['question']}",
        "",
        f"- Focus: `{record['focus']}`",
        f"- Validated: **{bool(record['validated'])}**",
        f"- Next focus: `{record.get('next_experiment_focus')}`",
    ]
    for key in (
        "instrumentation_validated",
        "local_crossing_validated",
        "discovery_propagation_validated",
        "holdout_validated",
        "robust_auction_margin_control",
        "canonical_conclusion",
    ):
        if key in record:
            lines.append(f"- {key}: **{record[key]}**")
    for key in ("local_gate", "propagation_evaluation"):
        value = record.get(key)
        if isinstance(value, Mapping):
            lines.extend(["", f"### {key}", *_scalar_lines(value)])
    seeds = record.get("seed_records") or record.get("instrumentation_records")
    if isinstance(seeds, Sequence):
        lines.extend(
            [
                "",
                "### Seed summary",
                "",
                "| Seed | Pre-activation equal | Near crossed | Buffered crossed | Invariants |",
                "|---:|---|---|---|---|",
            ]
        )
        for item in seeds:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"| {item['seed']} | {item.get('preactivation_equal')} | {item.get('near_crossed')} | "
                f"{item.get('buffered_crossed')} | {item.get('all_invariants')} |"
            )
    return "\n".join(lines) + "\n"


def render_synthesis(checkpoint: Mapping[str, object]) -> str:
    robust = bool(checkpoint.get("robust_auction_margin_control"))
    local = bool(checkpoint.get("local_crossing_validated"))
    if robust:
        conclusion = (
            "The frozen auction-margin controller prospectively controlled the immediate argmax crossing and "
            "the induced one-shot crossing propagated to organizational divergence across timing transfer, "
            "independent replication, and the unseen holdout. This validates robust auction-margin control, "
            "not self-organized criticality."
        )
    elif local:
        conclusion = (
            "The auction margin prospectively controlled immediate decision sensitivity, but the full chain "
            "did not establish robust organizational propagation. Preserve the local causal result and do not "
            "retune radius, epsilon, activation timing, or distance gates."
        )
    else:
        conclusion = (
            "The frozen near-versus-buffered auction-margin crossing pattern did not validate. Preserve the "
            "falsification and do not search another auction radius or probe magnitude within this family."
        )
    return "\n".join(
        [
            "<!-- auction-margin-129-134:synthesis -->",
            "## Auction Margin Control Campaign 129–134 — Final Synthesis",
            "",
            f"- Commit: `{checkpoint['code_sha']}`",
            f"- Config hash: `{checkpoint['config_hash']}`",
            f"- Instrumentation: **{bool(checkpoint.get('instrumentation_validated'))}**",
            f"- Local causal crossing: **{local}**",
            f"- Discovery organizational propagation: **{bool(checkpoint.get('discovery_propagation_validated'))}**",
            f"- Timing transfer: **{bool(checkpoint.get('timing_transfer_validated'))}**",
            f"- Independent replication: **{bool(checkpoint.get('replication_validated'))}**",
            f"- Holdout validation: **{bool(checkpoint.get('holdout_validated'))}**",
            f"- Robust auction-margin control: **{robust}**",
            "- SOC claim: **not available from this campaign**",
            "- Experiments completed: **6**",
            "",
            conclusion,
            "",
            "Production behavior remains unchanged and reputation-neutral.",
        ]
    ) + "\n"


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
    if int(record["number"]) == 134:
        (output / "campaign-summary.md").write_text(render_synthesis(checkpoint))


__all__ = ["render_record", "render_synthesis", "write_step_artifacts"]
