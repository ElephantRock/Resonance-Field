"""Deterministic pre-seal power adequacy model for Experiments 142–145.

This module does not replace the confirmatory bootstrap/randomization estimator.
It is a prospective planning model for the frozen independent-case success
rule. It separates:

1. detection power against zero under the conservative first Holm threshold;
2. probability of also clearing the frozen observed-effect magnitude gate.

The empirical two-point residual shapes are derived from the five completed
instrumentation cases whose frozen primary scoring is not known to be
mechanically invalid: Pilot 001 and Calibrations 002, 004, 006, and 008.
Only centered residual shape/variance is used; the observed instrumentation
mean effect is never used as the planning alternative.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist, mean, stdev

FAMILYWISE_ALPHA = 0.05
CONTRAST_COUNT = 4
PLANNED_CONFIRMATORY_CASES = 512
MINIMUM_EVALUABLE_CASES = 496

R_MINUS_G_MINIMUM_EFFECT = 0.03
R_MINUS_P_MINIMUM_EFFECT = 0.08

R_MINUS_G_INSTRUMENTATION_DIFFERENCES = (0.0, 0.0, 0.0, 0.40, 0.0)
R_MINUS_P_INSTRUMENTATION_DIFFERENCES = (0.0, 0.20, 0.0, 0.20, 0.0)

R_MINUS_G_EFFECT_GRID = (0.0, 0.03, 0.04, 0.05, 0.06)
R_MINUS_P_EFFECT_GRID = (0.0, 0.08, 0.09, 0.10, 0.12)


@dataclass(frozen=True, slots=True)
class TwoPointResidualModel:
    """Centered two-point planning residual distribution."""

    low: float
    high: float
    high_probability: float
    planning_sd: float
    source_case_count: int

    def validate(self) -> None:
        if not self.low < 0.0 < self.high:
            raise ValueError("residual support must straddle zero")
        if not 0.0 < self.high_probability < 1.0:
            raise ValueError("high_probability must be in (0, 1)")
        expected = (1.0 - self.high_probability) * self.low + self.high_probability * self.high
        if abs(expected) > 1e-12:
            raise ValueError("planning residual distribution must be centered")
        if self.planning_sd <= 0.0:
            raise ValueError("planning_sd must be positive")
        if self.source_case_count < 2:
            raise ValueError("source_case_count must be at least two")


@dataclass(frozen=True, slots=True)
class PowerPoint:
    true_effect: float
    detection_power: float
    hard_gate_pass_probability: float


@dataclass(frozen=True, slots=True)
class ContrastPowerReport:
    contrast: str
    case_count: int
    minimum_effect_gate: float
    planning_sd: float
    empirical_grid: tuple[PowerPoint, ...]
    normal_detection_power_at_gate_sd_020: float


@dataclass(frozen=True, slots=True)
class ConfirmatoryPowerReport:
    planned_case_count: int
    minimum_evaluable_case_count: int
    familywise_alpha: float
    contrast_count: int
    conservative_two_sided_per_test_alpha: float
    r_minus_g: ContrastPowerReport
    r_minus_p: ContrastPowerReport


def conservative_per_test_alpha(
    *, familywise_alpha: float = FAMILYWISE_ALPHA, contrast_count: int = CONTRAST_COUNT
) -> float:
    if not 0.0 < familywise_alpha < 1.0:
        raise ValueError("familywise_alpha must be in (0, 1)")
    if contrast_count < 1:
        raise ValueError("contrast_count must be positive")
    return familywise_alpha / contrast_count


def conservative_two_sided_z(
    *, familywise_alpha: float = FAMILYWISE_ALPHA, contrast_count: int = CONTRAST_COUNT
) -> float:
    per_test = conservative_per_test_alpha(
        familywise_alpha=familywise_alpha,
        contrast_count=contrast_count,
    )
    return NormalDist().inv_cdf(1.0 - per_test / 2.0)


def two_point_residual_model(values: tuple[float, ...]) -> TwoPointResidualModel:
    """Build a centered empirical residual model while preserving sample SD.

    Treating the observed values as an empirical distribution would shrink its
    population variance by `(m-1)/m` relative to the sample variance. Residuals
    are therefore multiplied by `sqrt(m/(m-1))`, so the planning distribution
    reproduces the instrumentation sample SD rather than using the smaller
    plug-in population SD.
    """

    if len(values) < 2:
        raise ValueError("at least two instrumentation case differences are required")
    observed_mean = mean(values)
    residuals = tuple(value - observed_mean for value in values)
    unique = sorted(set(residuals))
    if len(unique) != 2:
        raise ValueError("frozen planning residuals must have exactly two support points")
    scale = math.sqrt(len(values) / (len(values) - 1))
    low, high = (value * scale for value in unique)
    high_probability = residuals.count(unique[1]) / len(residuals)
    model = TwoPointResidualModel(
        low=low,
        high=high,
        high_probability=high_probability,
        planning_sd=stdev(values),
        source_case_count=len(values),
    )
    model.validate()
    return model


def _binomial_probabilities(n: int, probability: float) -> tuple[float, ...]:
    if n < 1:
        raise ValueError("n must be positive")
    if not 0.0 < probability < 1.0:
        raise ValueError("probability must be in (0, 1)")
    logs = []
    for k in range(n + 1):
        log_probability = (
            math.lgamma(n + 1)
            - math.lgamma(k + 1)
            - math.lgamma(n - k + 1)
            + k * math.log(probability)
            + (n - k) * math.log1p(-probability)
        )
        logs.append(log_probability)
    offset = max(logs)
    unscaled = [math.exp(value - offset) for value in logs]
    total = sum(unscaled)
    return tuple(value / total for value in unscaled)


def _sample_mean_and_sd(
    *, n: int, high_count: int, model: TwoPointResidualModel, true_effect: float
) -> tuple[float, float]:
    low_count = n - high_count
    residual_mean = (
        low_count * model.low + high_count * model.high
    ) / n
    estimate = true_effect + residual_mean
    if n == 1:
        return estimate, 0.0
    residual_ss = (
        low_count * (model.low - residual_mean) ** 2
        + high_count * (model.high - residual_mean) ** 2
    )
    return estimate, math.sqrt(residual_ss / (n - 1))


def enumerate_power_point(
    *,
    n: int,
    true_effect: float,
    minimum_effect_gate: float,
    model: TwoPointResidualModel,
    familywise_alpha: float = FAMILYWISE_ALPHA,
    contrast_count: int = CONTRAST_COUNT,
) -> PowerPoint:
    """Enumerate the frozen empirical residual distribution exactly.

    Statistical positivity is conservatively approximated by requiring the
    paired estimate minus the first-Holm-step normal critical value times its
    sample standard error to exceed zero. The actual confirmatory test remains
    the frozen paired randomization plus paired percentile bootstrap.
    """

    if true_effect < 0.0:
        raise ValueError("planning true_effect must be non-negative")
    if minimum_effect_gate < 0.0:
        raise ValueError("minimum_effect_gate must be non-negative")
    model.validate()
    critical = conservative_two_sided_z(
        familywise_alpha=familywise_alpha,
        contrast_count=contrast_count,
    )
    probabilities = _binomial_probabilities(n, model.high_probability)
    detection = 0.0
    hard_gate = 0.0
    for high_count, probability in enumerate(probabilities):
        estimate, sample_sd = _sample_mean_and_sd(
            n=n,
            high_count=high_count,
            model=model,
            true_effect=true_effect,
        )
        standard_error = sample_sd / math.sqrt(n)
        statistically_positive = estimate - critical * standard_error > 0.0
        if statistically_positive:
            detection += probability
            if estimate >= minimum_effect_gate:
                hard_gate += probability
    return PowerPoint(
        true_effect=true_effect,
        detection_power=min(1.0, detection),
        hard_gate_pass_probability=min(1.0, hard_gate),
    )


def normal_detection_power(
    *,
    n: int,
    true_effect: float,
    paired_sd: float,
    familywise_alpha: float = FAMILYWISE_ALPHA,
    contrast_count: int = CONTRAST_COUNT,
) -> float:
    """Two-sided normal detection-power screen at the conservative Holm bound."""

    if n < 2:
        raise ValueError("n must be at least two")
    if paired_sd <= 0.0:
        raise ValueError("paired_sd must be positive")
    critical = conservative_two_sided_z(
        familywise_alpha=familywise_alpha,
        contrast_count=contrast_count,
    )
    noncentrality = true_effect * math.sqrt(n) / paired_sd
    normal = NormalDist()
    power = normal.cdf(noncentrality - critical) + normal.cdf(-noncentrality - critical)
    return min(1.0, power)


def _contrast_report(
    *,
    contrast: str,
    case_count: int,
    minimum_effect_gate: float,
    instrumentation_differences: tuple[float, ...],
    effect_grid: tuple[float, ...],
) -> ContrastPowerReport:
    model = two_point_residual_model(instrumentation_differences)
    return ContrastPowerReport(
        contrast=contrast,
        case_count=case_count,
        minimum_effect_gate=minimum_effect_gate,
        planning_sd=model.planning_sd,
        empirical_grid=tuple(
            enumerate_power_point(
                n=case_count,
                true_effect=true_effect,
                minimum_effect_gate=minimum_effect_gate,
                model=model,
            )
            for true_effect in effect_grid
        ),
        normal_detection_power_at_gate_sd_020=normal_detection_power(
            n=case_count,
            true_effect=minimum_effect_gate,
            paired_sd=0.20,
        ),
    )


def build_frozen_power_report(
    *, case_count: int = PLANNED_CONFIRMATORY_CASES
) -> ConfirmatoryPowerReport:
    if case_count < MINIMUM_EVALUABLE_CASES:
        raise ValueError(
            f"confirmatory power report requires at least {MINIMUM_EVALUABLE_CASES} evaluable cases"
        )
    return ConfirmatoryPowerReport(
        planned_case_count=PLANNED_CONFIRMATORY_CASES,
        minimum_evaluable_case_count=MINIMUM_EVALUABLE_CASES,
        familywise_alpha=FAMILYWISE_ALPHA,
        contrast_count=CONTRAST_COUNT,
        conservative_two_sided_per_test_alpha=conservative_per_test_alpha(),
        r_minus_g=_contrast_report(
            contrast="resonance_field-provenance_graph",
            case_count=case_count,
            minimum_effect_gate=R_MINUS_G_MINIMUM_EFFECT,
            instrumentation_differences=R_MINUS_G_INSTRUMENTATION_DIFFERENCES,
            effect_grid=R_MINUS_G_EFFECT_GRID,
        ),
        r_minus_p=_contrast_report(
            contrast="resonance_field-pile",
            case_count=case_count,
            minimum_effect_gate=R_MINUS_P_MINIMUM_EFFECT,
            instrumentation_differences=R_MINUS_P_INSTRUMENTATION_DIFFERENCES,
            effect_grid=R_MINUS_P_EFFECT_GRID,
        ),
    )


def validate_frozen_power_adequacy() -> ConfirmatoryPowerReport:
    """Fail the pre-seal gate if the frozen 512/496 design loses 80% detection."""

    full = build_frozen_power_report(case_count=PLANNED_CONFIRMATORY_CASES)
    minimum = build_frozen_power_report(case_count=MINIMUM_EVALUABLE_CASES)

    if full.r_minus_g.normal_detection_power_at_gate_sd_020 < 0.80:
        raise ValueError("512-case R-G detection power is below 0.80 at SD 0.20")
    if minimum.r_minus_g.normal_detection_power_at_gate_sd_020 < 0.80:
        raise ValueError("minimum evaluable-case R-G detection power is below 0.80 at SD 0.20")
    if full.r_minus_p.normal_detection_power_at_gate_sd_020 < 0.80:
        raise ValueError("512-case R-P detection power is below 0.80 at SD 0.20")
    return full


__all__ = [
    "CONTRAST_COUNT",
    "FAMILYWISE_ALPHA",
    "MINIMUM_EVALUABLE_CASES",
    "PLANNED_CONFIRMATORY_CASES",
    "ConfirmatoryPowerReport",
    "ContrastPowerReport",
    "PowerPoint",
    "TwoPointResidualModel",
    "build_frozen_power_report",
    "conservative_per_test_alpha",
    "conservative_two_sided_z",
    "enumerate_power_point",
    "normal_detection_power",
    "two_point_residual_model",
    "validate_frozen_power_adequacy",
]
