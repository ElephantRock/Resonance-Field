"""Case-level paired confirmatory analysis for Experiments 142–145.

Evaluator draws are nested repeated measurements. The independent unit is the
research case, so each arm is first reduced to one mean accuracy per case.
Bootstrap resampling and paired randomization then operate on cases, never on
individual evaluator draws.

The campaign-level PASS rule preserves the hard-effect-gate semantics used by
the parent Experiments 138–141 campaign: each priority contrast must clear its
frozen observed-effect threshold, its Holm-adjusted zero-effect test, and a
positive paired-bootstrap lower confidence bound.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

ARMS = ("pile", "shared_memory", "provenance_graph", "resonance_field")
PLANNED_CONTRASTS = (
    ("shared_memory", "pile"),
    ("provenance_graph", "shared_memory"),
    ("resonance_field", "provenance_graph"),
    ("resonance_field", "pile"),
)
FROZEN_MINIMUM_EFFECTS: Mapping[tuple[str, str], float] = MappingProxyType(
    {
        ("resonance_field", "provenance_graph"): 0.03,
        ("resonance_field", "pile"): 0.08,
    }
)


@dataclass(frozen=True, slots=True)
class CaseAccuracy:
    """One independent case with nested binary evaluator draws for every arm."""

    case_id: str
    arm_draws: Mapping[str, tuple[float, ...]]

    def validate(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must be non-empty")
        if set(self.arm_draws) != set(ARMS):
            raise ValueError(f"case {self.case_id} must contain exactly the four campaign arms")
        draw_counts = {len(self.arm_draws[arm]) for arm in ARMS}
        if len(draw_counts) != 1 or not draw_counts or next(iter(draw_counts)) < 1:
            raise ValueError(f"case {self.case_id} must have equal nonzero draw counts across arms")
        for arm in ARMS:
            for value in self.arm_draws[arm]:
                if value not in (0.0, 1.0):
                    raise ValueError(
                        f"case {self.case_id} arm {arm} contains non-binary primary score {value}"
                    )

    def arm_mean(self, arm: str) -> float:
        self.validate()
        values = self.arm_draws[arm]
        return sum(values) / len(values)


@dataclass(frozen=True, slots=True)
class ContrastResult:
    treatment: str
    control: str
    case_count: int
    effect: float
    bootstrap_ci_low: float
    bootstrap_ci_high: float
    randomization_p_raw: float
    randomization_p_holm: float
    holm_reject: bool
    statistically_positive: bool
    minimum_effect: float | None
    meets_minimum_effect: bool | None
    passes_success_rule: bool | None


@dataclass(frozen=True, slots=True)
class ConfirmatoryAnalysisResult:
    case_count: int
    evaluator_draws_per_case_arm: int
    familywise_alpha: float
    bootstrap_resamples: int
    randomization_resamples: int
    seed: int
    campaign_success: bool | None
    contrasts: tuple[ContrastResult, ...]


def _seed_for(seed: int, *parts: str) -> int:
    material = ":".join((str(seed), *parts)).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("cannot take a quantile of an empty sequence")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0, 1]")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = probability * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def _bootstrap_ci(
    differences: Sequence[float],
    *,
    resamples: int,
    confidence: float,
    seed: int,
) -> tuple[float, float]:
    if resamples < 1:
        raise ValueError("bootstrap resamples must be positive")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    n = len(differences)
    rng = random.Random(seed)
    means = [sum(rng.choices(differences, k=n)) / n for _ in range(resamples)]
    means.sort()
    tail = (1.0 - confidence) / 2.0
    return _quantile(means, tail), _quantile(means, 1.0 - tail)


def _paired_randomization_p(
    differences: Sequence[float],
    *,
    resamples: int,
    seed: int,
) -> float:
    """Two-sided paired arm-label randomization p-value.

    Under the sharp no-treatment null, swapping the two arm labels within any
    case changes only the sign of that case's paired difference. Monte Carlo
    sign flips therefore randomize at the independent case level.
    """

    if resamples < 1:
        raise ValueError("randomization resamples must be positive")
    observed = abs(sum(differences) / len(differences))
    rng = random.Random(seed)
    extreme = 0
    n = len(differences)
    tolerance = 1e-15
    for _ in range(resamples):
        randomized = sum(value if rng.getrandbits(1) else -value for value in differences) / n
        if abs(randomized) + tolerance >= observed:
            extreme += 1
    return (extreme + 1.0) / (resamples + 1.0)


def _holm_adjust(raw_p_values: Sequence[float], alpha: float) -> tuple[tuple[float, ...], tuple[bool, ...]]:
    if not 0.0 < alpha < 1.0:
        raise ValueError("familywise alpha must be in (0, 1)")
    m = len(raw_p_values)
    if m < 1:
        raise ValueError("at least one p-value is required")
    if any(not 0.0 <= value <= 1.0 for value in raw_p_values):
        raise ValueError("p-values must be in [0, 1]")

    order = sorted(range(m), key=raw_p_values.__getitem__)
    adjusted = [0.0] * m
    running_adjusted = 0.0
    for rank, index in enumerate(order):
        candidate = min(1.0, (m - rank) * raw_p_values[index])
        running_adjusted = max(running_adjusted, candidate)
        adjusted[index] = running_adjusted

    rejected = [False] * m
    still_rejecting = True
    for rank, index in enumerate(order):
        threshold = alpha / (m - rank)
        if still_rejecting and raw_p_values[index] <= threshold:
            rejected[index] = True
        else:
            still_rejecting = False
    return tuple(adjusted), tuple(rejected)


def analyze_confirmatory_accuracy(
    cases: Iterable[CaseAccuracy],
    *,
    contrasts: Sequence[tuple[str, str]] = PLANNED_CONTRASTS,
    minimum_effects: Mapping[tuple[str, str], float] | None = FROZEN_MINIMUM_EFFECTS,
    familywise_alpha: float = 0.05,
    confidence: float = 0.95,
    bootstrap_resamples: int = 10_000,
    randomization_resamples: int = 100_000,
    seed: int = 142_145,
) -> ConfirmatoryAnalysisResult:
    case_values = tuple(cases)
    if not case_values:
        raise ValueError("at least one independent case is required")
    for case in case_values:
        case.validate()
    case_ids = [case.case_id for case in case_values]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case IDs must be unique")
    draw_counts = {len(case.arm_draws[ARMS[0]]) for case in case_values}
    if len(draw_counts) != 1:
        raise ValueError("all cases must use the same evaluator draw count")
    evaluator_draws = next(iter(draw_counts))

    requested = tuple(contrasts)
    for treatment, control in requested:
        if treatment not in ARMS or control not in ARMS or treatment == control:
            raise ValueError(f"invalid contrast {treatment!r} - {control!r}")

    effects = {} if minimum_effects is None else dict(minimum_effects)
    unavailable_gates = set(effects).difference(requested)
    if unavailable_gates:
        raise ValueError(
            "all hard minimum-effect gates must be present in the analyzed contrast family: "
            f"{sorted(unavailable_gates)}"
        )

    provisional: list[tuple[str, str, float, float, float, float, float | None]] = []
    raw_p_values: list[float] = []
    for treatment, control in requested:
        differences = tuple(
            case.arm_mean(treatment) - case.arm_mean(control) for case in case_values
        )
        effect = sum(differences) / len(differences)
        ci_low, ci_high = _bootstrap_ci(
            differences,
            resamples=bootstrap_resamples,
            confidence=confidence,
            seed=_seed_for(seed, treatment, control, "bootstrap"),
        )
        p_raw = _paired_randomization_p(
            differences,
            resamples=randomization_resamples,
            seed=_seed_for(seed, treatment, control, "randomization"),
        )
        raw_p_values.append(p_raw)
        minimum = effects.get((treatment, control))
        provisional.append((treatment, control, effect, ci_low, ci_high, p_raw, minimum))

    adjusted, rejected = _holm_adjust(raw_p_values, familywise_alpha)
    results: list[ContrastResult] = []
    for index, values in enumerate(provisional):
        treatment, control, effect, ci_low, ci_high, p_raw, minimum = values
        statistically_positive = rejected[index] and ci_low > 0.0
        meets_minimum = None if minimum is None else effect >= minimum
        passes_success_rule = (
            None if minimum is None else statistically_positive and bool(meets_minimum)
        )
        results.append(
            ContrastResult(
                treatment=treatment,
                control=control,
                case_count=len(case_values),
                effect=effect,
                bootstrap_ci_low=ci_low,
                bootstrap_ci_high=ci_high,
                randomization_p_raw=p_raw,
                randomization_p_holm=adjusted[index],
                holm_reject=rejected[index],
                statistically_positive=statistically_positive,
                minimum_effect=minimum,
                meets_minimum_effect=meets_minimum,
                passes_success_rule=passes_success_rule,
            )
        )

    gated = [result for result in results if result.minimum_effect is not None]
    campaign_success = None if not gated else all(result.passes_success_rule is True for result in gated)

    return ConfirmatoryAnalysisResult(
        case_count=len(case_values),
        evaluator_draws_per_case_arm=evaluator_draws,
        familywise_alpha=familywise_alpha,
        bootstrap_resamples=bootstrap_resamples,
        randomization_resamples=randomization_resamples,
        seed=seed,
        campaign_success=campaign_success,
        contrasts=tuple(results),
    )


__all__ = [
    "ARMS",
    "FROZEN_MINIMUM_EFFECTS",
    "PLANNED_CONTRASTS",
    "CaseAccuracy",
    "ConfirmatoryAnalysisResult",
    "ContrastResult",
    "analyze_confirmatory_accuracy",
]
