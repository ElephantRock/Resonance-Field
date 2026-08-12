"""Controlled kick-dose instrumentation and campaign machinery for Experiments 135–137."""

from __future__ import annotations

import csv
import json
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from resonance.market.signals import BidSignal

from . import endogenous_demand_campaign as ec
from . import lifecycle_campaign as lc
from .auction_margin_campaign import (
    MarginActivationAudit,
    MarginCellSpec,
    _MarginSignalProvider,
    _pair_series,
    _query_outcomes,
    _slot,
    preactivation_equal,
)
from .auction_margin_config import AuctionMarginConfig
from .controlled_kick_dose_config import InstrumentationCell, KickDoseConfig
from .endogenous_demand_config import (
    EndogenousDemandSpec,
    endogenous_environment,
    load_endogenous_demand_config,
)


class _BurstMarginSignalProvider:
    """Route the validated single-auction controller to a frozen set of kick cycles."""

    def __init__(
        self,
        connection: Connection[Any],
        *,
        margin_config: AuctionMarginConfig,
        experiment_number: int,
        cohort: str,
        seed: int,
        kick_cycles: Sequence[int],
    ) -> None:
        spec = MarginCellSpec("kick_near_probe", margin_config.near_radius, True)
        self.audits = {
            cycle: MarginActivationAudit(
                experiment_number=experiment_number,
                cohort=cohort,
                arm_label="kick_near_probe",
                seed=seed,
                activation_cycle=cycle,
            )
            for cycle in kick_cycles
        }
        self.providers = {
            cycle: _MarginSignalProvider(  # noqa: SLF001
                connection,
                config=margin_config,
                spec=spec,
                activation_cycle=cycle,
                audit=self.audits[cycle],
            )
            for cycle in kick_cycles
        }
        self.nonzero_adjustment_cycles: set[int] = set()

    def signal(self, task, bid, *, at) -> BidSignal:
        cycle = int(task.success_condition.get("campaign_cycle", -1))
        provider = self.providers.get(cycle)
        if provider is None:
            return BidSignal()
        signal = provider.signal(task, bid, at=at)
        if abs(signal.adjustment) > 0.0:
            self.nonzero_adjustment_cycles.add(cycle)
        return signal


def load_campaign_base(config: KickDoseConfig):
    base, _ = load_endogenous_demand_config(config.canonical_endogenous_config)
    return replace(base, integration=replace(base.integration, name=config.name))


def campaign_environment(base, config: KickDoseConfig):
    return endogenous_environment(
        base,
        cycles=config.cycles,
        shift_period=config.shift_period,
        candidate_count=config.candidate_count,
    )


def _aligned_spec(config: KickDoseConfig) -> EndogenousDemandSpec:
    return EndogenousDemandSpec(mode="closed_loop", strength=config.feedback_strength)


def _attach_rows(connection: Connection[Any], cell: dict[str, object]) -> dict[str, object]:
    cell["rows"] = _query_outcomes(connection, str(cell["run_id"]))
    return cell


def run_control_cell(
    connection: Connection[Any],
    *,
    config: KickDoseConfig,
    base,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    seed: int,
):
    environment = campaign_environment(base, config)
    cell = ec.run_endogenous_cell(
        connection,
        config=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=experiment_number,
        label="kick_dose_k0_control",
        spec=_aligned_spec(config),
        seed=seed,
        environment=environment,
    )
    return _attach_rows(connection, cell)


