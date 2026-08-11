"""Checkpoint state machine for Chaos / Predictability-Decay Experiments 123–128."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from psycopg import Connection

from .chaos_predictability_campaign import (
    basin_occupancy,
    load_canonical_endogenous_config,
    local_screen,
    run_chaos_pair,
    scaling_evaluation,
    select_family,
)
from .chaos_predictability_config import ChaosPredictabilityConfig

_CHECKPOINT_VERSION = 1
_FIRST_EXPERIMENT = 123
_LAST_EXPERIMENT = 128


def _initial_checkpoint(
    *, protocol: ChaosPredictabilityConfig, config_hash: str, code_sha: str
) -> dict[str, object]:
    return {
        "version": _CHECKPOINT_VERSION,
        "campaign": protocol.name,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "last_completed": 122,
        "next_experiment": 123,
        "instrumentation_validated": False,
        "local_screen_validated": False,
        "scaling_validated": False,
        "discovery_classification": None,
        "selected_family": None,
        "replication_validated": False,
        "holdout_validated": False,
        "organizational_chaos_validated": False,
        "canonical_classification": None,
    }


def _validate_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    number: int,
    protocol: ChaosPredictabilityConfig,
    config_hash: str,
    code_sha: str,
) -> None:
    if int(checkpoint.get("version", -1)) != _CHECKPOINT_VERSION:
        raise ValueError("unsupported chaos checkpoint version")
    if checkpoint.get("campaign") != protocol.name:
        raise ValueError("checkpoint campaign mismatch")
    if checkpoint.get("config_hash") != config_hash:
        raise ValueError("checkpoint config hash mismatch")
    if checkpoint.get("code_sha") != code_sha:
        raise ValueError("checkpoint code SHA mismatch")
    if int(checkpoint.get("last_completed", -1)) != number - 1:
        raise ValueError("checkpoint does not immediately precede requested experiment")
    if int(checkpoint.get("next_experiment", -1)) != number:
        raise ValueError("checkpoint next experiment mismatch")


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
        "causal_family": "chaos_predictability_decay",
        "validated": validated,
        "next_experiment_focus": next_focus,
        **dict(extras),
    }


def _run_pairs(
    connection: Connection[Any],
    *,
    protocol: ChaosPredictabilityConfig,
    base,
    config_hash: str,
    code_sha: str,
    experiment_number: int,
    cohort: str,
    seeds: Sequence[int],
    environment_spec,
    families: Sequence[str],
    epsilons: Sequence[float],
    feedback_strengths: Sequence[float],
) -> list[dict[str, object]]:
    pairs: list[dict[str, object]] = []
    for family in families:
        for epsilon in epsilons:
            for feedback_strength in feedback_strengths:
                for seed in seeds:
                    pairs.append(
                        run_chaos_pair(
                            connection,
                            protocol=protocol,
                            base=base,
                            config_hash=config_hash,
                            code_sha=code_sha,
                            experiment_number=experiment_number,
                            cohort=cohort,
                            seed=seed,
                            environment_spec=environment_spec,
                            family=family,
                            epsilon=epsilon,
                            feedback_strength=feedback_strength,
                        )
                    )
    return pairs


def _instrumentation(
    connection: Connection[Any],
    *,
    protocol: ChaosPredictabilityConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_endogenous_config(protocol)
    pairs = _run_pairs(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=123,
        cohort="instrumentation_zero",
        seeds=protocol.instrumentation_seeds,
        environment_spec=protocol.standard,
        families=("bid_confidence", "trace_energy", "embedding_control"),
        epsilons=(0.0,),
        feedback_strengths=(0.0, protocol.feedback_strength),
    )
    timing_pairs = [
        run_chaos_pair(
            connection,
            protocol=protocol,
            base=base,
            config_hash=config_hash,
            code_sha=code_sha,
            experiment_number=123,
            cohort="instrumentation_timing",
            seed=seed,
            environment_spec=protocol.standard,
            family="feedback_delay",
            epsilon=0.0,
            feedback_strength=protocol.feedback_strength,
            feedback_delay=protocol.feedback_delay_cycles,
        )
        for seed in protocol.instrumentation_seeds
    ]
    zero_exact = all(
        float(pair["final_micro_distance"]) == 0.0
        and float(pair["final_meso_distance"]) == 0.0
        and float(pair["final_macro_distance"]) == 0.0
        and int(pair["first_changed_winner_cycle"]) == protocol.standard.cycles + 1
        for pair in pairs
    )
    candidate_equal = all(bool(pair["candidate_set_equal"]) for pair in pairs + timing_pairs)
    invariants = all(bool(pair["all_invariants"]) for pair in pairs + timing_pairs)
    bid_targets = all(
        int(pair["baseline_audit"]["bid_target_count"]) == 1  # type: ignore[index]
        and int(pair["perturbed_audit"]["bid_target_count"]) == 1  # type: ignore[index]
        for pair in pairs
    )
    trace_pairs = [pair for pair in pairs if pair["family"] == "trace_energy"]
    trace_targets = all(
        int(pair["baseline_audit"]["trace_target_count"]) == 1  # type: ignore[index]
        and int(pair["perturbed_audit"]["trace_target_count"]) == 1  # type: ignore[index]
        for pair in trace_pairs
    )
    embedding_pairs = [pair for pair in pairs if pair["family"] == "embedding_control"]
    embedding_inert = all(
        int(pair["baseline_audit"]["eligible_embedding_event_count"]) == 0  # type: ignore[index]
        and int(pair["perturbed_audit"]["eligible_embedding_event_count"]) == 0  # type: ignore[index]
        for pair in embedding_pairs
    )
    gate = zero_exact and candidate_equal and invariants and bid_targets and trace_targets and embedding_inert
    state["instrumentation_validated"] = gate
    return _record(
        number=123,
        focus="twin_instrumentation",
        question=(
            "Can zero-perturbation twins remain exactly identical while native bid/trace targets, "
            "candidate equality, feedback controls, and the embedding negative control are instrumented?"
        ),
        validated=gate,
        next_focus="local_divergence_screen",
        extras={
            "zero_twin_exact": zero_exact,
            "candidate_set_equal": candidate_equal,
            "hard_invariants": invariants,
            "bid_target_exact": bid_targets,
            "trace_target_exact": trace_targets,
            "embedding_negative_control_inert": embedding_inert,
            "timing_pairs": timing_pairs,
            "instrumentation_gate": gate,
        },
    )


def _local_divergence(
    connection: Connection[Any],
    *,
    protocol: ChaosPredictabilityConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_endogenous_config(protocol)
    pairs = _run_pairs(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=124,
        cohort="discovery_local",
        seeds=protocol.discovery_seeds,
        environment_spec=protocol.standard,
        families=("bid_confidence", "trace_energy"),
        epsilons=(protocol.epsilons[0],),
        feedback_strengths=(0.0, protocol.feedback_strength),
    )
    evaluation = local_screen(pairs, protocol=protocol, cycles=protocol.standard.cycles)
    passing = [family for family, result in evaluation.items() if bool(result["local_screen_gate"])]
    gate = bool(state["instrumentation_validated"]) and bool(passing)
    state["local_screen_validated"] = gate
    state["local_screen_families"] = passing
    state["discovery_pairs"] = pairs
    return _record(
        number=124,
        focus="local_divergence_screen",
        question=(
            "Can an epsilon=1e-6 native micro-perturbation produce delayed, bounded multiscale "
            "divergence under lambda=0.5 beyond the matched lambda=0 control?"
        ),
        validated=gate,
        next_focus="finite_size_scaling",
        extras={
            "instrumentation_validated": bool(state["instrumentation_validated"]),
            "local_screen": evaluation,
            "passing_families": passing,
            "local_screen_validated": gate,
        },
    )


def _scaling(
    connection: Connection[Any],
    *,
    protocol: ChaosPredictabilityConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    base = load_canonical_endogenous_config(protocol)
    new_pairs = _run_pairs(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=125,
        cohort="discovery_scaling",
        seeds=protocol.discovery_seeds,
        environment_spec=protocol.standard,
        families=("bid_confidence", "trace_energy"),
        epsilons=protocol.epsilons[1:],
        feedback_strengths=(protocol.feedback_strength,),
    )
    raw = state.get("discovery_pairs")
    if not isinstance(raw, Sequence):
        raise ValueError("Experiment 125 requires Experiment 124 pair summaries")
    prior = [dict(item) for item in raw if isinstance(item, Mapping)]
    primary_prior = [
        item for item in prior if float(item["feedback_strength"]) == protocol.feedback_strength
    ]
    all_primary = primary_prior + new_pairs
    evaluation = scaling_evaluation(
        all_primary,
        protocol=protocol,
        cycles=protocol.standard.cycles,
    )
    scaling_families = [
        family
        for family, result in evaluation.items()
        if bool(result["scales"]["micro"]["scaling_gate"])  # type: ignore[index]
        or bool(result["scales"]["meso"]["scaling_gate"])  # type: ignore[index]
    ]
    gate = bool(state["local_screen_validated"]) and bool(scaling_families)
    state["scaling_validated"] = gate
    state["scaling_families"] = scaling_families
    state["discovery_pairs"] = all_primary
    state["scaling_evaluation"] = evaluation
    return _record(
        number=125,
        focus="finite_size_scaling",
        question=(
            "Across the frozen five-epsilon grid, does predictability horizon shorten with log epsilon "
            "while divergence remains bounded rather than threshold-like or unstable?"
        ),
        validated=gate,
        next_focus="multiscale_basin_classification",
        extras={
            "scaling_evaluation": evaluation,
            "scaling_families": scaling_families,
            "scaling_validated": gate,
        },
    )


def _classification(
    connection: Connection[Any],
    *,
    protocol: ChaosPredictabilityConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    del connection, config_hash, code_sha
    raw = state.get("discovery_pairs")
    evaluation = state.get("scaling_evaluation")
    if not isinstance(raw, Sequence) or not isinstance(evaluation, Mapping):
        raise ValueError("Experiment 126 requires frozen 124–125 evidence")
    pairs = [dict(item) for item in raw if isinstance(item, Mapping)]
    typed_eval = {
        str(key): dict(value) for key, value in evaluation.items() if isinstance(value, Mapping)
    }
    selected = select_family(typed_eval, pairs, cycles=protocol.standard.cycles)
    classification = str(typed_eval[selected]["classification"])
    family_pairs = [pair for pair in pairs if pair["family"] == selected]
    state["selected_family"] = selected
    state["discovery_classification"] = classification
    state["discovery_scaling_spearman"] = {
        scale: float(typed_eval[selected]["scales"][scale]["spearman"])  # type: ignore[index]
        for scale in ("micro", "meso", "macro")
    }
    state.pop("discovery_pairs", None)
    state.pop("scaling_evaluation", None)
    organizational = classification == "organizationally_chaotic"
    return _record(
        number=126,
        focus="multiscale_basin_classification",
        question=(
            "Does the selected micro-perturbation produce stable order, basin-boundary sensitivity, "
            "instability, microscopic chaos with organizational predictability, or organizational chaos?"
        ),
        validated=organizational,
        next_focus="independent_replication",
        extras={
            "family_evaluations": typed_eval,
            "selected_family": selected,
            "discovery_classification": classification,
            "basin_occupancy": basin_occupancy(family_pairs),
            "organizational_chaos_discovery": organizational,
        },
    )


def _replication(
    connection: Connection[Any],
    *,
    protocol: ChaosPredictabilityConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    selected = str(state.get("selected_family"))
    if selected not in {"bid_confidence", "trace_energy"}:
        raise ValueError("Experiment 127 requires a frozen selected perturbation family")
    base = load_canonical_endogenous_config(protocol)
    pairs = _run_pairs(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=127,
        cohort="replication",
        seeds=protocol.replication_seeds,
        environment_spec=protocol.standard,
        families=(selected,),
        epsilons=protocol.epsilons,
        feedback_strengths=(protocol.feedback_strength,),
    )
    evaluation = scaling_evaluation(pairs, protocol=protocol, cycles=protocol.standard.cycles)[selected]
    classification = str(evaluation["classification"])
    discovery_classification = str(state.get("discovery_classification"))
    discovery_rho = state.get("discovery_scaling_spearman")
    assert isinstance(discovery_rho, Mapping)
    sign_agreement = all(
        (float(discovery_rho[scale]) <= 0)
        == (float(evaluation["scales"][scale]["spearman"]) <= 0)  # type: ignore[index]
        for scale in ("micro", "meso")
    )
    gate = classification == discovery_classification and sign_agreement
    state["replication_validated"] = gate
    state["replication_classification"] = classification
    return _record(
        number=127,
        focus="independent_replication",
        question="Does the frozen perturbation family reproduce the discovery dynamical classification?",
        validated=gate,
        next_focus="unseen_environment_holdout",
        extras={
            "selected_family": selected,
            "discovery_classification": discovery_classification,
            "replication_classification": classification,
            "forecast_horizon_sign_agreement": sign_agreement,
            "replication_evaluation": evaluation,
            "basin_occupancy": basin_occupancy(pairs),
            "replication_validated": gate,
        },
    )


def _holdout(
    connection: Connection[Any],
    *,
    protocol: ChaosPredictabilityConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    selected = str(state.get("selected_family"))
    if selected not in {"bid_confidence", "trace_energy"}:
        raise ValueError("Experiment 128 requires a frozen selected perturbation family")
    base = load_canonical_endogenous_config(protocol)
    pairs = _run_pairs(
        connection,
        protocol=protocol,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=128,
        cohort="holdout",
        seeds=protocol.holdout_seeds,
        environment_spec=protocol.holdout,
        families=(selected,),
        epsilons=protocol.epsilons,
        feedback_strengths=(protocol.feedback_strength,),
    )
    evaluation = scaling_evaluation(pairs, protocol=protocol, cycles=protocol.holdout.cycles)[selected]
    classification = str(evaluation["classification"])
    discovery_classification = str(state.get("discovery_classification"))
    holdout_gate = classification == discovery_classification
    full_org_chaos = (
        bool(state["instrumentation_validated"])
        and bool(state["local_screen_validated"])
        and bool(state["scaling_validated"])
        and discovery_classification == "organizationally_chaotic"
        and bool(state["replication_validated"])
        and holdout_gate
        and classification == "organizationally_chaotic"
    )
    if full_org_chaos:
        canonical = "organizationally_chaotic"
    elif (
        classification == "micro_chaotic_organizationally_predictable"
        and discovery_classification == classification
    ):
        canonical = "microscopic_chaos_with_organizational_predictability"
    elif (
        classification == "basin_boundary_sensitive"
        or discovery_classification == "basin_boundary_sensitive"
    ):
        canonical = "basin_boundary_sensitivity_or_hidden_state_contingency"
    elif classification == "unstable" or discovery_classification == "unstable":
        canonical = "instability_not_chaos"
    else:
        canonical = "no_replicated_chaos_or_predictability_decay"
    state["holdout_validated"] = holdout_gate
    state["organizational_chaos_validated"] = full_org_chaos
    state["canonical_classification"] = canonical
    return _record(
        number=128,
        focus="unseen_environment_holdout",
        question=(
            "Does the frozen perturbation family preserve its finite-size predictability classification "
            "under an unseen regime period without refitting?"
        ),
        validated=full_org_chaos,
        next_focus=None,
        extras={
            "selected_family": selected,
            "discovery_classification": discovery_classification,
            "replication_classification": state.get("replication_classification"),
            "holdout_classification": classification,
            "holdout_classification_agreement": holdout_gate,
            "holdout_evaluation": evaluation,
            "basin_occupancy": basin_occupancy(pairs),
            "organizational_chaos_validated": full_org_chaos,
            "canonical_classification": canonical,
        },
    )


_STEPS = {
    123: _instrumentation,
    124: _local_divergence,
    125: _scaling,
    126: _classification,
    127: _replication,
    128: _holdout,
}


def run_chaos_predictability_step(
    connection: Connection[Any],
    *,
    protocol: ChaosPredictabilityConfig,
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
            raise ValueError("Experiment 123 must start without a checkpoint")
        state = _initial_checkpoint(protocol=protocol, config_hash=config_hash, code_sha=code_sha)
    else:
        if checkpoint is None:
            raise ValueError("later chaos experiments require a checkpoint")
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

    from .chaos_predictability_notebook import write_step_artifacts

    write_step_artifacts(output_dir, record=record, checkpoint=state)
    return {"record": record, "checkpoint": state}


def load_checkpoint(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, Mapping):
        raise ValueError("checkpoint must be a JSON object")
    return dict(value)


__all__ = ["load_checkpoint", "run_chaos_predictability_step"]
