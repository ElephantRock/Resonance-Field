"""Existing-evidence post-crossing reconvergence audit for Experiments 129–134."""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from psycopg import Connection

from .auction_margin_campaign import (
    MarginCellSpec,
    load_canonical_base,
    margin_environment,
    pair_summary,
    preactivation_equal,
    run_margin_cell,
)
from .auction_margin_config import AuctionMarginConfig, MarginEnvironment
from .chaos_predictability_campaign import _pair_series

_CANONICAL_CAMPAIGN_SHA = "2a85739603ebac86f451b90733229782c0d45ce0"
_EPS = 1e-12


def _cohort_specs(config: AuctionMarginConfig) -> tuple[tuple[str, int, MarginEnvironment, tuple[int, ...]], ...]:
    return (
        ("discovery", 130, config.standard, config.discovery_seeds),
        ("timing_transfer", 132, config.timing_transfer, config.timing_transfer_seeds),
        ("replication", 133, config.standard, config.replication_seeds),
        ("holdout", 134, config.holdout, config.holdout_seeds),
    )


def _persistent_starts(
    series: Sequence[Mapping[str, object]],
    *,
    key: str,
    threshold: float,
    activation_cycle: int,
    hits: int,
    window: int,
) -> list[int]:
    values = [row for row in series if int(row["cycle"]) >= activation_cycle]
    starts: list[int] = []
    for index in range(0, max(0, len(values) - window + 1)):
        chunk = values[index : index + window]
        if sum(float(row[key]) >= threshold for row in chunk) >= hits:
            starts.append(int(chunk[0]["cycle"]))
    return starts


def terminal_recovery(
    series: Sequence[Mapping[str, object]],
    *,
    key: str,
    threshold: float,
    activation_cycle: int,
    hits: int,
    window: int,
    cycles: int,
) -> int:
    """Return first cycle after the final persistent crossing window."""
    starts = _persistent_starts(
        series,
        key=key,
        threshold=threshold,
        activation_cycle=activation_cycle,
        hits=hits,
        window=window,
    )
    if not starts:
        return activation_cycle
    recovery = starts[-1] + window
    return recovery if recovery < cycles else cycles + 1


def longest_true_run(values: Sequence[bool]) -> int:
    longest = 0
    current = 0
    for value in values:
        if value:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _scale_summary(
    series: Sequence[Mapping[str, object]],
    *,
    key: str,
    threshold: float,
    activation_cycle: int,
    shift_period: int,
    hits: int,
    window: int,
    cycles: int,
) -> dict[str, object]:
    post = [row for row in series if int(row["cycle"]) >= activation_cycle]
    if not post:
        raise ValueError("post-activation series is empty")
    values = [float(row[key]) for row in post]
    peak = max(values)
    peak_cycle = next(int(row["cycle"]) for row in post if float(row[key]) == peak)
    final_regime = [row for row in series if int(row["cycle"]) >= cycles - shift_period]
    return {
        "peak": peak,
        "peak_cycle": peak_cycle,
        "auc": statistics.mean(values),
        "final": values[-1],
        "final_regime_mean": statistics.mean(float(row[key]) for row in final_regime),
        "terminal_recovery": terminal_recovery(
            series,
            key=key,
            threshold=threshold,
            activation_cycle=activation_cycle,
            hits=hits,
            window=window,
            cycles=cycles,
        ),
        "persistent_crossed": bool(
            _persistent_starts(
                series,
                key=key,
                threshold=threshold,
                activation_cycle=activation_cycle,
                hits=hits,
                window=window,
            )
        ),
    }


