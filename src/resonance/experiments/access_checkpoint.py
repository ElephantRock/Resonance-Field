"""Checkpoint state machine for Capability-Preserving Access Experiments 075–080."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from psycopg import Connection

from . import lifecycle_campaign as lc
from .access_config import AccessControlConfig, access_environment, load_access_config
from .integration_campaign import ReputationPolicy


_CHECKPOINT_VERSION = 1
_FIRST_EXPERIMENT = 75
_LAST_EXPERIMENT = 80


@dataclass(frozen=True, slots=True)
class AccessMechanism:
    exposure_penalty: float = 0.0
    exposure_window: int = 12
    challenger_inflation: float = 0.0
    diversified_retrieval: bool = False
    diversified_lineages: int = 3

    def __post_init__(self) -> None:
        if self.exposure_penalty < 0:
            raise ValueError("exposure_penalty must be non-negative")
        if self.exposure_window <= 0:
            raise ValueError("exposure_window must be positive")
        if not 0 <= self.challenger_inflation <= 0.5:
            raise ValueError("challenger_inflation must be in [0, 0.5]")
        if self.diversified_lineages <= 0:
            raise ValueError("diversified_lineages must be positive")

    @property
    def neutral(self) -> bool:
        return (
            self.exposure_penalty == 0
            and self.challenger_inflation == 0
            and not self.diversified_retrieval
        )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> AccessMechanism:
        return cls(
            exposure_penalty=float(value.get("exposure_penalty", 0.0)),
            exposure_window=int(value.get("exposure_window", 12)),
            challenger_inflation=float(value.get("challenger_inflation", 0.0)),
            diversified_retrieval=bool(value.get("diversified_retrieval", False)),
            diversified_lineages=int(value.get("diversified_lineages", 3)),
        )


def _initial_checkpoint(
    *,
    config: AccessControlConfig,
    config_hash: str,
    code_sha: str,
) -> dict[str, object]:
    return {
        "version": _CHECKPOINT_VERSION,
        "campaign": config.integration.name,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "last_completed": 74,
        "next_experiment": 75,
        "selected_mechanism": None,
        "screen_validated": False,
        "decomposition_validated": False,
        "response_validated": False,
        "rapid_shift_validated": False,
        "replication_validated": False,
        "validated": None,
    }


def _validate_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    number: int,
    config: AccessControlConfig,
    config_hash: str,
    code_sha: str,
) -> None:
    if int(checkpoint.get("version", -1)) != _CHECKPOINT_VERSION:
        raise ValueError("unsupported access-control checkpoint version")
    if checkpoint.get("campaign") != config.integration.name:
        raise ValueError("checkpoint campaign does not match configuration")
    if checkpoint.get("config_hash") != config_hash:
        raise ValueError("checkpoint config hash does not match configuration")
    if checkpoint.get("code_sha") != code_sha:
        raise ValueError("checkpoint code SHA does not match current workflow")
    if int(checkpoint.get("last_completed", -1)) != number - 1:
        raise ValueError("checkpoint does not immediately precede requested experiment")
    if int(checkpoint.get("next_experiment", -1)) != number:
        raise ValueError("checkpoint next_experiment does not match requested experiment")


def _arm(
    config: AccessControlConfig,
    *,
    label: str,
    mechanism: AccessMechanism,
    env=None,
) -> lc.LifecycleArmSpec:
    effective_env = env if env is not None else access_environment(
        config,
        challenger_inflation=mechanism.challenger_inflation,
    )
    if mechanism.exposure_penalty > 0:
        policy = ReputationPolicy(
            mode="reputation",
            weight=0.0,
            exposure_penalty=mechanism.exposure_penalty,
            exposure_window=mechanism.exposure_window,
        )
    else:
        policy = ReputationPolicy()
    lifecycle = lc.LifecycleSpec(
        diversified_retrieval=mechanism.diversified_retrieval,
    )
    return lc.LifecycleArmSpec(
        label=label,
        policy=policy,
        environment=effective_env,
        lifecycle=lifecycle,
        public_trace_confidence_weight=config.public_trace_confidence_weight,
        retrieval_top_k=config.retrieval_top_k,
        diversified_lineages=mechanism.diversified_lineages,
        knowledge_signal_threshold=config.knowledge_signal_threshold,
    )


def _run_mechanisms(
    connection: Connection[Any],
    *,
    config: AccessControlConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    mechanisms: Sequence[tuple[str, AccessMechanism]],
    seeds: Sequence[int] | None = None,
    env_overrides: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    arms: list[lc.LifecycleArmSpec] = []
    for label, mechanism in mechanisms:
        base_env = access_environment(
            config,
            challenger_inflation=mechanism.challenger_inflation,
            **dict(env_overrides or {}),
        )
        arms.append(_arm(config, label=label, mechanism=mechanism, env=base_env))
    results = lc.run_lifecycle_experiment(
        connection,
        config=config.integration,
        config_hash=config_hash,
        experiment_number=number,
        arms=arms,
        seeds=seeds if seeds is not None else config.integration.seeds,
        code_sha=code_sha,
    )
    by_label = {label: mechanism for label, mechanism in mechanisms}
    for item in results:
        item["mechanism"] = by_label[str(item["label"])].as_dict()
    return results


def _effects(
    arm: Mapping[str, object],
    control: Mapping[str, object],
) -> dict[str, float]:
    return lc.lifecycle_effects(arm, control)


def _hard_gate(
    arm: Mapping[str, object],
    control: Mapping[str, object],
    *,
    config: AccessControlConfig,
) -> tuple[bool, dict[str, float]]:
    effects = _effects(arm, control)
    feasible = lc.lifecycle_feasible(
        arm,
        control,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )
    hard = (
        feasible
        and effects["success_effect"] >= -config.integration.success_tolerance
        and effects["logical_incumbent_reduction"] >= config.minimum_logical_improvement
        and effects["knowledge_effect"] >= -config.knowledge_tolerance
    )
    return hard, effects


def _evaluate(
    arms: Sequence[dict[str, object]],
    *,
    config: AccessControlConfig,
    control_label: str = "immortal_control",
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object], bool]:
    control = next(arm for arm in arms if arm["label"] == control_label)
    evaluated: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    for arm in arms:
        item = dict(arm)
        metrics = item["metrics"]
        assert isinstance(metrics, Mapping)
        item["utility"] = lc.lifecycle_utility(metrics)  # type: ignore[arg-type]
        item["feasible"] = lc.lifecycle_feasible(
            arm,
            control,
            config=config.integration,
            knowledge_tolerance=config.knowledge_tolerance,
        )
        if arm["label"] == control_label:
            item["hard_gate"] = True
            item["effects"] = {
                "success_effect": 0.0,
                "logical_incumbent_reduction": 0.0,
                "identity_incumbent_reduction": 0.0,
                "hhi_reduction": 0.0,
                "knowledge_effect": 0.0,
                "cultural_hhi_reduction": 0.0,
            }
        else:
            hard, effects = _hard_gate(arm, control, config=config)
            item["hard_gate"] = hard
            item["effects"] = effects
            candidates.append(item)
        evaluated.append(item)

    passing = [item for item in candidates if bool(item["hard_gate"])]
    if passing:
        selected = max(passing, key=lambda item: (float(item["utility"]), str(item["label"])))
        return evaluated, selected, control, True

    feasible_candidates = [item for item in candidates if bool(item["feasible"])]
    if feasible_candidates:
        selected = max(
            feasible_candidates,
            key=lambda item: (
                float(item["effects"]["logical_incumbent_reduction"]),  # type: ignore[index]
                float(item["utility"]),
                str(item["label"]),
            ),
        )
        return evaluated, selected, control, False

    selected = next(item for item in evaluated if item["label"] == control_label)
    return evaluated, selected, control, False


def _record(
    *,
    number: int,
    focus: str,
    question: str,
    arms: Sequence[Mapping[str, object]],
    selected: Mapping[str, object],
    next_focus: str | None,
    validated: bool,
    extras: Mapping[str, object],
) -> dict[str, object]:
    return {
        "number": number,
        "focus": focus,
        "question": question,
        "motivating_failure": "control_without_capability_destruction",
        "observed_failure": None if validated else focus,
        "arms": list(arms),
        "selected_label": selected["label"],
        "next_experiment_focus": next_focus,
        "validated": validated,
        **dict(extras),
    }


def _screen(
    connection: Connection[Any],
    *,
    config: AccessControlConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    p = config.screen_exposure_penalty
    w = config.screen_exposure_window
    c = config.screen_challenger_inflation
    d = config.diversified_lineages
    mechanisms = [
        ("immortal_control", AccessMechanism(exposure_window=w, diversified_lineages=d)),
        ("exposure_limit", AccessMechanism(exposure_penalty=p, exposure_window=w, diversified_lineages=d)),
        (
            "challenger_opportunity",
            AccessMechanism(
                exposure_window=w,
                challenger_inflation=c,
                diversified_lineages=d,
            ),
        ),
        (
            "lineage_diverse_retrieval",
            AccessMechanism(
                exposure_window=w,
                diversified_retrieval=True,
                diversified_lineages=d,
            ),
        ),
        (
            "combined_access_opportunity",
            AccessMechanism(
                exposure_penalty=p,
                exposure_window=w,
                challenger_inflation=c,
                diversified_retrieval=True,
                diversified_lineages=d,
            ),
        ),
    ]
    arms = _run_mechanisms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=75,
        mechanisms=mechanisms,
    )
    evaluated, selected, control, validated = _evaluate(arms, config=config)
    raw = selected.get("mechanism")
    assert isinstance(raw, Mapping)
    state["selected_mechanism"] = dict(raw)
    state["screen_validated"] = validated
    effects = _effects(selected, control) if selected["label"] != "immortal_control" else {
        "success_effect": 0.0,
        "logical_incumbent_reduction": 0.0,
        "identity_incumbent_reduction": 0.0,
        "hhi_reduction": 0.0,
        "knowledge_effect": 0.0,
        "cultural_hhi_reduction": 0.0,
    }
    return _record(
        number=75,
        focus="mechanism_screen",
        question=(
            "Can any practice-preserving access mechanism reduce logical capture without sacrificing "
            "quality or public knowledge?"
        ),
        arms=evaluated,
        selected=selected,
        next_focus="mechanism_decomposition",
        validated=validated,
        extras={**effects, "screen_validated": validated, "selected_mechanism": dict(raw)},
    )


def _decomposition_specs(
    mechanism: AccessMechanism,
) -> list[tuple[str, AccessMechanism]]:
    specs: list[tuple[str, AccessMechanism]] = [("candidate_full", mechanism)]
    if mechanism.exposure_penalty > 0:
        specs.append(("without_exposure_limit", replace(mechanism, exposure_penalty=0.0)))
    if mechanism.challenger_inflation > 0:
        specs.append(("without_challenger_opportunity", replace(mechanism, challenger_inflation=0.0)))
    if mechanism.diversified_retrieval:
        specs.append(("without_diverse_retrieval", replace(mechanism, diversified_retrieval=False)))
    unique: dict[tuple[object, ...], tuple[str, AccessMechanism]] = {}
    for label, spec in specs:
        key = (
            spec.exposure_penalty,
            spec.exposure_window,
            spec.challenger_inflation,
            spec.diversified_retrieval,
            spec.diversified_lineages,
        )
        unique.setdefault(key, (label, spec))
    return list(unique.values())


def _decompose(
    connection: Connection[Any],
    *,
    config: AccessControlConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_mechanism")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected mechanism")
    mechanism = AccessMechanism.from_mapping(raw)
    control = AccessMechanism(
        exposure_window=mechanism.exposure_window,
        diversified_lineages=mechanism.diversified_lineages,
    )
    mechanisms = [("immortal_control", control), *_decomposition_specs(mechanism)]
    arms = _run_mechanisms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=76,
        mechanisms=mechanisms,
    )
    evaluated, selected, baseline, validated = _evaluate(arms, config=config)
    raw_selected = selected.get("mechanism")
    assert isinstance(raw_selected, Mapping)
    state["selected_mechanism"] = dict(raw_selected)
    state["decomposition_validated"] = validated
    effects = _effects(selected, baseline) if selected["label"] != "immortal_control" else {
        "success_effect": 0.0,
        "logical_incumbent_reduction": 0.0,
        "identity_incumbent_reduction": 0.0,
        "hhi_reduction": 0.0,
        "knowledge_effect": 0.0,
        "cultural_hhi_reduction": 0.0,
    }
    return _record(
        number=76,
        focus="mechanism_decomposition",
        question=(
            "Which components of the screened mechanism are actually necessary for "
            "practice-preserving plasticity?"
        ),
        arms=evaluated,
        selected=selected,
        next_focus="bounded_response",
        validated=validated,
        extras={
            **effects,
            "screen_validated": bool(state["screen_validated"]),
            "decomposition_validated": validated,
            "selected_mechanism": dict(raw_selected),
        },
    )


def _scaled(mechanism: AccessMechanism, scale: float) -> AccessMechanism:
    lineages = mechanism.diversified_lineages
    if mechanism.diversified_retrieval:
        lineages = max(2, int(round(lineages * scale)))
    return replace(
        mechanism,
        exposure_penalty=mechanism.exposure_penalty * scale,
        challenger_inflation=min(0.5, mechanism.challenger_inflation * scale),
        diversified_lineages=lineages,
    )


def _response(
    connection: Connection[Any],
    *,
    config: AccessControlConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_mechanism")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected mechanism")
    mechanism = AccessMechanism.from_mapping(raw)
    control = AccessMechanism(
        exposure_window=mechanism.exposure_window,
        diversified_lineages=config.diversified_lineages,
    )
    mechanisms: list[tuple[str, AccessMechanism]] = [("immortal_control", control)]
    seen: set[tuple[object, ...]] = set()
    for scale in config.response_scales:
        spec = _scaled(mechanism, scale)
        key = (
            spec.exposure_penalty,
            spec.exposure_window,
            spec.challenger_inflation,
            spec.diversified_retrieval,
            spec.diversified_lineages,
        )
        if key in seen:
            continue
        seen.add(key)
        mechanisms.append((f"response_{scale:g}x", spec))
    arms = _run_mechanisms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=77,
        mechanisms=mechanisms,
    )
    evaluated, selected, baseline, _ = _evaluate(arms, config=config)
    passing = [
        arm for arm in evaluated
        if arm["label"] != "immortal_control" and bool(arm.get("hard_gate"))
    ]
    response_validated = len(passing) >= 2
    if passing:
        selected = max(passing, key=lambda item: (float(item["utility"]), str(item["label"])))
    raw_selected = selected.get("mechanism")
    assert isinstance(raw_selected, Mapping)
    state["selected_mechanism"] = dict(raw_selected)
    state["response_validated"] = response_validated
    effects = _effects(selected, baseline) if selected["label"] != "immortal_control" else {
        "success_effect": 0.0,
        "logical_incumbent_reduction": 0.0,
        "identity_incumbent_reduction": 0.0,
        "hhi_reduction": 0.0,
        "knowledge_effect": 0.0,
        "cultural_hhi_reduction": 0.0,
    }
    return _record(
        number=77,
        focus="bounded_response",
        question=(
            "Does the mechanism survive bounded weaker and stronger settings rather than only one "
            "tuned point?"
        ),
        arms=evaluated,
        selected=selected,
        next_focus="rapid_regime_shift",
        validated=response_validated,
        extras={
            **effects,
            "decomposition_validated": bool(state["decomposition_validated"]),
            "response_validated": response_validated,
            "passing_settings": len(passing),
            "selected_mechanism": dict(raw_selected),
        },
    )


def _frozen_pair(
    connection: Connection[Any],
    *,
    config: AccessControlConfig,
    config_hash: str,
    code_sha: str,
    number: int,
    mechanism: AccessMechanism,
    seeds: Sequence[int],
    env_overrides: Mapping[str, object] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object], bool]:
    control = AccessMechanism(
        exposure_window=mechanism.exposure_window,
        diversified_lineages=config.diversified_lineages,
    )
    arms = _run_mechanisms(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=number,
        seeds=seeds,
        env_overrides=env_overrides,
        mechanisms=[
            ("immortal_control", control),
            ("candidate_access", mechanism),
        ],
    )
    return _evaluate(arms, config=config)


def _rapid_shift(
    connection: Connection[Any],
    *,
    config: AccessControlConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_mechanism")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected mechanism")
    mechanism = AccessMechanism.from_mapping(raw)
    evaluated, selected, baseline, hard = _frozen_pair(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=78,
        mechanism=mechanism,
        seeds=config.integration.seeds,
        env_overrides={"shift_period": config.rapid_shift_period},
    )
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_access")
    effects = _effects(candidate, baseline)
    validated = bool(state["response_validated"]) and hard and bool(candidate["hard_gate"])
    state["rapid_shift_validated"] = validated
    return _record(
        number=78,
        focus="rapid_regime_shift",
        question=(
            "Does the frozen access mechanism preserve quality and logical plasticity when mappings "
            "change faster?"
        ),
        arms=evaluated,
        selected=candidate if validated else selected,
        next_focus="independent_replication",
        validated=validated,
        extras={**effects, "rapid_shift_validated": validated, "selected_mechanism": mechanism.as_dict()},
    )


def _replication(
    connection: Connection[Any],
    *,
    config: AccessControlConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_mechanism")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected mechanism")
    mechanism = AccessMechanism.from_mapping(raw)
    evaluated, selected, baseline, hard = _frozen_pair(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=79,
        mechanism=mechanism,
        seeds=config.replication_seeds,
    )
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_access")
    effects = _effects(candidate, baseline)
    validated = bool(state["rapid_shift_validated"]) and hard and bool(candidate["hard_gate"])
    state["replication_validated"] = validated
    return _record(
        number=79,
        focus="independent_replication",
        question=(
            "Does the frozen practice-preserving access mechanism reproduce on independent seeds "
            "without retuning?"
        ),
        arms=evaluated,
        selected=candidate if validated else selected,
        next_focus="unseen_holdout",
        validated=validated,
        extras={**effects, "replication_validated": validated, "selected_mechanism": mechanism.as_dict()},
    )


def _holdout(
    connection: Connection[Any],
    *,
    config: AccessControlConfig,
    config_hash: str,
    code_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    raw = state.get("selected_mechanism")
    if not isinstance(raw, Mapping):
        raise ValueError("missing selected mechanism")
    mechanism = AccessMechanism.from_mapping(raw)
    holdout = _scaled(mechanism, config.holdout_strength_scale)
    holdout = replace(holdout, exposure_window=config.holdout_exposure_window)
    evaluated, selected, baseline, hard = _frozen_pair(
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        number=80,
        mechanism=holdout,
        seeds=config.integration.holdout_seeds,
        env_overrides={
            "cycles": config.integration.holdout_cycles,
            "shift_period": config.integration.holdout_shift_period,
            "candidate_count": config.integration.holdout_candidate_count,
        },
    )
    candidate = next(arm for arm in evaluated if arm["label"] == "candidate_access")
    effects = _effects(candidate, baseline)
    validated = (
        bool(state["decomposition_validated"])
        and bool(state["response_validated"])
        and bool(state["rapid_shift_validated"])
        and bool(state["replication_validated"])
        and hard
        and bool(candidate["hard_gate"])
    )
    state["validated"] = validated
    return _record(
        number=80,
        focus="unseen_holdout",
        question=(
            "Does the access mechanism generalize to unseen seeds, shift timing, and a bounded "
            "unseen strength perturbation?"
        ),
        arms=evaluated,
        selected=candidate if hard else selected,
        next_focus=None,
        validated=validated,
        extras={
            **effects,
            "screen_validated": bool(state["screen_validated"]),
            "decomposition_validated": bool(state["decomposition_validated"]),
            "response_validated": bool(state["response_validated"]),
            "rapid_shift_validated": bool(state["rapid_shift_validated"]),
            "replication_validated": bool(state["replication_validated"]),
            "holdout_mechanism": holdout.as_dict(),
        },
    )


_STEPS = {
    75: _screen,
    76: _decompose,
    77: _response,
    78: _rapid_shift,
    79: _replication,
    80: _holdout,
}


def run_access_step(
    connection: Connection[Any],
    *,
    config: AccessControlConfig,
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
            raise ValueError("Experiment 075 must start without a checkpoint")
        state = _initial_checkpoint(config=config, config_hash=config_hash, code_sha=code_sha)
    else:
        if checkpoint is None:
            raise ValueError("later access-control experiments require a checkpoint")
        _validate_checkpoint(
            checkpoint,
            number=number,
            config=config,
            config_hash=config_hash,
            code_sha=code_sha,
        )
        state = dict(checkpoint)

    record = _STEPS[number](
        connection,
        config=config,
        config_hash=config_hash,
        code_sha=code_sha,
        state=state,
    )
    state["last_completed"] = number
    state["next_experiment"] = number + 1 if number < _LAST_EXPERIMENT else None

    from .access_notebook import write_step_artifacts

    write_step_artifacts(output_dir, record=record, checkpoint=state)
    return {"record": record, "checkpoint": state}


def load_checkpoint(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("checkpoint must be a JSON object")
    return value


__all__ = [
    "AccessMechanism",
    "load_access_config",
    "load_checkpoint",
    "run_access_step",
]
