"""Frozen discovery analysis for Controlled Kick-Dose Experiment 136."""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from psycopg import Connection

from .auction_margin_campaign import _final_public_knowledge, preactivation_equal
from .auction_margin_config import AuctionMarginConfig
from .chaos_predictability_campaign import _basin_class
from .chaos_predictability_config import load_chaos_predictability_config
from .censored_cascade_survival_audit import _first_full_regime_sync
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

_CHAOS_CONFIG_PATH = "configs/experiments/chaos-predictability-123-128.json"
_EPS = 1e-12


def dose_for_seed(seed: int, *, first_seed: int) -> int:
    """Return the frozen modulo-3 dose assignment."""
    offset = seed - first_seed
    if offset < 0:
        raise ValueError("seed precedes cohort")
    return (1, 2, 4)[offset % 3]


def schedule_for_seed(
    config: KickDoseConfig,
    *,
    seed: int,
    cohort_seeds: Sequence[int],
) -> tuple[int, tuple[int, ...]]:
    """Assign the predeclared timing sequence by within-dose ordinal."""
    if seed not in cohort_seeds:
        raise ValueError("seed is not in the frozen cohort")
    first_seed = min(cohort_seeds)
    dose = dose_for_seed(seed, first_seed=first_seed)
    same_dose = [
        value
        for value in sorted(cohort_seeds)
        if dose_for_seed(value, first_seed=first_seed) == dose
    ]
    ordinal = same_dose.index(seed)
    templates = tuple(config.timing_sequences[dose])
    return dose, templates[ordinal % len(templates)]


def _invert_information(info: Sequence[Sequence[float]]) -> list[list[float]] | None:
    size = len(info)
    if size == 1:
        value = float(info[0][0])
        if not math.isfinite(value) or value <= _EPS:
            return None
        return [[1.0 / value]]
    if size == 2:
        a = float(info[0][0])
        b = float(info[0][1])
        c = float(info[1][0])
        d = float(info[1][1])
        det = a * d - b * c
        scale = max(abs(a * d), abs(b * c), 1.0)
        if not math.isfinite(det) or abs(det) <= _EPS * scale:
            return None
        return [[d / det, -b / det], [-c / det, a / det]]
    raise ValueError("only one- and two-covariate Cox models are preregistered")


