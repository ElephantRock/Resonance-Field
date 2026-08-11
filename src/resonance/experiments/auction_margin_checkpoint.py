"""Checkpoint state machine for Auction Margin Control Experiments 129–134."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from psycopg import Connection

from .auction_margin_campaign import (
    evaluate_cohort,
    instrumentation_specs,
    load_canonical_base,
    local_crossing,
    pair_summary,
    persist_pair_summary,
    preactivation_equal,
    primary_specs,
    run_margin_cell,
)
from .auction_margin_config import AuctionMarginConfig, MarginEnvironment

_CHECKPOINT_VERSION = 1
_FIRST = 129
_LAST = 134
_RADIUS_TOLERANCE = 1e-9


def _initial_state(*, protocol: AuctionMarginConfig, config_hash: str, code_sha: str) -> dict[str, object]:
    return {
        "version": _CHECKPOINT_VERSION,
        "campaign": protocol.name,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "last_completed": 128,
        "next_experiment": 129,
        "instrumentation_validated": False,
        "local_crossing_validated": False,
        "discovery_propagation_validated": False,
        "discovery_classification": None,
        "timing_transfer_validated": False,
        "replication_validated": False,
        "holdout_validated": False,
        "robust_auction_margin_control": False,
    }


def _validate_state(
    state: Mapping[str, object],
    *,
    number: int,
    protocol: AuctionMarginConfig,
    config_hash: str,
    code_sha: str,
) -> None:
    if int(state.get("version", -1)) != _CHECKPOINT_VERSION:
        raise ValueError("unsupported auction-margin checkpoint version")
    if state.get("campaign") != protocol.name or state.get("config_hash") != config_hash:
        raise ValueError("auction-margin checkpoint configuration mismatch")
    if state.get("code_sha") != code_sha:
        raise ValueError("auction-margin checkpoint code SHA mismatch")
    if int(state.get("last_completed", -1)) != number - 1:
        raise ValueError("auction-margin checkpoint does not immediately precede experiment")
    if int(state.get("next_experiment", -1)) != number:
        raise ValueError("auction-margin checkpoint next experiment mismatch")


def _record(
    *,
    number: int,
    focus: str,
    question: str,
    validated: bool,
    next_focus: str | None,
    extras: Mapping[str, object],
) -> dict[str, object]:
    return {
        "number": number,
        "focus": focus,
        "question": question,
        "causal_family": "auction_margin_control",
        "validated": validated,
        "next_experiment_focus": next_focus,
        **dict(extras),
    }


def _all_invariants(cells: Mapping[str, Mapping[str, object]]) -> bool:
    for cell in cells.values():
        invariants = cell["invariants"]
        assert isinstance(invariants, Mapping)
        if not all(bool(value) for value in invariants.values()):
            return False
    return True


def _activation(cell: Mapping[str, object]) -> Mapping[str, object]:
    value = cell["margin_audit"]
    assert isinstance(value, Mapping)
    return value


def _run_seed(
    connection: Connection[Any],
    *,
    protocol: AuctionMarginConfig,
    base,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    cohort: str,
    seed: int,
    environment: MarginEnvironment,
    instrumentation: bool = False,
) -> dict[str, object]:
    specs = instrumentation_specs(protocol) if instrumentation else primary_specs(protocol)
    cells = {
        spec.label: run_margin_cell(
            connection,
            config=protocol,
            base=base,
            config_hash=config_hash,
            code_sha=code_sha,
            experiment_number=experiment_number,
            cohort=cohort,
            seed=seed,
            environment_spec=environment,
            spec=spec,
            through_activation=instrumentation,
        )
        for spec in specs
    }
    reference = cells["natural_no_probe"]
    preactivation = all(
        preactivation_equal(
            connection,
            reference,
            cell,
            activation_cycle=environment.activation_cycle,
        )
        for cell in cells.values()
    )
    result: dict[str, object] = {
        "seed": seed,
        "preactivation_equal": preactivation,
        "all_invariants": _all_invariants(cells),
        "activations": {label: dict(_activation(cell)) for label, cell in cells.items()},
        "near_crossed": local_crossing(cells["near_probe"]),
        "buffered_crossed": local_crossing(cells["buffered_probe"]),
        "natural_probe_crossed": local_crossing(cells["natural_probe"]),
    }
    if instrumentation:
        natural_winner = int(_activation(reference)["awarded_winner_slot"])
        near_no = _activation(cells["near_no_probe"])
        buffered_no = _activation(cells["buffered_no_probe"])
        result.update(
            {
                "near_no_probe_preserved": int(near_no["awarded_winner_slot"]) == natural_winner,
                "buffered_no_probe_preserved": int(buffered_no["awarded_winner_slot"]) == natural_winner,
                "near_radius_error": abs(float(near_no["placed_radius"]) - protocol.near_radius),
                "buffered_radius_error": abs(
                    float(buffered_no["placed_radius"]) - protocol.buffered_radius
                ),
            }
        )
    else:
        summary = pair_summary(
            config=protocol,
            base=base,
            seed=seed,
            environment_spec=environment,
            near=cells["near_probe"],
            buffered=cells["buffered_probe"],
        )
        persist_pair_summary(
            connection,
            experiment_number=experiment_number,
            cohort=cohort,
            seed=seed,
            near_run_id=str(cells["near_probe"]["run_id"]),
            buffered_run_id=str(cells["buffered_probe"]["run_id"]),
            summary=summary,
        )
        result["pair_summary"] = summary
        result["first_changed_winner_cycle"] = summary["first_changed_winner_cycle"]
    return result


def _local_gate(records: Sequence[Mapping[str, object]], *, activation_cycle: int) -> dict[str, object]:
    near_share = sum(bool(item["near_crossed"]) for item in records) / len(records)
    buffered_share = sum(bool(item["buffered_crossed"]) for item in records) / len(records)
    first_exact = all(int(item["first_changed_winner_cycle"]) == activation_cycle for item in records)
    preactivation = all(bool(item["preactivation_equal"]) for item in records)
    invariants = all(bool(item["all_invariants"]) for item in records)
    validated = near_share == 1.0 and buffered_share == 0.0 and first_exact and preactivation and invariants
    return {
        "near_crossing_share": near_share,
        "buffered_crossing_share": buffered_share,
        "first_divergence_exact": first_exact,
        "preactivation_equal": preactivation,
        "all_invariants": invariants,
        "validated": validated,
    }


def _cohort_quality(evaluation: Mapping[str, object], protocol: AuctionMarginConfig) -> bool:
    return bool(
        float(evaluation["mean_success_loss"]) <= protocol.maximum_success_loss
        and float(evaluation["mean_knowledge_loss"]) <= protocol.maximum_knowledge_loss
        and bool(evaluation["all_invariants"])
    )


def _instrumentation(
    connection: Connection[Any],
    *,
    protocol: AuctionMarginConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_base(protocol)
    records = [
        _run_seed(
            connection,
            protocol=protocol,
            base=base,
            config_hash=config_hash,
            code_sha=code_sha,
            experiment_number=129,
            cohort="instrumentation",
            seed=seed,
            environment=protocol.standard,
            instrumentation=True,
        )
        for seed in protocol.instrumentation_seeds
    ]
    gate = all(
        bool(item["preactivation_equal"])
        and bool(item["all_invariants"])
        and bool(item["near_no_probe_preserved"])
        and bool(item["buffered_no_probe_preserved"])
        and float(item["near_radius_error"]) <= _RADIUS_TOLERANCE
        and float(item["buffered_radius_error"]) <= _RADIUS_TOLERANCE
        for item in records
    )
    state["instrumentation_validated"] = gate
    return _record(
        number=129,
        focus="margin_controller_instrumentation",
        question="Can the frozen auction radius be placed exactly without changing pre-probe discrete state?",
        validated=gate,
        next_focus="local_causal_crossing",
        extras={"instrumentation_records": records, "instrumentation_validated": gate},
    )


def _discovery_crossing(
    connection: Connection[Any],
    *,
    protocol: AuctionMarginConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_base(protocol)
    records = [
        _run_seed(
            connection,
            protocol=protocol,
            base=base,
            config_hash=config_hash,
            code_sha=code_sha,
            experiment_number=130,
            cohort="discovery",
            seed=seed,
            environment=protocol.standard,
        )
        for seed in protocol.discovery_seeds
    ]
    local = _local_gate(records, activation_cycle=protocol.standard.activation_cycle)
    gate = bool(state["instrumentation_validated"]) and bool(local["validated"])
    state["local_crossing_validated"] = gate
    state["discovery_pairs"] = [dict(item["pair_summary"]) for item in records]
    return _record(
        number=130,
        focus="local_causal_crossing",
        question="Does the same epsilon=0.10 probe cross the near auction surface and remain subcritical when buffered?",
        validated=gate,
        next_focus="downstream_propagation_discovery",
        extras={"local_gate": local, "seed_records": records, "local_crossing_validated": gate},
    )


def _discovery_propagation(
    connection: Connection[Any],
    *,
    protocol: AuctionMarginConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    del connection, config_hash, code_sha
    raw = state.get("discovery_pairs")
    if not isinstance(raw, Sequence):
        raise ValueError("Experiment 131 requires Experiment 130 pair summaries")
    pairs = [dict(item) for item in raw if isinstance(item, Mapping)]
    evaluation = evaluate_cohort(pairs, config=protocol)
    gate = bool(state["local_crossing_validated"]) and bool(evaluation["organizational_propagation"])
    state["discovery_propagation_validated"] = gate
    state["discovery_classification"] = evaluation["classification"]
    state["discovery_evaluation"] = evaluation
    state.pop("discovery_pairs", None)
    return _record(
        number=131,
        focus="downstream_propagation_discovery",
        question="Does one controlled auction-surface crossing propagate to robust organizational divergence?",
        validated=gate,
        next_focus="activation_time_transfer",
        extras={
            "local_crossing_validated": bool(state["local_crossing_validated"]),
            "propagation_evaluation": evaluation,
            "discovery_propagation_validated": gate,
        },
    )


def _validation_cohort(
    connection: Connection[Any],
    *,
    protocol: AuctionMarginConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
    number: int,
    cohort: str,
    seeds: Sequence[int],
    environment: MarginEnvironment,
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object], bool]:
    base = load_canonical_base(protocol)
    records = [
        _run_seed(
            connection,
            protocol=protocol,
            base=base,
            config_hash=config_hash,
            code_sha=code_sha,
            experiment_number=number,
            cohort=cohort,
            seed=seed,
            environment=environment,
        )
        for seed in seeds
    ]
    local = _local_gate(records, activation_cycle=environment.activation_cycle)
    pairs = [dict(item["pair_summary"]) for item in records]
    evaluation = evaluate_cohort(pairs, config=protocol)
    expected = str(state.get("discovery_classification"))
    classification_agreement = str(evaluation["classification"]) == expected
    valid = bool(local["validated"]) and classification_agreement and _cohort_quality(evaluation, protocol)
    return records, local, evaluation, valid


def _timing_transfer(
    connection: Connection[Any],
    *,
    protocol: AuctionMarginConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    records, local, evaluation, gate = _validation_cohort(
        connection,
        protocol=protocol,
        config_hash=config_hash,
        code_sha=code_sha,
        state=state,
        number=132,
        cohort="timing_transfer",
        seeds=protocol.timing_transfer_seeds,
        environment=protocol.timing_transfer,
    )
    state["timing_transfer_validated"] = gate
    return _record(
        number=132,
        focus="activation_time_transfer",
        question="Does auction-margin crossing and its organizational classification transfer after a three-regime burn-in?",
        validated=gate,
        next_focus="independent_replication",
        extras={"local_gate": local, "propagation_evaluation": evaluation, "seed_records": records},
    )


def _replication(
    connection: Connection[Any],
    *,
    protocol: AuctionMarginConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    records, local, evaluation, gate = _validation_cohort(
        connection,
        protocol=protocol,
        config_hash=config_hash,
        code_sha=code_sha,
        state=state,
        number=133,
        cohort="replication",
        seeds=protocol.replication_seeds,
        environment=protocol.standard,
    )
    state["replication_validated"] = gate
    return _record(
        number=133,
        focus="independent_replication",
        question="Does the frozen auction-margin result replicate on independent seeds without refitting?",
        validated=gate,
        next_focus="unseen_environment_holdout",
        extras={"local_gate": local, "propagation_evaluation": evaluation, "seed_records": records},
    )


def _holdout(
    connection: Connection[Any],
    *,
    protocol: AuctionMarginConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    records, local, evaluation, holdout_gate = _validation_cohort(
        connection,
        protocol=protocol,
        config_hash=config_hash,
        code_sha=code_sha,
        state=state,
        number=134,
        cohort="holdout",
        seeds=protocol.holdout_seeds,
        environment=protocol.holdout,
    )
    robust = bool(
        state["instrumentation_validated"]
        and state["local_crossing_validated"]
        and state["discovery_propagation_validated"]
        and state["timing_transfer_validated"]
        and state["replication_validated"]
        and holdout_gate
    )
    state["holdout_validated"] = holdout_gate
    state["robust_auction_margin_control"] = robust
    return _record(
        number=134,
        focus="unseen_environment_holdout",
        question="Does the frozen auction-margin crossing/propagation classification survive an unseen regime period?",
        validated=holdout_gate,
        next_focus=None,
        extras={
            "local_gate": local,
            "propagation_evaluation": evaluation,
            "seed_records": records,
            "holdout_validated": holdout_gate,
            "robust_auction_margin_control": robust,
            "canonical_conclusion": (
                "robust_auction_margin_control"
                if robust
                else (
                    "auction_margin_controls_local_decision_sensitivity_but_not_robust_organizational_propagation"
                    if bool(state["local_crossing_validated"])
                    else "auction_margin_local_causal_control_not_validated"
                )
            ),
        },
    )


_STEPS = {
    129: _instrumentation,
    130: _discovery_crossing,
    131: _discovery_propagation,
    132: _timing_transfer,
    133: _replication,
    134: _holdout,
}


def run_auction_margin_step(
    connection: Connection[Any],
    *,
    protocol: AuctionMarginConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    checkpoint: Mapping[str, object] | None,
    output_dir: str | Path,
) -> dict[str, object]:
    if number not in _STEPS:
        raise ValueError(f"experiment must be between {_FIRST} and {_LAST}")
    if number == _FIRST:
        if checkpoint is not None:
            raise ValueError("Experiment 129 must start without a checkpoint")
        state = _initial_state(protocol=protocol, config_hash=config_hash, code_sha=code_sha)
    else:
        if checkpoint is None:
            raise ValueError("later auction-margin experiments require a checkpoint")
        _validate_state(
            checkpoint,
            number=number,
            protocol=protocol,
            config_hash=config_hash,
            code_sha=code_sha,
        )
        state = dict(checkpoint)

    record = _STEPS[number](
        connection,
        protocol=protocol,
        config_hash=config_hash,
        code_sha=code_sha,
        state=state,
    )
    state["last_completed"] = number
    state["next_experiment"] = number + 1 if number < _LAST else None

    from .auction_margin_notebook import write_step_artifacts

    write_step_artifacts(output_dir, record=record, checkpoint=state)
    return {"record": record, "checkpoint": state}


def load_checkpoint(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, Mapping):
        raise ValueError("checkpoint must be a JSON object")
    return dict(value)


__all__ = ["load_checkpoint", "run_auction_margin_step"]
