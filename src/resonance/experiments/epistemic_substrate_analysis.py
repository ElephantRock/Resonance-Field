"""Frozen confirmatory statistics for Epistemic Substrate Experiments 138–141."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, replace
from statistics import mean

from .epistemic_substrate_campaign import ArmMetrics
from .epistemic_substrate_config import EpistemicSubstrateConfig


@dataclass(frozen=True, slots=True)
class ContrastResult:
    endpoint: str
    treatment: str
    control: str
    treatment_mean: float
    control_mean: float
    effect: float
    ci_lower: float
    ci_upper: float
    p_value: float
    adjusted_p_value: float = 1.0

    def to_dict(self) -> dict[str, str | float]:
        return {
            "endpoint": self.endpoint,
            "treatment": self.treatment,
            "control": self.control,
            "treatment_mean": self.treatment_mean,
            "control_mean": self.control_mean,
            "effect": self.effect,
            "ci_lower": self.ci_lower,
            "ci_upper": self.ci_upper,
            "p_value": self.p_value,
            "adjusted_p_value": self.adjusted_p_value,
        }


@dataclass(frozen=True, slots=True)
class ConfirmatoryAnalysis:
    contrasts: tuple[ContrastResult, ...]
    campaign_success: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "campaign_success": self.campaign_success,
            "contrasts": [result.to_dict() for result in self.contrasts],
        }


def _derived_seed(base: int, *parts: str) -> int:
    payload = "|".join((str(base), *parts)).encode()
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big")


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def paired_bootstrap_ci(
    differences: tuple[float, ...],
    *,
    resamples: int,
    confidence: float,
    seed: int,
) -> tuple[float, float]:
    if not differences:
        raise ValueError("paired bootstrap requires at least one difference")
    rng = random.Random(seed)
    count = len(differences)
    estimates = [
        mean(differences[rng.randrange(count)] for _ in range(count))
        for _ in range(resamples)
    ]
    tail = (1.0 - confidence) / 2.0
    return _percentile(estimates, tail), _percentile(estimates, 1.0 - tail)


def paired_sign_flip_p_value(
    differences: tuple[float, ...],
    *,
    resamples: int,
    seed: int,
) -> float:
    if not differences:
        raise ValueError("paired randomization requires at least one difference")
    observed = abs(mean(differences))
    if observed == 0.0:
        return 1.0
    rng = random.Random(seed)
    count = 0
    n = len(differences)
    threshold = observed - 1e-15
    for _ in range(resamples):
        permuted = sum(
            difference if rng.getrandbits(1) else -difference
            for difference in differences
        ) / n
        if abs(permuted) >= threshold:
            count += 1
    return (count + 1) / (resamples + 1)


def holm_adjust(p_values: tuple[float, ...]) -> tuple[float, ...]:
    if not p_values:
        return ()
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [1.0] * len(p_values)
    running = 0.0
    total = len(p_values)
    for rank, index in enumerate(order):
        candidate = min(1.0, (total - rank) * p_values[index])
        running = max(running, candidate)
        adjusted[index] = running
    return tuple(adjusted)


def _metric_by_arm(metrics: tuple[ArmMetrics, ...]) -> dict[str, ArmMetrics]:
    return {metric.arm: metric for metric in metrics}


def _endpoint_value(metric: ArmMetrics, endpoint: str) -> float:
    value = getattr(metric, endpoint)
    if not isinstance(value, float):
        raise TypeError(f"primary endpoint {endpoint} is not numeric")
    return value


def analyze_confirmatory(
    paired_worlds: dict[int, tuple[ArmMetrics, ...]],
    config: EpistemicSubstrateConfig,
) -> ConfirmatoryAnalysis:
    if tuple(sorted(paired_worlds)) != tuple(sorted(config.confirmatory_seeds)):
        raise ValueError("confirmatory analysis requires exactly the frozen confirmatory cohort")

    raw: list[ContrastResult] = []
    seeds = tuple(sorted(paired_worlds))
    for endpoint in config.primary_endpoints:
        for treatment, control in config.confirmatory_contrasts:
            treatment_values: list[float] = []
            control_values: list[float] = []
            for seed in seeds:
                by_arm = _metric_by_arm(paired_worlds[seed])
                treatment_values.append(_endpoint_value(by_arm[treatment], endpoint))
                control_values.append(_endpoint_value(by_arm[control], endpoint))
            differences = tuple(
                treatment_value - control_value
                for treatment_value, control_value in zip(
                    treatment_values,
                    control_values,
                    strict=True,
                )
            )
            label = f"{endpoint}:{treatment}:{control}"
            ci_lower, ci_upper = paired_bootstrap_ci(
                differences,
                resamples=config.bootstrap_resamples,
                confidence=config.confidence_interval,
                seed=_derived_seed(config.randomization_seed, label, "bootstrap"),
            )
            p_value = paired_sign_flip_p_value(
                differences,
                resamples=config.randomization_resamples,
                seed=_derived_seed(config.randomization_seed, label, "randomization"),
            )
            raw.append(
                ContrastResult(
                    endpoint=endpoint,
                    treatment=treatment,
                    control=control,
                    treatment_mean=mean(treatment_values),
                    control_mean=mean(control_values),
                    effect=mean(differences),
                    ci_lower=ci_lower,
                    ci_upper=ci_upper,
                    p_value=p_value,
                )
            )

    adjusted = holm_adjust(tuple(result.p_value for result in raw))
    results = tuple(
        replace(result, adjusted_p_value=adjusted[index])
        for index, result in enumerate(raw)
    )
    total_effects = {
        result.endpoint: result
        for result in results
        if result.treatment == "resonance_field" and result.control == "pile"
    }
    minimums = {
        "transfer_accuracy": config.minimum_total_effect_transfer_accuracy,
        "collective_emergence_ratio": config.minimum_total_effect_collective_emergence_ratio,
    }
    campaign_success = all(
        total_effects[endpoint].effect >= minimums[endpoint]
        and total_effects[endpoint].adjusted_p_value < config.alpha
        and total_effects[endpoint].ci_lower > 0.0
        for endpoint in config.primary_endpoints
    )
    return ConfirmatoryAnalysis(results, campaign_success)


__all__ = [
    "ConfirmatoryAnalysis",
    "ContrastResult",
    "analyze_confirmatory",
    "holm_adjust",
    "paired_bootstrap_ci",
    "paired_sign_flip_p_value",
]