def _winner_recovery(
    buffered_rows: Sequence[Mapping[str, object]],
    near_rows: Sequence[Mapping[str, object]],
    *,
    activation_cycle: int,
) -> dict[str, object]:
    post = [
        (left, right)
        for left, right in zip(buffered_rows, near_rows, strict=True)
        if int(left["cycle"]) > activation_cycle
    ]
    equal = [int(left["winner_slot"]) == int(right["winner_slot"]) for left, right in post]
    first_same = next(
        (int(left["cycle"]) for (left, right), same in zip(post, equal, strict=True) if same),
        None,
    )
    return {
        "first_same_winner_cycle": first_same,
        "post_activation_same_winner_share": statistics.mean(float(value) for value in equal) if equal else 0.0,
        "longest_same_winner_run": longest_true_run(equal),
    }


def _last_component_cycles(
    series: Sequence[Mapping[str, object]],
    *,
    activation_cycle: int,
    terminal_macro_recovery: int,
    thresholds: Mapping[str, float],
) -> dict[str, int | None]:
    end = terminal_macro_recovery if terminal_macro_recovery > activation_cycle else activation_cycle + 1
    result: dict[str, int | None] = {}
    for scale, components_key in (
        ("micro", "micro_components"),
        ("meso", "meso_components"),
        ("macro", "macro_components"),
    ):
        threshold = float(thresholds[scale])
        names: set[str] = set()
        for row in series:
            components = row.get(components_key)
            if isinstance(components, Mapping):
                names.update(str(key) for key in components)
        for name in sorted(names):
            latest: int | None = None
            for row in series:
                cycle = int(row["cycle"])
                if cycle < activation_cycle or cycle >= end:
                    continue
                components = row.get(components_key)
                if isinstance(components, Mapping) and float(components.get(name, 0.0)) >= threshold:
                    latest = cycle
            result[f"{scale}.{name}"] = latest
    return result


def _close_float(left: object, right: object, *, tol: float = 1e-12) -> bool:
    try:
        a = float(left)
        b = float(right)
    except (TypeError, ValueError):
        return left == right
    if math.isinf(a) or math.isinf(b):
        return a == b
    return abs(a - b) <= tol


