"""Checkpoint state machine for Trajectory/Hysteresis Experiments 117–122."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from psycopg import Connection

from .trajectory_hysteresis_campaign import (
    evaluate_hysteresis,
    evaluate_instrumentation,
    evaluate_trajectory_predictors,
    load_canonical_endogenous_config,
    run_history_cohort,
    validate_trajectory_predictor,
)
from .trajectory_hysteresis_config import TrajectoryHysteresisConfig

_CHECKPOINT_VERSION = 1
_FIRST_EXPERIMENT = 117
_LAST_EXPERIMENT = 122


def _initial_checkpoint(
    *, protocol: TrajectoryHysteresisConfig, config_hash: str, code_sha: str
) -> dict[str, object]:
    return {
        "version": _CHECKPOINT_VERSION,
        "campaign": protocol.name,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "last_completed": 116,
        "next_experiment": 117,
        "instrumentation_validated": False,
        "discovery_hysteresis_validated": False,
        "discovery_annealing_validated": False,
        "trajectory_predictor_selected": False,
        "trajectory_predictor": None,
        "replication_validated": False,
        "replication_annealing_validated": False,
        "timing_validated": False,
        "timing_annealing_validated": False,
        "holdout_validated": False,
        "hysteresis_validated": False,
        "annealing_validated": False,
    }


def _validate_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    number: int,
    protocol: TrajectoryHysteresisConfig,
    config_hash: str,
    code_sha: str,
) -> None:
    if int(checkpoint.get("version", -1)) != _CHECKPOINT_VERSION:
        raise ValueError("unsupported trajectory-hysteresis checkpoint version")
    if checkpoint.get("campaign") != protocol.name:
        raise ValueError("checkpoint campaign does not match configuration")
    if checkpoint.get("config_hash") != config_hash:
        raise ValueError("checkpoint config hash does not match configuration")
    if checkpoint.get("code_sha") != code_sha:
        raise ValueError("checkpoint code SHA does not match current workflow")
    if int(checkpoint.get("last_completed", -1)) != number - 1:
        raise ValueError("checkpoint does not immediately precede requested experiment")
    if int(checkpoint.get("next_experiment", -1)) != number:
        raise ValueError("checkpoint next_experiment does not match requested experiment")


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
        "causal_family": "trajectory_hysteresis",
        "validated": validated,
        "next_experiment_focus": next_focus,
        **dict(extras),
    }


def _instrumentation(
    connection: Connection[Any],
    *,
    protocol: TrajectoryHysteresisConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_endogenous_config(protocol)
    instrumentation = replace(protocol.standard, cycles=protocol.standard.activation_cycle)
    records = run_history_cohort(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=117,
        cohort="instrumentation",
        seeds=protocol.instrumentation_seeds,
        environment_spec=instrumentation,
        analyze_post=False,
    )
    evaluation = evaluate_instrumentation(records, protocol)
    validated = bool(evaluation["instrumentation_gate"])
    state["instrumentation_validated"] = validated
    return _record(
        number=117,
        focus="history_instrumentation_and_endpoint_matching",
        question=(
            "Can four distinct preregistered histories be constructed with exact within-history paired "
            "prefixes, reproducible trajectory observables, and tolerance-matched endpoints before any "
            "post-activation effect is analyzed?"
        ),
        validated=validated,
        next_focus="boundary_hysteresis_discovery",
        extras={**evaluation, "records": records},
    )


def _discovery(
    connection: Connection[Any],
    *,
    protocol: TrajectoryHysteresisConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_endogenous_config(protocol)
    records = run_history_cohort(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=118,
        cohort="discovery",
        seeds=protocol.discovery_seeds,
        environment_spec=protocol.standard,
    )
    evaluation = evaluate_hysteresis(records, protocol)
    hysteresis = bool(state["instrumentation_validated"]) and bool(evaluation["hysteresis_gate"])
    annealing = bool(state["instrumentation_validated"]) and bool(evaluation["annealing_gate"])
    state["discovery_hysteresis_validated"] = hysteresis
    state["discovery_annealing_validated"] = annealing
    state["discovery_records"] = records
    return _record(
        number=118,
        focus="boundary_hysteresis_discovery",
        question=(
            "Among tolerance-matched endpoints, do structured histories change the sign/magnitude of the "
            "same λ=0.5 feedback response, and does annealed history make that sign more consistent?"
        ),
        validated=hysteresis,
        next_focus="trajectory_observable_freeze",
        extras={
            **evaluation,
            "instrumentation_validated": bool(state["instrumentation_validated"]),
            "discovery_hysteresis_validated": hysteresis,
            "discovery_annealing_validated": annealing,
            "records": records,
        },
    )


def _trajectory_freeze(
    connection: Connection[Any],
    *,
    protocol: TrajectoryHysteresisConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    del connection, config_hash, code_sha
    raw = state.get("discovery_records")
    if not isinstance(raw, Sequence):
        raise ValueError("Experiment 119 requires Experiment 118 discovery records")
    records = [dict(record) for record in raw if isinstance(record, Mapping)]
    evaluations, classifier = evaluate_trajectory_predictors(records, protocol)
    selected = classifier is not None
    state["trajectory_predictor_selected"] = selected
    state["trajectory_predictor"] = classifier
    state.pop("discovery_records", None)
    return _record(
        number=119,
        focus="trajectory_observable_freeze",
        question=(
            "Does one preregistered pre-activation trajectory scalar prospectively classify feedback sign "
            "on the fixed smooth-reference discovery records?"
        ),
        validated=selected,
        next_focus="independent_hysteresis_replication",
        extras={
            "discovery_hysteresis_validated": bool(state["discovery_hysteresis_validated"]),
            "trajectory_predictor_selected": selected,
            "trajectory_predictor": classifier,
            "evaluations": evaluations,
            "conclusion": (
                "trajectory predictor frozen" if selected else "no prospective trajectory scalar predictor"
            ),
        },
    )


def _replication(
    connection: Connection[Any],
    *,
    protocol: TrajectoryHysteresisConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_endogenous_config(protocol)
    records = run_history_cohort(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=120,
        cohort="replication",
        seeds=protocol.replication_seeds,
        environment_spec=protocol.standard,
    )
    evaluation = evaluate_hysteresis(records, protocol)
    classifier = state.get("trajectory_predictor")
    classifier_map = classifier if isinstance(classifier, Mapping) else None
    prediction = validate_trajectory_predictor(records, classifier_map, protocol)
    predictor_ok = (
        not bool(state["trajectory_predictor_selected"])
        or bool(prediction["predictor_validation_gate"])
    )
    hysteresis = (
        bool(state["discovery_hysteresis_validated"])
        and bool(evaluation["hysteresis_gate"])
        and predictor_ok
    )
    annealing = (
        bool(state["discovery_annealing_validated"])
        and bool(evaluation["annealing_gate"])
    )
    state["replication_validated"] = hysteresis
    state["replication_annealing_validated"] = annealing
    return _record(
        number=120,
        focus="independent_hysteresis_replication",
        question="Does the frozen matched-history hysteresis result replicate on independent seeds?",
        validated=hysteresis,
        next_focus="mid_regime_timing_control",
        extras={
            **evaluation,
            **prediction,
            "replication_validated": hysteresis,
            "replication_annealing_validated": annealing,
            "records": records,
        },
    )


def _timing_control(
    connection: Connection[Any],
    *,
    protocol: TrajectoryHysteresisConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_endogenous_config(protocol)
    records = run_history_cohort(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=121,
        cohort="timing_control",
        seeds=protocol.timing_seeds,
        environment_spec=protocol.timing_control,
    )
    evaluation = evaluate_hysteresis(records, protocol)
    classifier = state.get("trajectory_predictor")
    classifier_map = classifier if isinstance(classifier, Mapping) else None
    prediction = validate_trajectory_predictor(records, classifier_map, protocol)
    predictor_ok = (
        not bool(state["trajectory_predictor_selected"])
        or bool(prediction["predictor_validation_gate"])
    )
    hysteresis = (
        bool(state["replication_validated"])
        and bool(evaluation["hysteresis_gate"])
        and predictor_ok
    )
    annealing = (
        bool(state["replication_annealing_validated"])
        and bool(evaluation["annealing_gate"])
    )
    state["timing_validated"] = hysteresis
    state["timing_annealing_validated"] = annealing
    return _record(
        number=121,
        focus="mid_regime_timing_control",
        question=(
            "Does matched-endpoint history dependence survive when the same feedback is activated mid-regime "
            "rather than at a regime boundary?"
        ),
        validated=hysteresis,
        next_focus="unseen_environment_holdout",
        extras={
            **evaluation,
            **prediction,
            "timing_validated": hysteresis,
            "timing_annealing_validated": annealing,
            "records": records,
        },
    )


def _holdout(
    connection: Connection[Any],
    *,
    protocol: TrajectoryHysteresisConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_endogenous_config(protocol)
    records = run_history_cohort(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=122,
        cohort="holdout",
        seeds=protocol.holdout_seeds,
        environment_spec=protocol.holdout,
    )
    evaluation = evaluate_hysteresis(records, protocol)
    classifier = state.get("trajectory_predictor")
    classifier_map = classifier if isinstance(classifier, Mapping) else None
    prediction = validate_trajectory_predictor(records, classifier_map, protocol)
    predictor_ok = (
        not bool(state["trajectory_predictor_selected"])
        or bool(prediction["predictor_validation_gate"])
    )
    holdout_gate = bool(evaluation["hysteresis_gate"]) and predictor_ok
    hysteresis = (
        bool(state["instrumentation_validated"])
        and bool(state["discovery_hysteresis_validated"])
        and bool(state["replication_validated"])
        and bool(state["timing_validated"])
        and holdout_gate
    )
    annealing = (
        bool(state["discovery_annealing_validated"])
        and bool(state["replication_annealing_validated"])
        and bool(state["timing_annealing_validated"])
        and bool(evaluation["annealing_gate"])
    )
    state["holdout_validated"] = holdout_gate
    state["hysteresis_validated"] = hysteresis
    state["annealing_validated"] = annealing
    return _record(
        number=122,
        focus="unseen_environment_holdout",
        question=(
            "Does the frozen matched-history hysteresis design survive an unseen regime period, and does "
            "the preregistered annealing consistency prediction survive the full chain?"
        ),
        validated=hysteresis,
        next_focus=None,
        extras={
            **evaluation,
            **prediction,
            "instrumentation_validated": bool(state["instrumentation_validated"]),
            "discovery_hysteresis_validated": bool(state["discovery_hysteresis_validated"]),
            "replication_validated": bool(state["replication_validated"]),
            "timing_validated": bool(state["timing_validated"]),
            "holdout_validated": holdout_gate,
            "hysteresis_validated": hysteresis,
            "annealing_validated": annealing,
            "trajectory_predictor": classifier_map,
            "records": records,
        },
    )


_STEPS = {
    117: _instrumentation,
    118: _discovery,
    119: _trajectory_freeze,
    120: _replication,
    121: _timing_control,
    122: _holdout,
}


def run_trajectory_hysteresis_step(
    connection: Connection[Any],
    *,
    protocol: TrajectoryHysteresisConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    checkpoint: Mapping[str, object] | None,
    output_dir: str | Path,
) -> dict[str, object]:
    if number not in _STEPS:
        raise ValueError(f"experiment must be between {_FIRST_EXPERIMENT} and {_LAST_EXPERIMENT}")
    if number == _FIRST_EXPERIMENT:
        if checkpoint is not None:
            raise ValueError("Experiment 117 must start without a checkpoint")
        state = _initial_checkpoint(protocol=protocol, config_hash=config_hash, code_sha=code_sha)
    else:
        if checkpoint is None:
            raise ValueError("later trajectory-hysteresis experiments require a checkpoint")
        _validate_checkpoint(
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
    state["next_experiment"] = number + 1 if number < _LAST_EXPERIMENT else None

    from .trajectory_hysteresis_notebook import write_step_artifacts

    write_step_artifacts(output_dir, record=record, checkpoint=state)
    return {"record": record, "checkpoint": state}


def load_checkpoint(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("checkpoint must be a JSON object")
    return value


__all__ = ["load_checkpoint", "run_trajectory_hysteresis_step"]
