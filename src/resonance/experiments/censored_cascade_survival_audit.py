"""Read-only censored cascade-survival audit for Experiments 129–134."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

EXPECTED_CLASSES = {"absorbed": 19, "liminal": 6, "escape": 3, "never_crossed": 8}
SHIFT_PERIOD = {
    "discovery": 18,
    "timing_transfer": 18,
    "replication": 18,
    "holdout": 15,
}
_EPS = 1e-12


def _float(row: dict[str, str], key: str) -> float:
    return float(row[key])


def _int(row: dict[str, str], key: str) -> int:
    return int(float(row[key]))


def _bool(row: dict[str, str], key: str) -> bool:
    return row[key].strip().lower() == "true"


def _mean(values: Iterable[float]) -> float:
    xs = list(values)
    return sum(xs) / len(xs) if xs else math.nan


def _standardize(values: list[float]) -> list[float]:
    mean = _mean(values)
    variance = _mean((x - mean) ** 2 for x in values)
    sd = math.sqrt(variance)
    if sd <= _EPS:
        raise ValueError("predictor has zero variance")
    return [(x - mean) / sd for x in values]


def cox_univariate(
    durations: list[float], events: list[int], predictor: list[float]
) -> dict[str, float | bool]:
    """Fit one univariate Cox PH model with Breslow ties using Newton scoring."""
    if not (len(durations) == len(events) == len(predictor)) or not durations:
        raise ValueError("invalid Cox inputs")
    x = _standardize(predictor)
    beta = 0.0
    event_times = sorted({durations[i] for i, event in enumerate(events) if event})
    if not event_times:
        raise ValueError("Cox model requires observed recovery events")

    converged = False
    info = math.nan
    for _ in range(100):
        score = 0.0
        info = 0.0
        for t in event_times:
            event_indices = [i for i, event in enumerate(events) if event and durations[i] == t]
            d = len(event_indices)
            risk = [i for i, duration in enumerate(durations) if duration >= t]
            linear = [beta * x[i] for i in risk]
            offset = max(linear)
            weights = [math.exp(value - offset) for value in linear]
            s0 = sum(weights)
            s1 = sum(weight * x[i] for weight, i in zip(weights, risk, strict=True))
            s2 = sum(weight * x[i] * x[i] for weight, i in zip(weights, risk, strict=True))
            score += sum(x[i] for i in event_indices) - d * s1 / s0
            info += d * (s2 / s0 - (s1 / s0) ** 2)
        if info <= _EPS:
            break
        step = score / info
        beta += step
        if abs(step) < 1e-10:
            converged = True
            break

    if not converged or not math.isfinite(info) or info <= _EPS:
        return {
            "converged": False,
            "beta": beta,
            "hazard_ratio": math.exp(beta) if math.isfinite(beta) else math.nan,
            "se": math.nan,
            "z": math.nan,
            "p_two_sided": math.nan,
        }

    se = 1.0 / math.sqrt(info)
    z = beta / se
    p = math.erfc(abs(z) / math.sqrt(2.0))
    return {
        "converged": True,
        "beta": beta,
        "hazard_ratio": math.exp(beta),
        "se": se,
        "z": z,
        "p_two_sided": p,
    }


def _auc_positive_higher(positive: list[float], negative: list[float]) -> float:
    if not positive or not negative:
        return math.nan
    wins = 0.0
    for p in positive:
        for n in negative:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(positive) * len(negative))


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _pair_key(row: dict[str, str]) -> tuple[str, int]:
    return row["cohort"], _int(row, "seed")


def _classify(pair: dict[str, str], activation: int) -> tuple[bool, str]:
    recovery = _int(pair, "macro_terminal_recovery")
    crossed = recovery != activation
    if not crossed:
        return False, "never_crossed"
    if _bool(pair, "basin_disagreement"):
        return True, "escape"
    if _bool(pair, "macro_absorbed"):
        return True, "absorbed"
    return True, "liminal"


def _winner_same_flags(rows: list[dict[str, str]]) -> dict[int, bool]:
    flags: dict[int, bool] = {}
    previous_damage = 0
    for row in sorted(rows, key=lambda item: _int(item, "cycle")):
        cycle = _int(row, "cycle")
        raw_components = row["micro_components"]
        components = (
            json.loads(raw_components)
            if isinstance(raw_components, str)
            else raw_components
        )
        cumulative = int(round(float(components["winner_damage"]) * (cycle + 1)))
        increment = cumulative - previous_damage
        if increment not in (0, 1):
            raise ValueError(f"invalid cumulative winner damage at cycle {cycle}")
        flags[cycle] = increment == 0
        previous_damage = cumulative
    return flags


def _first_full_regime_sync(
    rows: list[dict[str, str]], *, activation: int, cycles: int, shift_period: int
) -> tuple[int, bool]:
    same = _winner_same_flags(rows)
    latest_start = cycles - shift_period
    for start in range(activation + 1, latest_start + 1):
        if all(same.get(cycle, False) for cycle in range(start, start + shift_period)):
            return start, True
    return cycles, False


def audit(
    pair_path: Path, cycle_path: Path
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    pairs = _load_csv(pair_path)
    cycles = _load_csv(cycle_path)
    if len(pairs) != 36:
        raise ValueError(f"expected 36 pair rows, found {len(pairs)}")

    cycle_groups: dict[tuple[str, int], list[dict[str, str]]] = {}
    for row in cycles:
        cycle_groups.setdefault(_pair_key(row), []).append(row)

    pair_rows: list[dict[str, object]] = []
    sync_rows: list[dict[str, object]] = []

    for pair in pairs:
        key = _pair_key(pair)
        rows = cycle_groups.get(key)
        if not rows:
            raise ValueError(f"missing cycle rows for {key}")
        cohort, seed = key
        activation_values = {_int(row, "activation_cycle") for row in rows}
        if len(activation_values) != 1:
            raise ValueError(f"activation mismatch for {key}")
        activation = activation_values.pop()
        cycles_count = max(_int(row, "cycle") for row in rows) + 1
        shift_period = SHIFT_PERIOD[cohort]
        crossed, classification = _classify(pair, activation)
        first_regime = [
            row for row in rows
            if activation <= _int(row, "cycle") < activation + shift_period
        ]
        if len(first_regime) != shift_period:
            raise ValueError(f"incomplete first post-activation regime for {key}")
        early_micro = [_float(row, "micro_distance") for row in first_regime]
        early_micro_peak = max(early_micro)
        early_micro_auc = _mean(early_micro)

        basin_agrees = not _bool(pair, "basin_disagreement")
        recovery_cycle = _int(pair, "macro_terminal_recovery")
        primary_eligible = crossed and basin_agrees
        recovery_observed = primary_eligible and recovery_cycle <= cycles_count
        recovery_duration = (
            recovery_cycle - activation if recovery_observed else cycles_count - activation
        )

        t_sync, sync_observed = _first_full_regime_sync(
            rows,
            activation=activation,
            cycles=cycles_count,
            shift_period=shift_period,
        )
        sync_duration = t_sync - activation if sync_observed else cycles_count - activation

        pair_row: dict[str, object] = {
            **pair,
            "activation_cycle": activation,
            "cycles": cycles_count,
            "shift_period": shift_period,
            "macro_crossed": crossed,
            "survival_class": classification,
            "primary_survival_eligible": primary_eligible,
            "recovery_observed": recovery_observed,
            "recovery_duration": recovery_duration,
            "early_micro_peak": early_micro_peak,
            "early_micro_auc": early_micro_auc,
            "t_sync": t_sync,
            "sync_observed": sync_observed,
            "sync_duration": sync_duration,
        }
        pair_rows.append(pair_row)
        sync_rows.append(
            {
                "experiment": _int(pair, "experiment"),
                "cohort": cohort,
                "seed": seed,
                "survival_class": classification,
                "activation_cycle": activation,
                "cycles": cycles_count,
                "shift_period": shift_period,
                "t_sync": t_sync,
                "sync_observed": sync_observed,
                "sync_duration": sync_duration,
                "post_activation_same_winner_share": _float(pair, "post_activation_same_winner_share"),
                "longest_same_winner_run": _int(pair, "longest_same_winner_run"),
            }
        )

    class_counts = Counter(str(row["survival_class"]) for row in pair_rows)
    reconstruction_valid = (
        dict(class_counts) == EXPECTED_CLASSES
        and all(str(row["reconstruction_valid"]).lower() == "true" for row in pair_rows)
        and sum(bool(row["macro_crossed"]) for row in pair_rows) == 28
        and sum(str(row["macro_absorbed"]).lower() == "true" for row in pair_rows) == 19
        and sum(str(row["basin_disagreement"]).lower() == "true" for row in pair_rows) == 3
    )

    primary = [row for row in pair_rows if bool(row["primary_survival_eligible"])]
    if len(primary) != 25:
        raise ValueError(f"expected 25 primary survival pairs, found {len(primary)}")
    p_duration = [float(row["recovery_duration"]) for row in primary]
    p_event = [int(bool(row["recovery_observed"])) for row in primary]

    primary_models = {
        "early_micro_peak": cox_univariate(
            p_duration, p_event, [float(row["early_micro_peak"]) for row in primary]
        ),
        "early_micro_auc": cox_univariate(
            p_duration, p_event, [float(row["early_micro_auc"]) for row in primary]
        ),
    }

    robust = [row for row in pair_rows if bool(row["macro_crossed"])]
    r_duration = [
        (
            float(row["macro_terminal_recovery"]) - float(row["activation_cycle"])
            if str(row["survival_class"]) == "absorbed"
            and int(float(row["macro_terminal_recovery"])) <= int(row["cycles"])
            else float(row["cycles"]) - float(row["activation_cycle"])
        )
        for row in robust
    ]
    r_event = [
        int(
            str(row["survival_class"]) == "absorbed"
            and int(float(row["macro_terminal_recovery"])) <= int(row["cycles"])
        )
        for row in robust
    ]
    robustness_models = {
        "early_micro_peak": cox_univariate(
            r_duration, r_event, [float(row["early_micro_peak"]) for row in robust]
        ),
        "early_micro_auc": cox_univariate(
            r_duration, r_event, [float(row["early_micro_auc"]) for row in robust]
        ),
    }

    model_values = list(primary_models.values())
    survival_stable = all(bool(model["converged"]) for model in model_values) and all(
        bool(model["converged"]) for model in robustness_models.values()
    )
    survival_supported = (
        survival_stable
        and reconstruction_valid
        and all(float(model["beta"]) < 0 for model in model_values)
        and all(float(model["p_two_sided"]) <= 0.10 for model in model_values)
        and min(float(model["p_two_sided"]) for model in model_values) <= 0.025
        and all(float(model["beta"]) < 0 for model in robustness_models.values())
    )

    difficult = [
        float(row["sync_duration"])
        for row in pair_rows
        if str(row["survival_class"]) in {"escape", "liminal"}
    ]
    easy = [
        float(row["sync_duration"])
        for row in pair_rows
        if str(row["survival_class"]) in {"absorbed", "never_crossed"}
    ]
    sync_auc = _auc_positive_higher(difficult, easy)
    ranges_overlap = not (min(difficult) > max(easy) or max(difficult) < min(easy))
    winner_proxy = (
        "winner_proxy_strong_directional"
        if sync_auc >= 0.80
        else "winner_proxy_weak_or_overlap"
    )

    escape = [float(row["sync_duration"]) for row in pair_rows if str(row["survival_class"]) == "escape"]
    liminal = [float(row["sync_duration"]) for row in pair_rows if str(row["survival_class"]) == "liminal"]
    escape_liminal_auc = _auc_positive_higher(escape, liminal)

    if not reconstruction_valid or not survival_stable:
        recommendation = "no_new_family_justified"
        survival_conclusion = "survival_signal_not_supported"
    elif survival_supported:
        recommendation = "preregister_minimal_controlled_kick_size_recovery_time_campaign"
        survival_conclusion = "survival_signal_supported"
    else:
        recommendation = "build_discrete_causal_event_instrumentation_before_branch_cascade_family"
        survival_conclusion = "survival_signal_not_supported"

    result: dict[str, object] = {
        "source_audit_commit": "ba424566d754aa2338730837261808dc2af2e2bb",
        "source_audit_issue": 60,
        "audit_issue": 62,
        "pair_count": len(pair_rows),
        "class_counts": dict(class_counts),
        "macro_crossed_count": sum(bool(row["macro_crossed"]) for row in pair_rows),
        "primary_survival_pair_count": len(primary),
        "primary_recovery_events": sum(p_event),
        "primary_right_censored": len(primary) - sum(p_event),
        "reconstruction_valid": reconstruction_valid,
        "primary_models": primary_models,
        "robustness_models_all_macro_crossed": robustness_models,
        "survival_model_stable": survival_stable,
        "survival_conclusion": survival_conclusion,
        "winner_proxy": {
            "conclusion": winner_proxy,
            "difficult_count": len(difficult),
            "easy_count": len(easy),
            "sync_duration_auc": sync_auc,
            "range_overlap": ranges_overlap,
            "difficult_range": [min(difficult), max(difficult)],
            "easy_range": [min(easy), max(easy)],
            "escape_vs_liminal_auc_descriptive": escape_liminal_auc,
            "escape_range": [min(escape), max(escape)],
            "liminal_range": [min(liminal), max(liminal)],
        },
        "next_recommendation": recommendation,
        "interpretation_limits": [
            "Association is censored cascade-survival evidence, not a causal scaling exponent.",
            "No directed-percolation or universality-class claim is available.",
            "Winner synchronization is a low-capacity proxy, not an R_D estimate.",
            "No Experiment 135+ is authorized by this audit.",
        ],
    }
    return result, pair_rows, sync_rows


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError("cannot write empty CSV")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _report(result: dict[str, object]) -> str:
    primary = result["primary_models"]
    robust = result["robustness_models_all_macro_crossed"]
    winner = result["winner_proxy"]
    assert isinstance(primary, dict) and isinstance(robust, dict) and isinstance(winner, dict)
    lines = [
        "<!-- censored-cascade-survival-audit:result -->",
        "## Censored Cascade-Survival Audit — 129–134",
        "",
        f"- Reconstruction valid: **{result['reconstruction_valid']}**",
        f"- Historical pairs: **{result['pair_count']}**",
        f"- Class counts: **{result['class_counts']}**",
        f"- Primary survival pairs: **{result['primary_survival_pair_count']}**",
        f"- Observed recoveries: **{result['primary_recovery_events']}**",
        f"- Right-censored: **{result['primary_right_censored']}**",
        f"- Survival conclusion: **{result['survival_conclusion']}**",
        f"- Winner proxy: **{winner['conclusion']}**",
        f"- Next recommendation: **{result['next_recommendation']}**",
        "",
        "### Primary Cox models",
        "",
        "| Predictor | HR per +1 SD | beta | Wald p (two-sided) |",
        "|---|---:|---:|---:|",
    ]
    for name in ("early_micro_peak", "early_micro_auc"):
        model = primary[name]
        lines.append(
            f"| {name} | {float(model['hazard_ratio']):.6f} | "
            f"{float(model['beta']):+.6f} | {float(model['p_two_sided']):.6f} |"
        )
    lines += [
        "",
        "### All-macro-crossed robustness",
        "",
        "| Predictor | HR per +1 SD | beta | Wald p (two-sided) |",
        "|---|---:|---:|---:|",
    ]
    for name in ("early_micro_peak", "early_micro_auc"):
        model = robust[name]
        lines.append(
            f"| {name} | {float(model['hazard_ratio']):.6f} | "
            f"{float(model['beta']):+.6f} | {float(model['p_two_sided']):.6f} |"
        )
    lines += [
        "",
        "### Winner-disagreement proxy",
        "",
        f"- Difficult group (`escape + liminal`) n: **{winner['difficult_count']}**",
        f"- Recovered/never-crossed group n: **{winner['easy_count']}**",
        f"- `T_sync` ordering AUC: **{float(winner['sync_duration_auc']):.6f}**",
        f"- Exact duration-range overlap: **{winner['range_overlap']}**",
        f"- Difficult duration range: **{winner['difficult_range']}**",
        f"- Easy duration range: **{winner['easy_range']}**",
        "- Escape-vs-liminal AUC (descriptive only): "
        f"**{float(winner['escape_vs_liminal_auc_descriptive']):.6f}**",
        "",
        "### Interpretation",
        "",
        "The primary predictors use only the first complete post-activation regime. "
        "Full-horizon divergence summaries are not used to satisfy the gate. "
        "A supported result establishes a censored association between early microscopic damage "
        "and slower macroscopic recovery; it does not establish directed percolation, a critical exponent, "
        "or a branching-process reproduction number.",
        "",
        "No Experiment 135+ was run or authorized by this audit.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair-summary", type=Path, required=True)
    parser.add_argument("--cycle-components", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result, pair_rows, sync_rows = audit(args.pair_summary, args.cycle_components)
    (args.out_dir / "censored-cascade-survival-audit.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_csv(args.out_dir / "survival-pairs.csv", pair_rows)
    _write_csv(args.out_dir / "winner-sync.csv", sync_rows)
    (args.out_dir / "censored-cascade-survival-report.md").write_text(
        _report(result), encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
