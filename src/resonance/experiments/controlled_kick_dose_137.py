"""Frozen independent replication for Controlled Kick-Dose Experiment 137."""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from psycopg import Connection

from .auction_margin_campaign import _final_public_knowledge, preactivation_equal
from .auction_margin_config import AuctionMarginConfig
from .censored_cascade_survival_audit import _first_full_regime_sync
from .controlled_kick_dose_136 import (
    _dose_quality,
    _dose_survival,
    _mediation_analysis,
    _sync_survival,
    _write_csv,
    cox_ph,
    schedule_for_seed,
)
from .controlled_kick_dose_campaign import (
    _all_invariants,
    _persist_kick_events,
    _persist_pair_summary,
    _series_for_pair,
    campaign_environment,
    load_campaign_base,
    run_control_cell,
    run_kick_cell,
)
from .controlled_kick_dose_config import KickDoseConfig
from .post_crossing_reconvergence_audit import _persistent_starts, terminal_recovery

_EPS = 1e-12
_EXPERIMENT_NUMBER = 137


def _replication_pair(
    connection: Connection[Any],
    *,
    config: KickDoseConfig,
    margin_config: AuctionMarginConfig,
    base: Any,
    config_hash: str,
    code_sha: str,
    seed: int,
    dose: int,
    kick_cycles: Sequence[int],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Run one frozen replication pair without touching Experiment 136 state."""
    control = run_control_cell(
        connection,
        config=config,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=_EXPERIMENT_NUMBER,
        seed=seed,
    )
    kick = run_kick_cell(
        connection,
        config=config,
        margin_config=margin_config,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=_EXPERIMENT_NUMBER,
        seed=seed,
        dose=dose,
        kick_cycles=kick_cycles,
    )
    env = campaign_environment(base, config)
    series = _series_for_pair(
        control=control,
        kick=kick,
        seed=seed,
        environment=env,
        base=base,
    )

    audits = kick["kick_audits"]
    assert isinstance(audits, Sequence)
    event_checks = [
        bool(audit["margin_only_preserved"])
        and bool(audit["probe_crossed"])
        and int(audit["predicted_winner_slot"]) == int(audit["awarded_winner_slot"])
        and abs(float(audit["placed_radius"]) - config.target_radius) <= 1e-9
        for audit in audits
    ]
    nonzero_cycles = tuple(int(value) for value in kick["nonzero_adjustment_cycles"])
    pre_equal = preactivation_equal(
        connection,
        control,
        kick,
        activation_cycle=config.activation_cycle,
    )
    kick_invariants = kick["invariants"]
    assert isinstance(kick_invariants, Mapping)
    controlled_deviations = sum(bool(audit["probe_crossed"]) for audit in audits)
    pair_eligible = all(
        (
            pre_equal,
            len(audits) == dose,
            controlled_deviations == dose,
            all(event_checks),
            all(cycle <= 39 for cycle in nonzero_cycles),
            _all_invariants(control),
            _all_invariants(kick),
            bool(kick_invariants["endogenous_demand_reputation_neutral"]),
            bool(kick_invariants["identity_turnover_absent"]),
        )
    )

    persistent_starts = _persistent_starts(
        series,
        key="macro_distance",
        threshold=config.macro_threshold,
        activation_cycle=config.landmark_cycle,
        hits=config.persistent_hits,
        window=config.persistent_window,
    )
    recovery_cycle = terminal_recovery(
        series,
        key="macro_distance",
        threshold=config.macro_threshold,
        activation_cycle=config.landmark_cycle,
        hits=config.persistent_hits,
        window=config.persistent_window,
        cycles=config.cycles,
    )
    recovery_observed = recovery_cycle <= config.cycles - 1
    recovery_duration = (
        recovery_cycle - config.landmark_cycle + 1
        if recovery_observed
        else config.censor_duration
    )

    mediator_rows = [
        row
        for row in series
        if config.mediator_cycles[0] <= int(row["cycle"]) <= config.mediator_cycles[1]
    ]
    mediator_values = [float(row["micro_distance"]) for row in mediator_rows]
    sync_cycle, sync_observed = _first_full_regime_sync(
        series,
        activation=config.activation_cycle,
        cycles=config.cycles,
        shift_period=config.shift_period,
    )
    sync_duration = (
        sync_cycle - config.activation_cycle
        if sync_observed
        else config.cycles - config.activation_cycle
    )

    control_rows = control["rows"]
    kick_rows = kick["rows"]
    assert isinstance(control_rows, Sequence) and isinstance(kick_rows, Sequence)
    from .controlled_kick_dose_136 import _final_basin

    control_basin, kick_basin = _final_basin(
        control_rows,  # type: ignore[arg-type]
        kick_rows,  # type: ignore[arg-type]
        env=env,
    )
    control_metrics = control["metrics"]
    kick_metrics = kick["metrics"]
    assert isinstance(control_metrics, Mapping) and isinstance(kick_metrics, Mapping)
    control_success = float(control_metrics["success_rate"])
    kick_success = float(kick_metrics["success_rate"])
    control_knowledge = _final_public_knowledge(control_rows, env=env, base=base)  # type: ignore[arg-type]
    kick_knowledge = _final_public_knowledge(kick_rows, env=env, base=base)  # type: ignore[arg-type]

    summary: dict[str, object] = {
        "experiment_number": _EXPERIMENT_NUMBER,
        "seed": seed,
        "dose": dose,
        "log2_dose": math.log2(dose),
        "kick_cycles": list(kick_cycles),
        "control_run_id": str(control["run_id"]),
        "kick_run_id": str(kick["run_id"]),
        "preactivation_identity": pre_equal,
        "controlled_award_deviation_count": controlled_deviations,
        "every_kick_preserved_then_crossed": all(event_checks),
        "no_adjustment_after_39": all(cycle <= 39 for cycle in nonzero_cycles),
        "control_hard_invariants": _all_invariants(control),
        "kick_hard_invariants": _all_invariants(kick),
        "reputation_neutral": bool(kick_invariants["endogenous_demand_reputation_neutral"]),
        "zero_turnover": bool(kick_invariants["identity_turnover_absent"]),
        "pair_eligible": pair_eligible,
        "post_landmark_persistent_macro_crossing": bool(persistent_starts),
        "persistent_macro_starts": persistent_starts,
        "recovery_cycle": recovery_cycle if recovery_observed else None,
        "recovery_observed": recovery_observed,
        "recovery_duration": recovery_duration,
        "early_micro_peak": max(mediator_values),
        "early_micro_auc": statistics.mean(mediator_values),
        "control_basin": control_basin,
        "kick_basin": kick_basin,
        "basin_agreement": control_basin == kick_basin,
        "t_sync": sync_cycle if sync_observed else None,
        "sync_observed": sync_observed,
        "sync_duration": sync_duration,
        "control_success_rate": control_success,
        "kick_success_rate": kick_success,
        "success_difference": kick_success - control_success,
        "success_loss": max(0.0, control_success - kick_success),
        "control_final_public_knowledge": control_knowledge,
        "kick_final_public_knowledge": kick_knowledge,
        "public_knowledge_difference": kick_knowledge - control_knowledge,
        "knowledge_loss": max(0.0, control_knowledge - kick_knowledge),
        "kick_audits": list(audits),
        "natural_radius_diagnostic_role": "descriptive_only_not_in_confirmatory_models",
    }
    _persist_kick_events(
        connection,
        run_id=str(kick["run_id"]),
        experiment_number=_EXPERIMENT_NUMBER,
        seed=seed,
        dose=dose,
        kick_cycles=kick_cycles,
        audits=audits,  # type: ignore[arg-type]
    )
    _persist_pair_summary(
        connection,
        control_run_id=str(control["run_id"]),
        kick_run_id=str(kick["run_id"]),
        experiment_number=_EXPERIMENT_NUMBER,
        seed=seed,
        dose=dose,
        summary=summary,
    )
    series_rows = [
        {
            "seed": seed,
            "dose": dose,
            "cycle": int(row["cycle"]),
            "micro_distance": float(row["micro_distance"]),
            "meso_distance": float(row["meso_distance"]),
            "macro_distance": float(row["macro_distance"]),
            "micro_components": row["micro_components"],
            "meso_components": row["meso_components"],
            "macro_components": row["macro_components"],
        }
        for row in series
    ]
    return summary, series_rows


def _replication_mediation(
    eligible: Sequence[Mapping[str, object]],
    *,
    mediator_key: str,
    model1: Mapping[str, object],
) -> dict[str, object]:
    result = dict(
        _mediation_analysis(
            eligible,
            mediator_key=mediator_key,
            model1=model1,
        )
    )
    local_gate = bool(result.pop("discovery_conditions_met", False))
    result["replication_conditions_met"] = local_gate
    return result


def run_experiment_137(
    connection: Connection[Any],
    *,
    config: KickDoseConfig,
    margin_config: AuctionMarginConfig,
    config_hash: str,
    code_sha: str,
    instrumentation_135: Mapping[str, object],
) -> dict[str, object]:
    """Run the frozen 36-pair independent replication and preregistered analyses."""
    instrumentation_validated = bool(instrumentation_135.get("instrumentation_validated"))
    instrumentation_hash_matches = str(instrumentation_135.get("config_hash")) == config_hash
    instrumentation_dependency_valid = instrumentation_validated and instrumentation_hash_matches
    base = load_campaign_base(config)
    pairs: list[dict[str, object]] = []
    series_rows: list[dict[str, object]] = []

    for seed in config.replication_seeds:
        dose, schedule = schedule_for_seed(
            config,
            seed=seed,
            cohort_seeds=config.replication_seeds,
        )
        pair, series = _replication_pair(
            connection,
            config=config,
            margin_config=margin_config,
            base=base,
            config_hash=config_hash,
            code_sha=code_sha,
            seed=seed,
            dose=dose,
            kick_cycles=schedule,
        )
        pairs.append(pair)
        series_rows.extend(series)

    eligible = [pair for pair in pairs if bool(pair["pair_eligible"])]
    durations = [float(pair["recovery_duration"]) for pair in eligible]
    events = [int(bool(pair["recovery_observed"])) for pair in eligible]
    d = [float(pair["log2_dose"]) for pair in eligible]
    primary_cox = cox_ph(
        durations,
        events,
        [[value] for value in d],
        names=("log2_dose",),
    )
    categorical_cox = cox_ph(
        durations,
        events,
        [
            [float(int(pair["dose"]) == 2), float(int(pair["dose"]) == 4)]
            for pair in eligible
        ],
        names=("k2_vs_k1", "k4_vs_k1"),
    )
    recovery_survival, recovery_km_rows = _dose_survival(
        pairs,
        doses=config.doses,
        horizon=config.censor_duration,
    )
    sync_survival, sync_km_rows = _sync_survival(
        pairs,
        doses=config.doses,
        horizon=config.cycles - config.activation_cycle,
    )
    quality = _dose_quality(pairs, doses=config.doses)
    primary_mediation = _replication_mediation(
        eligible,
        mediator_key="early_micro_peak",
        model1=primary_cox,
    )
    sensitivity_mediation = _replication_mediation(
        eligible,
        mediator_key="early_micro_auc",
        model1=primary_cox,
    )

    primary_coefficients = primary_cox.get("coefficients")
    primary_d = (
        primary_coefficients.get("log2_dose")
        if isinstance(primary_coefficients, Mapping)
        else None
    )
    rmst_values = [float(recovery_survival[str(dose)]["rmst_180"]) for dose in config.doses]
    rmst_nondecreasing = all(
        rmst_values[index] <= rmst_values[index + 1] + _EPS
        for index in range(len(rmst_values) - 1)
    )
    all_hard_invariants = all(
        bool(pair["control_hard_invariants"]) and bool(pair["kick_hard_invariants"])
        for pair in pairs
    )
    quality_success = all(
        int(quality[str(dose)]["eligible_pairs"]) > 0
        and float(quality[str(dose)]["mean_success_loss"])
        <= config.maximum_success_loss + _EPS
        for dose in config.doses
    )
    quality_knowledge = all(
        int(quality[str(dose)]["eligible_pairs"]) > 0
        and float(quality[str(dose)]["mean_knowledge_loss"])
        <= config.maximum_knowledge_loss + _EPS
        for dose in config.doses
    )
    primary_direction_significant = (
        bool(primary_cox.get("stable"))
        and isinstance(primary_d, Mapping)
        and float(primary_d["beta"]) < 0.0
        and float(primary_d["p_two_sided"]) <= config.alpha
    )
    replication_validates = all(
        (
            instrumentation_dependency_valid,
            primary_direction_significant,
            rmst_nondecreasing,
            all_hard_invariants,
            quality_success,
            quality_knowledge,
        )
    )

    gap_rows = [
        row
        for row in series_rows
        if config.gap_cycles[0] <= int(row["cycle"]) <= config.gap_cycles[1]
    ]
    mediator_rows = [
        row
        for row in series_rows
        if config.mediator_cycles[0] <= int(row["cycle"]) <= config.mediator_cycles[1]
    ]
    return {
        "experiment_number": _EXPERIMENT_NUMBER,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "instrumentation_135_validated": instrumentation_validated,
        "instrumentation_135_config_hash_matches": instrumentation_hash_matches,
        "instrumentation_dependency_valid": instrumentation_dependency_valid,
        "discovery_136_artifact_loaded": False,
        "pair_count": len(pairs),
        "eligible_pair_count": len(eligible),
        "dose_counts": {
            str(dose): sum(int(pair["dose"]) == dose for pair in pairs)
            for dose in config.doses
        },
        "eligible_dose_counts": {
            str(dose): sum(
                int(pair["dose"]) == dose and bool(pair["pair_eligible"])
                for pair in pairs
            )
            for dose in config.doses
        },
        "primary_cox": primary_cox,
        "categorical_cox": categorical_cox,
        "recovery_survival": recovery_survival,
        "rmst_nondecreasing": rmst_nondecreasing,
        "quality_by_dose": quality,
        "all_hard_invariants": all_hard_invariants,
        "primary_mediation_replication": primary_mediation,
        "sensitivity_mediation_replication": sensitivity_mediation,
        "winner_sync_survival": sync_survival,
        "replication_validates": replication_validates,
        "pairs": pairs,
        "pair_series": series_rows,
        "gap_trace": gap_rows,
        "mediator_trace": mediator_rows,
        "km_rows": recovery_km_rows + sync_km_rows,
        "natural_radius_diagnostic_role": "descriptive_only_not_in_confirmatory_models",
        "interpretation_boundary": (
            "independent_replication_only_no_experiment_136_outcomes_loaded_or_used"
        ),
    }


def write_experiment_137_outputs(result: Mapping[str, object], output_dir: str | Path) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "experiment-137.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )

    pairs = result["pairs"]
    series = result["pair_series"]
    gap = result["gap_trace"]
    mediator = result["mediator_trace"]
    km_rows = result["km_rows"]
    assert isinstance(pairs, Sequence)
    assert isinstance(series, Sequence)
    assert isinstance(gap, Sequence)
    assert isinstance(mediator, Sequence)
    assert isinstance(km_rows, Sequence)

    pair_fields = (
        "seed",
        "dose",
        "log2_dose",
        "kick_cycles",
        "pair_eligible",
        "controlled_award_deviation_count",
        "post_landmark_persistent_macro_crossing",
        "recovery_cycle",
        "recovery_observed",
        "recovery_duration",
        "early_micro_peak",
        "early_micro_auc",
        "basin_agreement",
        "t_sync",
        "sync_observed",
        "sync_duration",
        "success_difference",
        "success_loss",
        "public_knowledge_difference",
        "knowledge_loss",
    )
    _write_csv(output / "experiment-137-pairs.csv", pairs, pair_fields)  # type: ignore[arg-type]
    series_fields = (
        "seed",
        "dose",
        "cycle",
        "micro_distance",
        "meso_distance",
        "macro_distance",
        "micro_components",
        "meso_components",
        "macro_components",
    )
    _write_csv(output / "experiment-137-pair-series.csv", series, series_fields)  # type: ignore[arg-type]
    _write_csv(output / "experiment-137-gap-trace.csv", gap, series_fields)  # type: ignore[arg-type]
    _write_csv(
        output / "experiment-137-mediator-trace.csv",
        mediator,  # type: ignore[arg-type]
        series_fields,
    )
    _write_csv(
        output / "experiment-137-km.csv",
        km_rows,  # type: ignore[arg-type]
        ("endpoint", "dose", "time", "at_risk", "events", "censored", "survival"),
    )

    audit_rows: list[dict[str, object]] = []
    for pair in pairs:
        assert isinstance(pair, Mapping)
        audits = pair["kick_audits"]
        assert isinstance(audits, Sequence)
        for audit in audits:
            assert isinstance(audit, Mapping)
            audit_rows.append(
                {
                    "seed": pair["seed"],
                    "dose": pair["dose"],
                    "kick_cycles": pair["kick_cycles"],
                    **dict(audit),
                }
            )
    _write_csv(
        output / "experiment-137-kick-audits.csv",
        audit_rows,
        (
            "seed",
            "dose",
            "kick_cycles",
            "activation_cycle",
            "natural_winner_slot",
            "target_slot",
            "natural_radius",
            "requested_radius",
            "placed_radius",
            "margin_delta",
            "probe_delta",
            "margin_only_winner_slot",
            "predicted_winner_slot",
            "awarded_winner_slot",
            "margin_only_preserved",
            "probe_crossed",
        ),
    )

    primary = result["primary_cox"]
    categorical = result["categorical_cox"]
    recovery = result["recovery_survival"]
    quality = result["quality_by_dose"]
    mediation = result["primary_mediation_replication"]
    assert isinstance(primary, Mapping)
    assert isinstance(categorical, Mapping)
    assert isinstance(recovery, Mapping)
    assert isinstance(quality, Mapping)
    assert isinstance(mediation, Mapping)
    primary_coefficients = primary.get("coefficients", {})
    assert isinstance(primary_coefficients, Mapping)
    d = primary_coefficients.get("log2_dose", {})
    assert isinstance(d, Mapping)

    report = [
        "## Experiment 137 — Controlled Kick-Dose independent replication",
        "",
        f"- Config hash: `{result['config_hash']}`",
        f"- Code SHA: `{result['code_sha']}`",
        (
            f"- Eligible pairs: **{result['eligible_pair_count']}/{result['pair_count']}** "
            f"(K=1/2/4: {result['eligible_dose_counts']})"
        ),
        (
            "- 135 instrumentation dependency valid: "
            f"**{result['instrumentation_dependency_valid']}**"
        ),
        "- Experiment 136 artifact loaded: **False**",
        f"- Primary Cox stable: **{primary.get('stable')}**",
        (
            "- Primary log2-dose Cox: "
            f"beta={d.get('beta')}, HR={d.get('hazard_ratio')}, "
            f"95% CI=[{d.get('ci95_lower')}, {d.get('ci95_upper')}], "
            f"p={d.get('p_two_sided')}"
        ),
        f"- RMST nondecreasing K=1→2→4: **{result['rmst_nondecreasing']}**",
        f"- All hard invariants: **{result['all_hard_invariants']}**",
        f"- Replication gate `replication_validates`: **{result['replication_validates']}**",
        "",
        "### Dose-specific recovery and quality",
        "",
        "| K | n | recovery events | RMST(180) | mean success loss | mean knowledge loss |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for dose in (1, 2, 4):
        survival = recovery[str(dose)]
        dose_quality = quality[str(dose)]
        assert isinstance(survival, Mapping) and isinstance(dose_quality, Mapping)
        report.append(
            f"| {dose} | {survival['n']} | {survival['events']} | {survival['rmst_180']} | "
            f"{dose_quality['mean_success_loss']} | {dose_quality['mean_knowledge_loss']} |"
        )

    categorical_coefficients = categorical.get("coefficients", {})
    assert isinstance(categorical_coefficients, Mapping)
    report.extend(
        [
            "",
            "### Preregistered shape characterization",
            "",
            f"- K=2 vs K=1: `{categorical_coefficients.get('k2_vs_k1')}`",
            f"- K=4 vs K=1: `{categorical_coefficients.get('k4_vs_k1')}`",
            "",
            "### Replication mediation diagnostic",
            "",
            f"- Primary mediator (`early_micro_peak`): `{mediation}`",
            "",
            (
                "Cycles 40–53 and natural-radius values remain descriptive only and do not enter "
                "the frozen confirmatory models or gates."
            ),
            "",
            (
                "This workflow does not load or use Experiment 136 outcomes. Experiment 137 can "
                "validate only its independent replication component; the campaign-level robust "
                "claim still requires the separately frozen Experiment 136 discovery gate."
            ),
        ]
    )
    (output / "experiment-137-report.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )


__all__ = ["run_experiment_137", "write_experiment_137_outputs"]