def _validate_reconstruction(
    expected_record: Mapping[str, object],
    *,
    observed_preactivation_equal: bool,
    observed_near_crossed: bool,
    observed_buffered_crossed: bool,
    observed_pair: Mapping[str, object],
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    checks = (
        ("preactivation_equal", observed_preactivation_equal),
        ("near_crossed", observed_near_crossed),
        ("buffered_crossed", observed_buffered_crossed),
    )
    for key, observed in checks:
        if bool(expected_record.get(key)) != bool(observed):
            failures.append(key)

    expected_pair = expected_record.get("pair_summary")
    if not isinstance(expected_pair, Mapping):
        failures.append("missing_expected_pair_summary")
        return False, failures
    scalar_keys = (
        "first_changed_winner_cycle",
        "persistent_macro_crossed",
        "buffered_basin",
        "near_basin",
        "basin_disagreement",
        "success_loss",
        "knowledge_loss",
        "all_invariants",
        "final_micro_distance",
        "final_meso_distance",
        "final_macro_distance",
    )
    for key in scalar_keys:
        if key not in expected_pair or key not in observed_pair:
            failures.append(f"pair.{key}.missing")
            continue
        expected = expected_pair[key]
        observed = observed_pair[key]
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            if not _close_float(expected, observed):
                failures.append(f"pair.{key}")
        elif expected != observed:
            failures.append(f"pair.{key}")
    expected_horizons = expected_pair.get("horizons")
    observed_horizons = observed_pair.get("horizons")
    if expected_horizons != observed_horizons:
        failures.append("pair.horizons")
    expected_saturation = expected_pair.get("saturation")
    observed_saturation = observed_pair.get("saturation")
    if isinstance(expected_saturation, Mapping) and isinstance(observed_saturation, Mapping):
        for scale in ("micro", "meso", "macro"):
            expected_scale = expected_saturation.get(scale)
            observed_scale = observed_saturation.get(scale)
            if not isinstance(expected_scale, Mapping) or not isinstance(observed_scale, Mapping):
                failures.append(f"pair.saturation.{scale}.missing")
                continue
            if bool(expected_scale.get("bounded")) != bool(observed_scale.get("bounded")):
                failures.append(f"pair.saturation.{scale}.bounded")
            if not _close_float(
                expected_scale.get("mean_final_regime"),
                observed_scale.get("mean_final_regime"),
            ):
                failures.append(f"pair.saturation.{scale}.mean_final_regime")
    else:
        failures.append("pair.saturation")
    return not failures, failures


def _single_scalar_separator(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    positives = [record for record in records if bool(record["basin_disagreement"])]
    negatives = [record for record in records if not bool(record["basin_disagreement"])]
    if len(positives) < 3:
        return {"classification": "not_identifiable", "reason": "fewer_than_three_positive_pairs"}
    candidate_keys = (
        "micro_peak",
        "meso_peak",
        "macro_peak",
        "micro_auc",
        "meso_auc",
        "macro_auc",
        "micro_final",
        "meso_final",
        "macro_final",
        "micro_terminal_recovery",
        "meso_terminal_recovery",
        "macro_terminal_recovery",
        "first_same_winner_cycle_numeric",
        "post_activation_same_winner_share",
        "longest_same_winner_run",
        "natural_radius",
    )
    separators: list[dict[str, object]] = []
    for key in candidate_keys:
        pos = [float(record[key]) for record in positives if record.get(key) is not None]
        neg = [float(record[key]) for record in negatives if record.get(key) is not None]
        if len(pos) != len(positives) or len(neg) != len(negatives):
            continue
        if min(pos) > max(neg):
            separators.append({"feature": key, "direction": "positive_high", "boundary": (min(pos) + max(neg)) / 2})
        elif max(pos) < min(neg):
            separators.append({"feature": key, "direction": "positive_low", "boundary": (max(pos) + min(neg)) / 2})
    if separators:
        return {"classification": "candidate_scalar_only", "separators": separators}
    return {"classification": "descriptive_no_separator", "separators": []}


def run_post_crossing_audit(
    connection: Connection[Any],
    *,
    config: AuctionMarginConfig,
    config_hash: str,
    expected_records: Mapping[int, Mapping[int, Mapping[str, object]]],
    audit_code_sha: str,
) -> dict[str, object]:
    base = load_canonical_base(config)
    pair_records: list[dict[str, object]] = []
    cycle_rows: list[dict[str, object]] = []
    reconstruction_failures: list[dict[str, object]] = []

    near_spec = MarginCellSpec("near_probe", config.near_radius, True)
    buffered_spec = MarginCellSpec("buffered_probe", config.buffered_radius, True)
    thresholds = {"micro": config.delta_micro, "meso": config.delta_meso, "macro": config.delta_macro}

    for cohort, number, environment_spec, seeds in _cohort_specs(config):
        expected_by_seed = expected_records.get(number, {})
        for seed in seeds:
            near = run_margin_cell(
                connection,
                config=config,
                base=base,
                config_hash=config_hash,
                code_sha=_CANONICAL_CAMPAIGN_SHA,
                experiment_number=number,
                cohort=cohort,
                seed=seed,
                environment_spec=environment_spec,
                spec=near_spec,
            )
            buffered = run_margin_cell(
                connection,
                config=config,
                base=base,
                config_hash=config_hash,
                code_sha=_CANONICAL_CAMPAIGN_SHA,
                experiment_number=number,
                cohort=cohort,
                seed=seed,
                environment_spec=environment_spec,
                spec=buffered_spec,
            )
            env = margin_environment(base, environment_spec)
            observed_pair = pair_summary(
                config=config,
                base=base,
                seed=seed,
                environment_spec=environment_spec,
                near=near,
                buffered=buffered,
            )
            near_rows = near["rows"]
            buffered_rows = buffered["rows"]
            assert isinstance(near_rows, Sequence) and isinstance(buffered_rows, Sequence)
            prefix_equal = preactivation_equal(
                connection,
                near,
                buffered,
                activation_cycle=environment_spec.activation_cycle,
            )
            near_audit = near["margin_audit"]
            buffered_audit = buffered["margin_audit"]
            assert isinstance(near_audit, Mapping) and isinstance(buffered_audit, Mapping)
            near_crossed = int(near_audit["awarded_winner_slot"]) != int(near_audit["natural_winner_slot"])
            buffered_crossed = int(buffered_audit["awarded_winner_slot"]) != int(buffered_audit["natural_winner_slot"])
            expected = expected_by_seed.get(seed)
            if expected is None:
                valid, failures = False, ["missing_expected_seed_record"]
            else:
                valid, failures = _validate_reconstruction(
                    expected,
                    observed_preactivation_equal=prefix_equal,
                    observed_near_crossed=near_crossed,
                    observed_buffered_crossed=buffered_crossed,
                    observed_pair=observed_pair,
                )
            if not valid:
                reconstruction_failures.append({"experiment": number, "cohort": cohort, "seed": seed, "failures": failures})

            series = _pair_series(
                buffered_rows,
                near_rows,
                seed=seed,
                env=env,
                base=base,
                baseline_trace_cycle=None,
                perturbed_trace_cycle=None,
                perturbed_trace_multiplier=1.0,
            )
            scale_summaries = {
                scale: _scale_summary(
                    series,
                    key=f"{scale}_distance",
                    threshold=float(thresholds[scale]),
                    activation_cycle=environment_spec.activation_cycle,
                    shift_period=environment_spec.shift_period,
                    hits=config.persistent_hits,
                    window=config.persistent_window,
                    cycles=environment_spec.cycles,
                )
                for scale in ("micro", "meso", "macro")
            }
            winner = _winner_recovery(
                buffered_rows,
                near_rows,
                activation_cycle=environment_spec.activation_cycle,
            )
            macro = scale_summaries["macro"]
            macro_crossed = bool(macro["persistent_crossed"])
            basin_disagreement = bool(observed_pair["basin_disagreement"])
            macro_absorbed = bool(
                macro_crossed
                and float(macro["final_regime_mean"]) < config.delta_macro
                and not basin_disagreement
            )
            micro_final = float(scale_summaries["micro"]["final"])
            coarse = bool(macro_absorbed and micro_final > _EPS)
            first_same = winner["first_same_winner_cycle"]
            record: dict[str, object] = {
                "experiment": number,
                "cohort": cohort,
                "seed": seed,
                "activation_cycle": environment_spec.activation_cycle,
                "reconstruction_valid": valid,
                "preactivation_equal": prefix_equal,
                "near_crossed": near_crossed,
                "buffered_crossed": buffered_crossed,
                "basin_disagreement": basin_disagreement,
                "buffered_basin": observed_pair["buffered_basin"],
                "near_basin": observed_pair["near_basin"],
                "macro_absorbed": macro_absorbed,
                "coarse_grained_absorption": coarse,
                "full_resynchronization": bool(macro_absorbed and micro_final <= _EPS),
                "natural_radius": float(near_audit["natural_radius"]),
                **winner,
                "first_same_winner_cycle_numeric": (
                    environment_spec.cycles + 1 if first_same is None else int(first_same)
                ),
            }
            for scale in ("micro", "meso", "macro"):
                summary = scale_summaries[scale]
                record.update(
                    {
                        f"{scale}_peak": summary["peak"],
                        f"{scale}_peak_cycle": summary["peak_cycle"],
                        f"{scale}_auc": summary["auc"],
                        f"{scale}_final": summary["final"],
                        f"{scale}_final_regime_mean": summary["final_regime_mean"],
                        f"{scale}_terminal_recovery": summary["terminal_recovery"],
                        f"{scale}_persistent_crossed": summary["persistent_crossed"],
                    }
                )
            record["last_component_above_before_macro_recovery"] = _last_component_cycles(
                series,
                activation_cycle=environment_spec.activation_cycle,
                terminal_macro_recovery=int(macro["terminal_recovery"]),
                thresholds=thresholds,
            )
            pair_records.append(record)

            for row in series:
                cycle_rows.append(
                    {
                        "experiment": number,
                        "cohort": cohort,
                        "seed": seed,
                        "activation_cycle": environment_spec.activation_cycle,
                        **dict(row),
                    }
                )

    reconstruction_valid = not reconstruction_failures and all(bool(record["reconstruction_valid"]) for record in pair_records)
    macro_crossed_records = [record for record in pair_records if bool(record["macro_persistent_crossed"])]
    absorbed_records = [record for record in macro_crossed_records if bool(record["macro_absorbed"])]
    absorbed_share = len(absorbed_records) / len(macro_crossed_records) if macro_crossed_records else 0.0
    coarse_share = (
        statistics.mean(float(bool(record["coarse_grained_absorption"])) for record in absorbed_records)
        if absorbed_records
        else 0.0
    )

    cohort_eval: dict[str, dict[str, object]] = {}
    for cohort in ("discovery", "timing_transfer", "replication", "holdout"):
        rows = [record for record in pair_records if record["cohort"] == cohort]
        basin_agreement = statistics.mean(float(not bool(record["basin_disagreement"])) for record in rows)
        median_macro = statistics.median(float(record["macro_final"]) for record in rows)
        median_micro = statistics.median(float(record["micro_final"]) for record in rows)
        cohort_eval[cohort] = {
            "n": len(rows),
            "basin_agreement_share": basin_agreement,
            "median_final_macro": median_macro,
            "median_final_micro": median_micro,
            "macro_lower_than_micro": median_macro < median_micro,
        }

    required_cohorts = ("discovery", "replication", "holdout")
    supported = bool(
        reconstruction_valid
        and absorbed_share >= 0.75
        and coarse_share >= 0.75
        and all(float(cohort_eval[c]["basin_agreement_share"]) >= 0.75 for c in required_cohorts)
        and all(bool(cohort_eval[c]["macro_lower_than_micro"]) for c in required_cohorts)
    )
    basin_escape = _single_scalar_separator(pair_records)
    if supported:
        next_recommendation = "preregister_contraction_breaking_family_only_if_a_single_causal_bottleneck_is_localized"
    else:
        next_recommendation = "no_new_family_justified"

    return {
        "audit": "post-crossing-reconvergence-129-134",
        "audit_code_sha": audit_code_sha,
        "canonical_campaign_sha": _CANONICAL_CAMPAIGN_SHA,
        "config_hash": config_hash,
        "pair_count": len(pair_records),
        "reconstruction_valid": reconstruction_valid,
        "reconstruction_failures": reconstruction_failures,
        "macro_crossed_pairs": len(macro_crossed_records),
        "macro_absorbed_pairs": len(absorbed_records),
        "macro_absorbed_share": absorbed_share,
        "coarse_grained_absorption_share_among_absorbed": coarse_share,
        "cohort_evaluation": cohort_eval,
        "cross_scale_absorption_supported": supported,
        "basin_escape_diagnostic": basin_escape,
        "recommendation": next_recommendation,
        "pair_records": pair_records,
        "cycle_rows": cycle_rows,
    }


def load_expected_records(root: str | Path) -> dict[int, dict[int, Mapping[str, object]]]:
    base = Path(root)
    result: dict[int, dict[int, Mapping[str, object]]] = {}
    for number in (130, 132, 133, 134):
        path = base / str(number) / "experiment.json"
        value = json.loads(path.read_text())
        records = value.get("seed_records", [])
        result[number] = {int(record["seed"]): record for record in records}
    return result


def render_markdown(audit: Mapping[str, object]) -> str:
    cohort_eval = audit["cohort_evaluation"]
    basin = audit["basin_escape_diagnostic"]
    assert isinstance(cohort_eval, Mapping) and isinstance(basin, Mapping)
    lines = [
        "<!-- post-crossing-reconvergence-audit:result -->",
        "## Post-Crossing Reconvergence Audit — 129–134",
        "",
        f"- Audit commit: `{audit['audit_code_sha']}`",
        f"- Canonical campaign SHA: `{audit['canonical_campaign_sha']}`",
        f"- Reconstruction valid: **{audit['reconstruction_valid']}**",
        f"- Historical pairs: **{audit['pair_count']}**",
        f"- Macro-crossed pairs: **{audit['macro_crossed_pairs']}**",
        f"- Macro-absorbed pairs: **{audit['macro_absorbed_pairs']}**",
        f"- Absorbed share among macro-crossed: **{float(audit['macro_absorbed_share']):.3f}**",
        f"- Coarse-grained share among absorbed: **{float(audit['coarse_grained_absorption_share_among_absorbed']):.3f}**",
        f"- Cross-scale absorption supported: **{audit['cross_scale_absorption_supported']}**",
        f"- Basin-escape diagnostic: **{basin.get('classification')}**",
        f"- Next recommendation: **{audit['recommendation']}**",
        "",
        "### Cohort recovery",
        "",
        "| Cohort | n | Basin agreement | Median final micro | Median final macro | Macro < micro |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for cohort in ("discovery", "timing_transfer", "replication", "holdout"):
        value = cohort_eval[cohort]
        assert isinstance(value, Mapping)
        lines.append(
            f"| {cohort} | {value['n']} | {float(value['basin_agreement_share']):.3f} | "
            f"{float(value['median_final_micro']):.6f} | {float(value['median_final_macro']):.6f} | "
            f"{value['macro_lower_than_micro']} |"
        )
    lines.extend(
        [
            "",
            "### Interpretation",
            "",
            (
                "The audit distinguishes transient macroscopic divergence from terminal basin separation and "
                "tests whether organizational reconvergence occurs while microscopic state remains distinct. "
                "A failed primary gate is preserved as a null even if individual pairs show coarse-grained absorption."
            ),
            "",
            "No Experiment 135+ was run or authorized by this audit.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_artifacts(output_dir: str | Path, audit: Mapping[str, object]) -> None:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    serializable = dict(audit)
    cycle_rows = serializable.pop("cycle_rows")
    pair_records = serializable.get("pair_records", [])
    (root / "post-crossing-reconvergence-audit.json").write_text(
        json.dumps(serializable, indent=2, sort_keys=True, default=str) + "\n"
    )
    (root / "audit-report.md").write_text(render_markdown(audit))

    assert isinstance(pair_records, Sequence)
    with (root / "pair-summary.csv").open("w", newline="") as handle:
        fieldnames = [
            "experiment",
            "cohort",
            "seed",
            "reconstruction_valid",
            "basin_disagreement",
            "macro_absorbed",
            "coarse_grained_absorption",
            "natural_radius",
            "first_same_winner_cycle",
            "post_activation_same_winner_share",
            "longest_same_winner_run",
            "micro_peak",
            "micro_auc",
            "micro_final",
            "micro_terminal_recovery",
            "meso_peak",
            "meso_auc",
            "meso_final",
            "meso_terminal_recovery",
            "macro_peak",
            "macro_auc",
            "macro_final",
            "macro_terminal_recovery",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in pair_records:
            writer.writerow({key: record.get(key) for key in fieldnames})

    assert isinstance(cycle_rows, Sequence)
    with (root / "cycle-distance-components.csv").open("w", newline="") as handle:
        fieldnames = [
            "experiment",
            "cohort",
            "seed",
            "activation_cycle",
            "cycle",
            "micro_distance",
            "meso_distance",
            "macro_distance",
            "candidate_distance",
            "micro_components",
            "meso_components",
            "macro_components",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in cycle_rows:
            row = {key: record.get(key) for key in fieldnames}
            for key in ("micro_components", "meso_components", "macro_components"):
                row[key] = json.dumps(row[key], sort_keys=True)
            writer.writerow(row)


__all__ = [
    "load_expected_records",
    "longest_true_run",
    "render_markdown",
    "run_post_crossing_audit",
    "terminal_recovery",
    "write_artifacts",
]
