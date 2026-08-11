"""Checkpoint state machine for Delayed-Onset Phase Observability Experiments 111–116."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from psycopg import Connection

from .delayed_phase_campaign import (
    cohort_quality,
    evaluate_discovery_features,
    load_canonical_endogenous_config,
    run_cohort,
    sign_heterogeneity,
    validate_classifier,
)
from .delayed_phase_config import DelayedPhaseConfig, PhaseEnvironment

_CHECKPOINT_VERSION = 1
_FIRST_EXPERIMENT = 111
_LAST_EXPERIMENT = 116


def _initial_checkpoint(
    *, protocol: DelayedPhaseConfig, config_hash: str, code_sha: str
) -> dict[str, object]:
    return {
        "version": _CHECKPOINT_VERSION,
        "campaign": protocol.name,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "last_completed": 110,
        "next_experiment": 111,
        "equivalence_validated": False,
        "heterogeneity_validated": False,
        "phase_condition_selected": False,
        "classifier": None,
        "replication_validated": False,
        "timing_transfer_validated": False,
        "validated": None,
        "prospective_phase_condition": False,
    }


def _validate_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    number: int,
    protocol: DelayedPhaseConfig,
    config_hash: str,
    code_sha: str,
) -> None:
    if int(checkpoint.get("version", -1)) != _CHECKPOINT_VERSION:
        raise ValueError("unsupported delayed-phase checkpoint version")
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
        "causal_family": "delayed_onset_phase_observability",
        "validated": validated,
        "next_experiment_focus": next_focus,
        **dict(extras),
    }


def _equivalence(
    connection: Connection[Any],
    *,
    protocol: DelayedPhaseConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_endogenous_config(protocol)
    instrumentation = PhaseEnvironment(
        shift_period=protocol.standard.shift_period,
        burn_in_cycles=protocol.standard.burn_in_cycles,
        cycles=protocol.standard.burn_in_cycles,
        candidate_count=protocol.standard.candidate_count,
    )
    records = run_cohort(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=111,
        cohort="equivalence",
        seeds=protocol.equivalence_seeds,
        environment_spec=instrumentation,
        analyze_post=False,
    )
    exact = all(
        bool(record["preactivation_exact"])
        and bool(record["state_features_exact"])
        and bool(record["all_cell_invariants"])
        for record in records
    )
    state["equivalence_validated"] = exact
    return _record(
        number=111,
        focus="delayed_onset_equivalence",
        question=(
            "Can control and delayed-feedback populations remain exactly identical through two complete "
            "regimes while the five preregistered state observables are measured?"
        ),
        validated=exact,
        next_focus="prospective_sign_heterogeneity",
        extras={
            "equivalence_validated": exact,
            "activation_cycle": protocol.standard.burn_in_cycles,
            "seed_count": len(records),
            "records": records,
        },
    )


def _discovery(
    connection: Connection[Any],
    *,
    protocol: DelayedPhaseConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_endogenous_config(protocol)
    records = run_cohort(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=112,
        cohort="discovery",
        seeds=protocol.discovery_seeds,
        environment_spec=protocol.standard,
    )
    heterogeneity = sign_heterogeneity(records, protocol)
    quality = cohort_quality(records, protocol)
    validated = (
        bool(state["equivalence_validated"])
        and bool(heterogeneity["heterogeneity_gate"])
        and bool(quality["quality_gate"])
    )
    state["heterogeneity_validated"] = validated
    state["discovery_records"] = records
    return _record(
        number=112,
        focus="prospective_sign_heterogeneity",
        question=(
            "After two identical exogenous regimes, does the same frozen λ=0.5 feedback mechanism "
            "still produce seed-level lock-in and plasticity signs?"
        ),
        validated=validated,
        next_focus="phase_condition_freeze",
        extras={
            **heterogeneity,
            **quality,
            "equivalence_validated": bool(state["equivalence_validated"]),
            "records": records,
        },
    )


def _phase_freeze(
    connection: Connection[Any],
    *,
    protocol: DelayedPhaseConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    del connection, config_hash, code_sha
    raw = state.get("discovery_records")
    if not isinstance(raw, Sequence):
        raise ValueError("Experiment 113 requires discovery records from Experiment 112")
    records = [dict(record) for record in raw if isinstance(record, Mapping)]
    if len(records) != len(protocol.discovery_seeds):
        raise ValueError("discovery record count mismatch")
    evaluations, raw_classifier = evaluate_discovery_features(records, protocol)
    classifier = raw_classifier if bool(state["heterogeneity_validated"]) else None
    selected = classifier is not None
    validated = bool(state["heterogeneity_validated"]) and selected
    state["phase_condition_selected"] = selected
    state["classifier"] = classifier
    state.pop("discovery_records", None)
    return _record(
        number=113,
        focus="phase_condition_freeze",
        question=(
            "Does one preregistered pre-treatment scalar state variable prospectively classify the "
            "sign of delayed endogenous feedback on the discovery cohort?"
        ),
        validated=validated,
        next_focus="independent_prospective_replication",
        extras={
            "heterogeneity_validated": bool(state["heterogeneity_validated"]),
            "phase_condition_selected": selected,
            "classifier": classifier,
            "evaluations": evaluations,
            "conclusion": (
                "candidate prospective phase condition frozen"
                if selected
                else "no prospective scalar phase condition"
            ),
        },
    )


def _replication(
    connection: Connection[Any],
    *,
    protocol: DelayedPhaseConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_endogenous_config(protocol)
    records = run_cohort(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=114,
        cohort="replication",
        seeds=protocol.replication_seeds,
        environment_spec=protocol.standard,
    )
    classifier = state.get("classifier")
    classifier_map = classifier if isinstance(classifier, Mapping) else None
    validation = validate_classifier(records, classifier_map, protocol)
    validated = bool(state["phase_condition_selected"]) and bool(validation["validation_gate"])
    state["replication_validated"] = validated
    return _record(
        number=114,
        focus="independent_prospective_replication",
        question="Does the frozen discovery threshold classify feedback sign on independent seeds without refitting?",
        validated=validated,
        next_focus="activation_time_transfer",
        extras={
            "phase_condition_selected": bool(state["phase_condition_selected"]),
            **validation,
            "records": records,
        },
    )


def _timing_transfer(
    connection: Connection[Any],
    *,
    protocol: DelayedPhaseConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_endogenous_config(protocol)
    records = run_cohort(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=115,
        cohort="timing_transfer",
        seeds=protocol.timing_transfer_seeds,
        environment_spec=protocol.timing_transfer,
    )
    classifier = state.get("classifier")
    classifier_map = classifier if isinstance(classifier, Mapping) else None
    validation = validate_classifier(records, classifier_map, protocol)
    validated = bool(state["replication_validated"]) and bool(validation["validation_gate"])
    state["timing_transfer_validated"] = validated
    return _record(
        number=115,
        focus="activation_time_transfer",
        question=(
            "Does the same frozen state threshold transfer unchanged when feedback activation is delayed "
            "from two regimes to three?"
        ),
        validated=validated,
        next_focus="unseen_environment_holdout",
        extras={
            "replication_validated": bool(state["replication_validated"]),
            **validation,
            "records": records,
        },
    )


def _holdout(
    connection: Connection[Any],
    *,
    protocol: DelayedPhaseConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_endogenous_config(protocol)
    records = run_cohort(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=116,
        cohort="holdout",
        seeds=protocol.holdout_seeds,
        environment_spec=protocol.holdout,
    )
    classifier = state.get("classifier")
    classifier_map = classifier if isinstance(classifier, Mapping) else None
    validation = validate_classifier(records, classifier_map, protocol)
    holdout_gate = bool(validation["validation_gate"])
    validated = (
        bool(state["equivalence_validated"])
        and bool(state["heterogeneity_validated"])
        and bool(state["phase_condition_selected"])
        and bool(state["replication_validated"])
        and bool(state["timing_transfer_validated"])
        and holdout_gate
    )
    state["validated"] = validated
    state["prospective_phase_condition"] = validated
    return _record(
        number=116,
        focus="unseen_environment_holdout",
        question=(
            "Does the same frozen phase classifier survive a different regime period on wholly unseen "
            "seeds without refitting?"
        ),
        validated=validated,
        next_focus=None,
        extras={
            "equivalence_validated": bool(state["equivalence_validated"]),
            "heterogeneity_validated": bool(state["heterogeneity_validated"]),
            "phase_condition_selected": bool(state["phase_condition_selected"]),
            "replication_validated": bool(state["replication_validated"]),
            "timing_transfer_validated": bool(state["timing_transfer_validated"]),
            "holdout_validated": holdout_gate,
            "prospective_phase_condition": validated,
            "classifier": classifier_map,
            **validation,
            "records": records,
        },
    )


_STEPS = {
    111: _equivalence,
    112: _discovery,
    113: _phase_freeze,
    114: _replication,
    115: _timing_transfer,
    116: _holdout,
}


def run_delayed_phase_step(
    connection: Connection[Any],
    *,
    protocol: DelayedPhaseConfig,
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
            raise ValueError("Experiment 111 must start without a checkpoint")
        state = _initial_checkpoint(protocol=protocol, config_hash=config_hash, code_sha=code_sha)
    else:
        if checkpoint is None:
            raise ValueError("later delayed-phase experiments require a checkpoint")
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

    from .delayed_phase_notebook import write_step_artifacts

    write_step_artifacts(output_dir, record=record, checkpoint=state)
    return {"record": record, "checkpoint": state}


def load_checkpoint(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("checkpoint must be a JSON object")
    return value


__all__ = ["load_checkpoint", "run_delayed_phase_step"]