def _matvec(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> list[float]:
    return [
        sum(float(value) * float(vector[index]) for index, value in enumerate(row))
        for row in matrix
    ]


def _cox_score_information(
    durations: Sequence[float],
    events: Sequence[int],
    covariates: Sequence[Sequence[float]],
    beta: Sequence[float],
) -> tuple[list[float], list[list[float]]]:
    p = len(beta)
    score = [0.0 for _ in range(p)]
    information = [[0.0 for _ in range(p)] for _ in range(p)]
    event_times = sorted({float(durations[i]) for i, event in enumerate(events) if event})
    for time in event_times:
        event_indices = [
            i for i, event in enumerate(events) if event and float(durations[i]) == time
        ]
        risk = [i for i, duration in enumerate(durations) if float(duration) >= time]
        linear = [
            sum(float(beta[j]) * float(covariates[i][j]) for j in range(p)) for i in risk
        ]
        offset = max(linear)
        weights = [math.exp(value - offset) for value in linear]
        s0 = sum(weights)
        means = [
            sum(weight * float(covariates[i][j]) for weight, i in zip(weights, risk, strict=True))
            / s0
            for j in range(p)
        ]
        second = [
            [
                sum(
                    weight * float(covariates[i][j]) * float(covariates[i][k])
                    for weight, i in zip(weights, risk, strict=True)
                )
                / s0
                for k in range(p)
            ]
            for j in range(p)
        ]
        count = len(event_indices)
        for j in range(p):
            score[j] += sum(float(covariates[i][j]) for i in event_indices) - count * means[j]
            for k in range(p):
                information[j][k] += count * (second[j][k] - means[j] * means[k])
    return score, information


def cox_ph(
    durations: Sequence[float],
    events: Sequence[int],
    covariates: Sequence[Sequence[float]],
    *,
    names: Sequence[str],
) -> dict[str, object]:
    """Fit a one- or two-covariate Cox PH model with Breslow ties."""
    n = len(durations)
    if n == 0 or len(events) != n or len(covariates) != n:
        raise ValueError("invalid Cox inputs")
    p = len(names)
    if p not in (1, 2) or any(len(row) != p for row in covariates):
        raise ValueError("invalid Cox design")
    if not any(events):
        return {"converged": False, "stable": False, "reason": "no_observed_events"}
    for column in range(p):
        values = [float(row[column]) for row in covariates]
        if max(values) - min(values) <= _EPS:
            return {
                "converged": False,
                "stable": False,
                "reason": f"zero_variance:{names[column]}",
            }

    beta = [0.0 for _ in range(p)]
    converged = False
    reason = "maximum_iterations"
    for _ in range(100):
        score, information = _cox_score_information(durations, events, covariates, beta)
        inverse = _invert_information(information)
        if inverse is None:
            reason = "singular_information"
            break
        step = _matvec(inverse, score)
        if not all(math.isfinite(value) for value in step):
            reason = "nonfinite_newton_step"
            break
        beta = [beta[index] + step[index] for index in range(p)]
        if not all(math.isfinite(value) and abs(value) < 50.0 for value in beta):
            reason = "complete_or_quasi_complete_separation"
            break
        if max(abs(value) for value in step) < 1e-10:
            converged = True
            reason = "ok"
            break

    coefficients: dict[str, dict[str, float]] = {}
    stable = False
    if converged:
        _, information = _cox_score_information(durations, events, covariates, beta)
        covariance = _invert_information(information)
        if covariance is None:
            reason = "singular_final_information"
        else:
            stable = True
            for index, name in enumerate(names):
                variance = float(covariance[index][index])
                if variance <= 0 or not math.isfinite(variance):
                    stable = False
                    reason = "nonfinite_standard_error"
                    break
                se = math.sqrt(variance)
                z = beta[index] / se
                lower_beta = beta[index] - 1.96 * se
                upper_beta = beta[index] + 1.96 * se
                values = {
                    "beta": beta[index],
                    "se": se,
                    "z": z,
                    "p_two_sided": math.erfc(abs(z) / math.sqrt(2.0)),
                    "hazard_ratio": math.exp(beta[index]),
                    "ci95_lower": math.exp(lower_beta),
                    "ci95_upper": math.exp(upper_beta),
                }
                if not all(math.isfinite(value) for value in values.values()):
                    stable = False
                    reason = "nonfinite_coefficient_output"
                    break
                coefficients[name] = values

    return {
        "converged": converged,
        "stable": stable,
        "reason": reason,
        "n": n,
        "events": sum(int(bool(value)) for value in events),
        "coefficients": coefficients,
    }


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    max_iterations = 300
    fpmin = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iterations + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-14:
            return h
    raise RuntimeError("incomplete-beta continued fraction did not converge")


def _regularized_beta(x: float, a: float, b: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_term = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    bt = math.exp(log_term)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _beta_continued_fraction(a, b, x) / a
    return 1.0 - bt * _beta_continued_fraction(b, a, 1.0 - x) / b


def _student_t_two_sided_p(t_value: float, degrees_freedom: int) -> float:
    if degrees_freedom <= 0:
        return math.nan
    x = degrees_freedom / (degrees_freedom + t_value * t_value)
    return _regularized_beta(x, degrees_freedom / 2.0, 0.5)


def ols_linear(x: Sequence[float], y: Sequence[float]) -> dict[str, float | bool]:
    """Fit OLS y ~ 1 + x and report the conventional Student-t slope test."""
    n = len(x)
    if n != len(y) or n < 3:
        raise ValueError("invalid OLS inputs")
    mean_x = statistics.mean(float(value) for value in x)
    mean_y = statistics.mean(float(value) for value in y)
    sxx = sum((float(value) - mean_x) ** 2 for value in x)
    if sxx <= _EPS:
        return {"stable": False}
    slope = sum(
        (float(x_value) - mean_x) * (float(y_value) - mean_y)
        for x_value, y_value in zip(x, y, strict=True)
    ) / sxx
    intercept = mean_y - slope * mean_x
    residuals = [
        float(y_value) - intercept - slope * float(x_value)
        for x_value, y_value in zip(x, y, strict=True)
    ]
    df = n - 2
    residual_variance = sum(value * value for value in residuals) / df
    se = math.sqrt(max(0.0, residual_variance / sxx))
    if se <= _EPS:
        return {
            "stable": False,
            "slope": slope,
            "intercept": intercept,
            "reason": "zero_residual_standard_error",
        }
    t_value = slope / se
    return {
        "stable": True,
        "n": float(n),
        "df": float(df),
        "intercept": intercept,
        "slope": slope,
        "se": se,
        "t": t_value,
        "p_two_sided": _student_t_two_sided_p(t_value, df),
    }


def standardize(values: Sequence[float]) -> list[float]:
    """Use the #62 population-SD z-score convention for the mediator."""
    mean = statistics.mean(float(value) for value in values)
    variance = statistics.mean((float(value) - mean) ** 2 for value in values)
    sd = math.sqrt(variance)
    if sd <= _EPS:
        raise ValueError("mediator has zero variance")
    return [(float(value) - mean) / sd for value in values]


def kaplan_meier(
    durations: Sequence[int],
    events: Sequence[int],
    *,
    horizon: int,
) -> tuple[list[dict[str, float | int]], float]:
    """Return KM step points and RMST through the fixed horizon."""
    if not durations or len(durations) != len(events):
        raise ValueError("invalid Kaplan-Meier inputs")
    survival = 1.0
    previous = 0
    rmst = 0.0
    points: list[dict[str, float | int]] = [
        {"time": 0, "at_risk": len(durations), "events": 0, "censored": 0, "survival": 1.0}
    ]
    for time in sorted({int(value) for value in durations if int(value) <= horizon}):
        rmst += survival * (time - previous)
        at_risk = sum(int(duration) >= time for duration in durations)
        event_count = sum(
            int(duration) == time and bool(event)
            for duration, event in zip(durations, events, strict=True)
        )
        censored_count = sum(
            int(duration) == time and not bool(event)
            for duration, event in zip(durations, events, strict=True)
        )
        if at_risk and event_count:
            survival *= 1.0 - event_count / at_risk
        points.append(
            {
                "time": time,
                "at_risk": at_risk,
                "events": event_count,
                "censored": censored_count,
                "survival": survival,
            }
        )
        previous = time
    if previous < horizon:
        rmst += survival * (horizon - previous)
    return points, rmst


def _final_basin(
    control_rows: Sequence[Mapping[str, object]],
    kick_rows: Sequence[Mapping[str, object]],
    *,
    env,
) -> tuple[str, str]:
    protocol, _ = load_chaos_predictability_config(_CHAOS_CONFIG_PATH)
    final_control = [
        row for row in control_rows if int(row["cycle"]) >= env.cycles - 2 * env.shift_period
    ]
    reference_success = statistics.mean(float(bool(row["success"])) for row in final_control)
    control_basin, _, _ = _basin_class(
        control_rows,
        env=env,
        reference_success=reference_success,
        protocol=protocol,
    )
    kick_basin, _, _ = _basin_class(
        kick_rows,
        env=env,
        reference_success=reference_success,
        protocol=protocol,
    )
    return control_basin, kick_basin


def _inferential_pair(
    connection: Connection[Any],
    *,
    config: KickDoseConfig,
    margin_config: AuctionMarginConfig,
    base,
    config_hash: str,
    code_sha: str,
    seed: int,
    dose: int,
    kick_cycles: Sequence[int],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    control = run_control_cell(
        connection,
        config=config,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=136,
        seed=seed,
    )
    kick = run_kick_cell(
        connection,
        config=config,
        margin_config=margin_config,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=136,
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
        "experiment_number": 136,
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
        experiment_number=136,
        seed=seed,
        dose=dose,
        kick_cycles=kick_cycles,
        audits=audits,  # type: ignore[arg-type]
    )
    _persist_pair_summary(
        connection,
        control_run_id=str(control["run_id"]),
        kick_run_id=str(kick["run_id"]),
        experiment_number=136,
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


def _dose_quality(
    pairs: Sequence[Mapping[str, object]],
    *,
    doses: Sequence[int],
) -> dict[str, dict[str, float | int]]:
    result: dict[str, dict[str, float | int]] = {}
    for dose in doses:
        cells = [pair for pair in pairs if int(pair["dose"]) == dose and bool(pair["pair_eligible"])]
        if not cells:
            result[str(dose)] = {
                "eligible_pairs": 0,
                "mean_success_loss": math.nan,
                "mean_knowledge_loss": math.nan,
            }
            continue
        result[str(dose)] = {
            "eligible_pairs": len(cells),
            "mean_success_loss": statistics.mean(float(pair["success_loss"]) for pair in cells),
            "mean_knowledge_loss": statistics.mean(float(pair["knowledge_loss"]) for pair in cells),
        }
    return result


def _dose_survival(
    pairs: Sequence[Mapping[str, object]],
    *,
    doses: Sequence[int],
    horizon: int,
) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    summaries: dict[str, dict[str, object]] = {}
    rows: list[dict[str, object]] = []
    for dose in doses:
        cells = [pair for pair in pairs if int(pair["dose"]) == dose and bool(pair["pair_eligible"])]
        durations = [int(pair["recovery_duration"]) for pair in cells]
        events = [int(bool(pair["recovery_observed"])) for pair in cells]
        if not cells:
            summaries[str(dose)] = {"n": 0, "events": 0, "rmst_180": math.nan}
            continue
        points, rmst = kaplan_meier(durations, events, horizon=horizon)
        summaries[str(dose)] = {"n": len(cells), "events": sum(events), "rmst_180": rmst}
        rows.extend({"endpoint": "recovery", "dose": dose, **point} for point in points)
    return summaries, rows


def _sync_survival(
    pairs: Sequence[Mapping[str, object]],
    *,
    doses: Sequence[int],
    horizon: int,
) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    summaries: dict[str, dict[str, object]] = {}
    rows: list[dict[str, object]] = []
    for dose in doses:
        cells = [pair for pair in pairs if int(pair["dose"]) == dose and bool(pair["pair_eligible"])]
        durations = [int(pair["sync_duration"]) for pair in cells]
        events = [int(bool(pair["sync_observed"])) for pair in cells]
        if not cells:
            summaries[str(dose)] = {"n": 0, "events": 0}
            continue
        points, _ = kaplan_meier(durations, events, horizon=horizon)
        summaries[str(dose)] = {"n": len(cells), "events": sum(events)}
        rows.extend({"endpoint": "winner_sync", "dose": dose, **point} for point in points)
    return summaries, rows


def _mediation_analysis(
    eligible: Sequence[Mapping[str, object]],
    *,
    mediator_key: str,
    model1: Mapping[str, object],
) -> dict[str, object]:
    d = [float(pair["log2_dose"]) for pair in eligible]
    mediator = [float(pair[mediator_key]) for pair in eligible]
    durations = [float(pair["recovery_duration"]) for pair in eligible]
    events = [int(bool(pair["recovery_observed"])) for pair in eligible]
    link_a = ols_linear(d, mediator)
    try:
        mediator_z = standardize(mediator)
    except ValueError:
        return {
            "mediator": mediator_key,
            "link_a": link_a,
            "conditional_cox": {
                "converged": False,
                "stable": False,
                "reason": "zero_variance_mediator",
            },
            "attenuation": math.nan,
            "discovery_conditions_met": False,
        }
    conditional = cox_ph(
        durations,
        events,
        [[d_value, z_value] for d_value, z_value in zip(d, mediator_z, strict=True)],
        names=("log2_dose", f"{mediator_key}_z"),
    )
    model1_coefficients = model1.get("coefficients")
    conditional_coefficients = conditional.get("coefficients")
    attenuation = math.nan
    if isinstance(model1_coefficients, Mapping) and isinstance(conditional_coefficients, Mapping):
        first = model1_coefficients.get("log2_dose")
        second = conditional_coefficients.get("log2_dose")
        if isinstance(first, Mapping) and isinstance(second, Mapping):
            beta1 = float(first["beta"])
            beta2 = float(second["beta"])
            if abs(beta1) > _EPS:
                attenuation = 1.0 - abs(beta2) / abs(beta1)
    mediator_coeff = None
    if isinstance(conditional_coefficients, Mapping):
        value = conditional_coefficients.get(f"{mediator_key}_z")
        if isinstance(value, Mapping):
            mediator_coeff = value
    discovery_conditions = (
        bool(link_a.get("stable"))
        and float(link_a.get("slope", math.nan)) > 0.0
        and float(link_a.get("p_two_sided", math.inf)) <= 0.05
        and bool(conditional.get("stable"))
        and isinstance(mediator_coeff, Mapping)
        and float(mediator_coeff["beta"]) < 0.0
        and float(mediator_coeff["p_two_sided"]) <= 0.05
        and math.isfinite(attenuation)
        and attenuation >= 0.20
        and bool(model1.get("stable"))
    )
    return {
        "mediator": mediator_key,
        "link_a": link_a,
        "conditional_cox": conditional,
        "attenuation": attenuation,
        "discovery_conditions_met": discovery_conditions,
    }


def run_experiment_136(
    connection: Connection[Any],
    *,
    config: KickDoseConfig,
    margin_config: AuctionMarginConfig,
    config_hash: str,
    code_sha: str,
    instrumentation_135: Mapping[str, object],
) -> dict[str, object]:
    """Run the frozen 36-pair discovery cohort and preregistered analyses."""
    instrumentation_validated = bool(instrumentation_135.get("instrumentation_validated"))
    instrumentation_hash_matches = str(instrumentation_135.get("config_hash")) == config_hash
    base = load_campaign_base(config)
    pairs: list[dict[str, object]] = []
    series_rows: list[dict[str, object]] = []
    for seed in config.discovery_seeds:
        dose, schedule = schedule_for_seed(
            config,
            seed=seed,
            cohort_seeds=config.discovery_seeds,
        )
        pair, series = _inferential_pair(
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
    primary_mediation = _mediation_analysis(
        eligible,
        mediator_key="early_micro_peak",
        model1=primary_cox,
    )
    sensitivity_mediation = _mediation_analysis(
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
        and float(quality[str(dose)]["mean_success_loss"]) <= config.maximum_success_loss + _EPS
        for dose in config.doses
    )
    quality_knowledge = all(
        int(quality[str(dose)]["eligible_pairs"]) > 0
        and float(quality[str(dose)]["mean_knowledge_loss"]) <= config.maximum_knowledge_loss + _EPS
        for dose in config.doses
    )
    primary_direction_significant = (
        bool(primary_cox.get("stable"))
        and isinstance(primary_d, Mapping)
        and float(primary_d["beta"]) < 0.0
        and float(primary_d["p_two_sided"]) <= config.alpha
    )
    supported = all(
        (
            instrumentation_validated,
            instrumentation_hash_matches,
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
        "experiment_number": 136,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "instrumentation_135_validated": instrumentation_validated,
        "instrumentation_135_config_hash_matches": instrumentation_hash_matches,
        "pair_count": len(pairs),
        "eligible_pair_count": len(eligible),
        "dose_counts": {
            str(dose): sum(int(pair["dose"]) == dose for pair in pairs) for dose in config.doses
        },
        "eligible_dose_counts": {
            str(dose): sum(
                int(pair["dose"]) == dose and bool(pair["pair_eligible"]) for pair in pairs
            )
            for dose in config.doses
        },
        "primary_cox": primary_cox,
        "categorical_cox": categorical_cox,
        "recovery_survival": recovery_survival,
        "rmst_nondecreasing": rmst_nondecreasing,
        "quality_by_dose": quality,
        "all_hard_invariants": all_hard_invariants,
        "primary_mediation_discovery": primary_mediation,
        "sensitivity_mediation_discovery": sensitivity_mediation,
        "winner_sync_survival": sync_survival,
        "kick_survival_dose_response_supported": supported,
        "pairs": pairs,
        "pair_series": series_rows,
        "gap_trace": gap_rows,
        "mediator_trace": mediator_rows,
        "km_rows": recovery_km_rows + sync_km_rows,
        "natural_radius_diagnostic_role": "descriptive_only_not_in_confirmatory_models",
        "interpretation_boundary": "discovery_only_replication_required_for_robust_causal_claim",
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]], fields: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            encoded = {
                field: (
                    json.dumps(row.get(field), sort_keys=True)
                    if isinstance(row.get(field), (dict, list, tuple))
                    else row.get(field)
                )
                for field in fields
            }
            writer.writerow(encoded)


def write_experiment_136_outputs(result: Mapping[str, object], output_dir: str | Path) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "experiment-136.json").write_text(
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
    _write_csv(output / "experiment-136-pairs.csv", pairs, pair_fields)  # type: ignore[arg-type]
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
    _write_csv(output / "experiment-136-pair-series.csv", series, series_fields)  # type: ignore[arg-type]
    _write_csv(output / "experiment-136-gap-trace.csv", gap, series_fields)  # type: ignore[arg-type]
    _write_csv(
        output / "experiment-136-mediator-trace.csv",
        mediator,  # type: ignore[arg-type]
        series_fields,
    )
    _write_csv(
        output / "experiment-136-km.csv",
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
        output / "experiment-136-kick-audits.csv",
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
    mediation = result["primary_mediation_discovery"]
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
        "## Experiment 136 — Controlled Kick-Dose discovery",
        "",
        f"- Config hash: `{result['config_hash']}`",
        f"- Code SHA: `{result['code_sha']}`",
        (
            f"- Eligible pairs: **{result['eligible_pair_count']}/{result['pair_count']}** "
            f"(K=1/2/4: {result['eligible_dose_counts']})"
        ),
        f"- 135 instrumentation dependency valid: **{result['instrumentation_135_validated']}**",
        f"- Primary Cox stable: **{primary.get('stable')}**",
        (
            "- Primary log2-dose Cox: "
            f"beta={d.get('beta')}, HR={d.get('hazard_ratio')}, "
            f"95% CI=[{d.get('ci95_lower')}, {d.get('ci95_upper')}], "
            f"p={d.get('p_two_sided')}"
        ),
        f"- RMST nondecreasing K=1→2→4: **{result['rmst_nondecreasing']}**",
        f"- All hard invariants: **{result['all_hard_invariants']}**",
        (
            "- Discovery causal gate `kick_survival_dose_response_supported`: "
            f"**{result['kick_survival_dose_response_supported']}**"
        ),
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
            "### Discovery mediation diagnostic",
            "",
            f"- Primary mediator (`early_micro_peak`): `{mediation}`",
            "",
            (
                "The cycles 40–53 gap trace and all natural-radius values are exported descriptively "
                "only. They are not p-valued, covariates, dose weights, exclusions, strata, mediators, "
                "or rescue variables in the frozen confirmatory analysis."
            ),
            "",
            (
                "Experiment 136 is discovery only. A robust causal dose-survival conclusion remains "
                "unavailable unless Experiment 137 independently replicates the frozen gate."
            ),
        ]
    )
    (output / "experiment-136-report.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "cox_ph",
    "dose_for_seed",
    "kaplan_meier",
    "ols_linear",
    "run_experiment_136",
    "schedule_for_seed",
    "write_experiment_136_outputs",
]