def run_kick_cell(
    connection: Connection[Any],
    *,
    config: KickDoseConfig,
    margin_config: AuctionMarginConfig,
    base,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    seed: int,
    dose: int,
    kick_cycles: Sequence[int],
):
    environment = campaign_environment(base, config)
    original_market = lc.PostgresMarketService
    provider_holder: list[_BurstMarginSignalProvider] = []

    class BurstMarginMarketService(original_market):
        def __init__(self, inner_connection, economy, *, bid_signal_provider=None):
            if bid_signal_provider is not None:
                raise RuntimeError("controlled-kick cells require reputation-neutral matching")
            provider = _BurstMarginSignalProvider(
                inner_connection,
                margin_config=margin_config,
                experiment_number=experiment_number,
                cohort="instrumentation" if experiment_number == 135 else "inferential",
                seed=seed,
                kick_cycles=kick_cycles,
            )
            provider_holder.append(provider)
            super().__init__(inner_connection, economy, bid_signal_provider=provider)

        def award(self, task_id, *, at):
            result = super().award(task_id, at=at)
            if result is not None and provider_holder:
                cycle = int(result.task.success_condition.get("campaign_cycle", -1))
                audit = provider_holder[0].audits.get(cycle)
                if audit is not None:
                    audit.awarded_winner_slot = _slot(result.winning_bid)
                    audit.probe_crossed = audit.awarded_winner_slot != audit.natural_winner_slot
            return result

    lc.PostgresMarketService = BurstMarginMarketService  # type: ignore[assignment]
    try:
        cell = ec.run_endogenous_cell(
            connection,
            config=base,
            config_hash=config_hash,
            code_sha=code_sha,
            experiment_number=experiment_number,
            label=f"kick_dose_k{dose}",
            spec=_aligned_spec(config),
            seed=seed,
            environment=environment,
        )
    finally:
        lc.PostgresMarketService = original_market

    if len(provider_holder) != 1:
        raise RuntimeError("controlled-kick market provider was not installed exactly once")
    provider = provider_holder[0]
    for cycle in kick_cycles:
        audit = provider.audits[cycle]
        if audit.plan_count != 1 or audit.awarded_winner_slot is None:
            raise RuntimeError(f"scheduled kick cycle {cycle} was not observed exactly once")
    cell = _attach_rows(connection, cell)
    return {
        **cell,
        "dose": dose,
        "kick_cycles": list(kick_cycles),
        "kick_audits": [provider.audits[cycle].as_dict() for cycle in kick_cycles],
        "nonzero_adjustment_cycles": sorted(provider.nonzero_adjustment_cycles),
    }


def _persist_kick_events(
    connection: Connection[Any],
    *,
    run_id: str,
    experiment_number: int,
    seed: int,
    dose: int,
    kick_cycles: Sequence[int],
    audits: Sequence[Mapping[str, object]],
) -> None:
    with connection.transaction():
        for audit in audits:
            connection.execute(
                """
                INSERT INTO controlled_kick_dose_observations (
                    run_id, experiment_number, seed, dose, scheduled_cycles, cycle,
                    natural_winner_slot, target_slot, natural_radius, requested_radius,
                    placed_radius, margin_delta, probe_delta, margin_only_winner_slot,
                    predicted_winner_slot, awarded_winner_slot, margin_only_preserved,
                    probe_crossed, audit, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, NOW()
                )
                """,
                (
                    UUID(run_id),
                    experiment_number,
                    seed,
                    dose,
                    Jsonb(list(kick_cycles)),
                    int(audit["activation_cycle"]),
                    audit["natural_winner_slot"],
                    audit["target_slot"],
                    audit["natural_radius"],
                    audit["requested_radius"],
                    audit["placed_radius"],
                    audit["margin_delta"],
                    audit["probe_delta"],
                    audit["margin_only_winner_slot"],
                    audit["predicted_winner_slot"],
                    audit["awarded_winner_slot"],
                    audit["margin_only_preserved"],
                    audit["probe_crossed"],
                    Jsonb(dict(audit)),
                ),
            )


def _persist_pair_summary(
    connection: Connection[Any],
    *,
    control_run_id: str,
    kick_run_id: str,
    experiment_number: int,
    seed: int,
    dose: int,
    summary: Mapping[str, object],
) -> None:
    with connection.transaction():
        connection.execute(
            """
            INSERT INTO controlled_kick_dose_pair_summaries (
                experiment_number, seed, dose, control_run_id, kick_run_id, summary, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                experiment_number,
                seed,
                dose,
                UUID(control_run_id),
                UUID(kick_run_id),
                Jsonb(dict(summary)),
            ),
        )


def _all_invariants(cell: Mapping[str, object]) -> bool:
    invariants = cell.get("invariants")
    return isinstance(invariants, Mapping) and all(bool(value) for value in invariants.values())


def _series_for_pair(*, control, kick, seed: int, environment, base) -> list[dict[str, object]]:
    control_rows = control["rows"]
    kick_rows = kick["rows"]
    assert isinstance(control_rows, Sequence) and isinstance(kick_rows, Sequence)
    return _pair_series(
        control_rows,  # type: ignore[arg-type]
        kick_rows,  # type: ignore[arg-type]
        seed=seed,
        env=environment,
        base=base,
        baseline_trace_cycle=None,
        perturbed_trace_cycle=None,
        perturbed_trace_multiplier=1.0,
    )


def instrumentation_pair(
    connection: Connection[Any],
    *,
    config: KickDoseConfig,
    margin_config: AuctionMarginConfig,
    base,
    config_hash: str,
    code_sha: str,
    spec: InstrumentationCell,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    control = run_control_cell(
        connection,
        config=config,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=135,
        seed=spec.seed,
    )
    kick = run_kick_cell(
        connection,
        config=config,
        margin_config=margin_config,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=135,
        seed=spec.seed,
        dose=spec.dose,
        kick_cycles=spec.kick_cycles,
    )
    environment = campaign_environment(base, config)
    series = _series_for_pair(
        control=control,
        kick=kick,
        seed=spec.seed,
        environment=environment,
        base=base,
    )
    by_cycle = {int(row["cycle"]): row for row in series}
    gap_start, gap_end = config.gap_cycles
    med_start, med_end = config.mediator_cycles
    gap = [by_cycle[cycle] for cycle in range(gap_start, gap_end + 1)]
    mediator = [by_cycle[cycle] for cycle in range(med_start, med_end + 1)]
    early_micro = [float(row["micro_distance"]) for row in mediator]
    audits = kick["kick_audits"]
    assert isinstance(audits, Sequence)
    event_checks = [
        bool(audit["margin_only_preserved"])
        and bool(audit["probe_crossed"])
        and int(audit["predicted_winner_slot"]) == int(audit["awarded_winner_slot"])
        and abs(float(audit["placed_radius"]) - config.target_radius) <= 1e-9
        for audit in audits
    ]
    nonzero_cycles = tuple(int(x) for x in kick["nonzero_adjustment_cycles"])
    pre_equal = preactivation_equal(
        connection,
        control,
        kick,
        activation_cycle=config.activation_cycle,
    )
    kick_invariants = kick["invariants"]
    assert isinstance(kick_invariants, Mapping)
    summary: dict[str, object] = {
        "experiment_number": 135,
        "seed": spec.seed,
        "dose": spec.dose,
        "kick_cycles": list(spec.kick_cycles),
        "control_run_id": str(control["run_id"]),
        "kick_run_id": str(kick["run_id"]),
        "preactivation_identity": pre_equal,
        "candidate_and_bid_identity_through_35": pre_equal,
        "scheduled_kick_count": len(spec.kick_cycles),
        "observed_activation_count": len(audits),
        "controlled_award_deviation_count": sum(bool(audit["probe_crossed"]) for audit in audits),
        "every_kick_preserved_then_crossed": all(event_checks),
        "nonzero_adjustment_cycles": list(nonzero_cycles),
        "no_adjustment_after_39": all(cycle <= 39 for cycle in nonzero_cycles),
        "control_hard_invariants": _all_invariants(control),
        "kick_hard_invariants": _all_invariants(kick),
        "reputation_neutral": bool(kick_invariants["endogenous_demand_reputation_neutral"]),
        "zero_turnover": bool(kick_invariants["identity_turnover_absent"]),
        "early_micro_peak": max(early_micro),
        "early_micro_auc": statistics.mean(early_micro),
        "gap_trace_exported_cycles": [gap_start, gap_end],
        "mediator_window_cycles": [med_start, med_end],
        "kick_audits": list(audits),
    }
    summary["instrumentation_pair_valid"] = all(
        (
            pre_equal,
            len(audits) == spec.dose,
            int(summary["controlled_award_deviation_count"]) == spec.dose,
            bool(summary["every_kick_preserved_then_crossed"]),
            bool(summary["no_adjustment_after_39"]),
            bool(summary["control_hard_invariants"]),
            bool(summary["kick_hard_invariants"]),
            bool(summary["reputation_neutral"]),
            bool(summary["zero_turnover"]),
        )
    )
    _persist_kick_events(
        connection,
        run_id=str(kick["run_id"]),
        experiment_number=135,
        seed=spec.seed,
        dose=spec.dose,
        kick_cycles=spec.kick_cycles,
        audits=audits,  # type: ignore[arg-type]
    )
    _persist_pair_summary(
        connection,
        control_run_id=str(control["run_id"]),
        kick_run_id=str(kick["run_id"]),
        experiment_number=135,
        seed=spec.seed,
        dose=spec.dose,
        summary=summary,
    )
    gap_rows = [
        {
            "seed": spec.seed,
            "dose": spec.dose,
            "cycle": int(row["cycle"]),
            "micro_distance": float(row["micro_distance"]),
            "micro_components": row["micro_components"],
        }
        for row in gap
    ]
    mediator_rows = [
        {
            "seed": spec.seed,
            "dose": spec.dose,
            "cycle": int(row["cycle"]),
            "micro_distance": float(row["micro_distance"]),
            "micro_components": row["micro_components"],
        }
        for row in mediator
    ]
    return summary, gap_rows, mediator_rows


def run_experiment_135(
    connection: Connection[Any],
    *,
    config: KickDoseConfig,
    margin_config: AuctionMarginConfig,
    config_hash: str,
    code_sha: str,
) -> dict[str, object]:
    base = load_campaign_base(config)
    summaries: list[dict[str, object]] = []
    gap_rows: list[dict[str, object]] = []
    mediator_rows: list[dict[str, object]] = []
    for spec in config.instrumentation:
        summary, gap, mediator = instrumentation_pair(
            connection,
            config=config,
            margin_config=margin_config,
            base=base,
            config_hash=config_hash,
            code_sha=code_sha,
            spec=spec,
        )
        summaries.append(summary)
        gap_rows.extend(gap)
        mediator_rows.extend(mediator)
    validated = all(bool(summary["instrumentation_pair_valid"]) for summary in summaries)
    return {
        "experiment_number": 135,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "instrumentation_validated": validated,
        "pair_count": len(summaries),
        "valid_pair_count": sum(bool(summary["instrumentation_pair_valid"]) for summary in summaries),
        "dose_counts": {
            str(dose): sum(int(summary["dose"]) == dose for summary in summaries)
            for dose in config.doses
        },
        "pairs": summaries,
        "gap_trace": gap_rows,
        "mediator_trace": mediator_rows,
        "scientific_boundary": "instrumentation_only_no_dose_survival_claim",
    }


def write_experiment_135_outputs(result: Mapping[str, object], output_dir: str | Path) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "experiment-135.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    pairs = result["pairs"]
    assert isinstance(pairs, Sequence)
    with (output / "experiment-135-pairs.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "seed",
            "dose",
            "kick_cycles",
            "preactivation_identity",
            "controlled_award_deviation_count",
            "every_kick_preserved_then_crossed",
            "no_adjustment_after_39",
            "control_hard_invariants",
            "kick_hard_invariants",
            "reputation_neutral",
            "zero_turnover",
            "early_micro_peak",
            "early_micro_auc",
            "instrumentation_pair_valid",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for pair in pairs:
            assert isinstance(pair, Mapping)
            writer.writerow(
                {
                    field: json.dumps(pair[field]) if field == "kick_cycles" else pair[field]
                    for field in fields
                }
            )
    gap = result["gap_trace"]
    assert isinstance(gap, Sequence)
    with (output / "experiment-135-gap-trace.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["seed", "dose", "cycle", "micro_distance", "micro_components"],
        )
        writer.writeheader()
        for row in gap:
            assert isinstance(row, Mapping)
            writer.writerow(
                {**row, "micro_components": json.dumps(row["micro_components"], sort_keys=True)}
            )
    report = [
        "## Experiment 135 — Controlled Kick-Dose instrumentation",
        "",
        f"- Config hash: `{result['config_hash']}`",
        f"- Code SHA: `{result['code_sha']}`",
        f"- Instrumentation validated: **{result['instrumentation_validated']}**",
        f"- Valid pairs: **{result['valid_pair_count']}/{result['pair_count']}**",
        "- Scientific boundary: **instrumentation only; no dose-survival claim**",
        "",
        (
            "| Seed | K | Schedule | Pre-ID | Deviations | Preserve→cross | "
            "No post-39 adjustment | Hard invariants | Valid |"
        ),
        "|---:|---:|---|:---:|---:|:---:|:---:|:---:|:---:|",
    ]
    for pair in pairs:
        assert isinstance(pair, Mapping)
        report.append(
            f"| {pair['seed']} | {pair['dose']} | `{pair['kick_cycles']}` | "
            f"{pair['preactivation_identity']} | {pair['controlled_award_deviation_count']} | "
            f"{pair['every_kick_preserved_then_crossed']} | {pair['no_adjustment_after_39']} | "
            f"{bool(pair['control_hard_invariants']) and bool(pair['kick_hard_invariants'])} | "
            f"**{pair['instrumentation_pair_valid']}** |"
        )
    report.extend(
        [
            "",
            (
                "The untreated cycles 40–53 micro-distance/components are exported descriptively only "
                "and cannot enter or rescue the frozen mediation test. The K=4 zero within-arm "
                "timing-variance limitation remains accepted and unchanged."
            ),
        ]
    )
    (output / "experiment-135-report.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )


__all__ = ["run_experiment_135", "write_experiment_135_outputs"]
