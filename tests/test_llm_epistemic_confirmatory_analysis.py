from __future__ import annotations

import pytest

from resonance.experiments.llm_epistemic_confirmatory_analysis import (
    ARMS,
    FROZEN_MINIMUM_EFFECTS,
    CaseAccuracy,
    analyze_confirmatory_accuracy,
)


def _case(case_id: str, **arm_values: tuple[float, ...]) -> CaseAccuracy:
    return CaseAccuracy(case_id=case_id, arm_draws=arm_values)


def test_identical_arms_fail_frozen_campaign_success_rule() -> None:
    cases = [
        _case(
            f"case-{index}",
            pile=(1.0, 0.0, 1.0, 1.0, 0.0),
            shared_memory=(1.0, 0.0, 1.0, 1.0, 0.0),
            provenance_graph=(1.0, 0.0, 1.0, 1.0, 0.0),
            resonance_field=(1.0, 0.0, 1.0, 1.0, 0.0),
        )
        for index in range(8)
    ]

    result = analyze_confirmatory_accuracy(
        cases,
        bootstrap_resamples=200,
        randomization_resamples=500,
        seed=7,
    )

    assert result.case_count == 8
    assert result.evaluator_draws_per_case_arm == 5
    assert result.campaign_success is False
    gated = 0
    for contrast in result.contrasts:
        assert contrast.effect == 0.0
        assert contrast.bootstrap_ci_low == 0.0
        assert contrast.bootstrap_ci_high == 0.0
        assert contrast.randomization_p_raw == 1.0
        assert contrast.randomization_p_holm == 1.0
        assert contrast.holm_reject is False
        assert contrast.statistically_positive is False
        if contrast.minimum_effect is not None:
            gated += 1
            assert contrast.meets_minimum_effect is False
            assert contrast.passes_success_rule is False
        else:
            assert contrast.meets_minimum_effect is None
            assert contrast.passes_success_rule is None
    assert gated == 2


def test_analysis_reduces_nested_draws_to_one_mean_per_case() -> None:
    cases = [
        _case(
            "case-a",
            pile=(0.0, 0.0, 0.0, 0.0, 0.0),
            shared_memory=(0.0, 0.0, 0.0, 0.0, 0.0),
            provenance_graph=(1.0, 1.0, 1.0, 1.0, 0.0),
            resonance_field=(1.0, 1.0, 1.0, 1.0, 1.0),
        ),
        _case(
            "case-b",
            pile=(1.0, 1.0, 1.0, 1.0, 1.0),
            shared_memory=(1.0, 1.0, 1.0, 1.0, 1.0),
            provenance_graph=(0.0, 0.0, 0.0, 0.0, 1.0),
            resonance_field=(0.0, 0.0, 0.0, 0.0, 0.0),
        ),
    ]

    result = analyze_confirmatory_accuracy(
        cases,
        contrasts=(("resonance_field", "provenance_graph"),),
        minimum_effects=None,
        bootstrap_resamples=200,
        randomization_resamples=500,
        seed=11,
    )

    contrast = result.contrasts[0]
    # Case-level differences are +0.2 and -0.2, so the paired effect is zero.
    assert contrast.effect == pytest.approx(0.0)
    assert contrast.case_count == 2
    assert result.campaign_success is None


def test_strong_paired_effect_is_detected_and_minimum_effect_is_reported() -> None:
    cases = [
        _case(
            f"case-{index}",
            pile=(0.0,) * 5,
            shared_memory=(0.0,) * 5,
            provenance_graph=(0.0,) * 5,
            resonance_field=(1.0,) * 5,
        )
        for index in range(20)
    ]

    result = analyze_confirmatory_accuracy(
        cases,
        contrasts=(("resonance_field", "provenance_graph"),),
        minimum_effects={("resonance_field", "provenance_graph"): 0.03},
        bootstrap_resamples=500,
        randomization_resamples=2_000,
        seed=23,
    )

    contrast = result.contrasts[0]
    assert contrast.effect == 1.0
    assert contrast.bootstrap_ci_low == 1.0
    assert contrast.bootstrap_ci_high == 1.0
    assert contrast.randomization_p_raw < 0.01
    assert contrast.randomization_p_holm < 0.01
    assert contrast.holm_reject is True
    assert contrast.statistically_positive is True
    assert contrast.minimum_effect == 0.03
    assert contrast.meets_minimum_effect is True
    assert contrast.passes_success_rule is True
    assert result.campaign_success is True


def test_campaign_success_requires_both_frozen_priority_effect_gates() -> None:
    cases = [
        _case(
            f"case-{index}",
            pile=(0.0,) * 5,
            shared_memory=(0.0,) * 5,
            provenance_graph=(0.0,) * 5,
            resonance_field=(1.0,) * 5,
        )
        for index in range(20)
    ]
    result = analyze_confirmatory_accuracy(
        cases,
        bootstrap_resamples=500,
        randomization_resamples=2_000,
        seed=29,
    )

    assert result.campaign_success is True
    gated = {
        (contrast.treatment, contrast.control): contrast
        for contrast in result.contrasts
        if contrast.minimum_effect is not None
    }
    assert set(gated) == set(FROZEN_MINIMUM_EFFECTS)
    assert all(contrast.passes_success_rule is True for contrast in gated.values())


def test_statistical_significance_alone_cannot_bypass_minimum_effect_gate() -> None:
    # R beats G and P in every case, but by only one of five nested draws = 0.20.
    # Raise the test-only gate above that observed effect to verify hard-gate semantics.
    cases = [
        _case(
            f"case-{index}",
            pile=(0.0,) * 5,
            shared_memory=(0.0,) * 5,
            provenance_graph=(0.0,) * 5,
            resonance_field=(1.0, 0.0, 0.0, 0.0, 0.0),
        )
        for index in range(20)
    ]
    result = analyze_confirmatory_accuracy(
        cases,
        contrasts=(("resonance_field", "provenance_graph"),),
        minimum_effects={("resonance_field", "provenance_graph"): 0.25},
        bootstrap_resamples=500,
        randomization_resamples=2_000,
        seed=31,
    )

    contrast = result.contrasts[0]
    assert contrast.effect == pytest.approx(0.20)
    assert contrast.statistically_positive is True
    assert contrast.meets_minimum_effect is False
    assert contrast.passes_success_rule is False
    assert result.campaign_success is False


def test_all_hard_gates_must_be_in_analyzed_family() -> None:
    arm_values = {arm: (1.0, 0.0) for arm in ARMS}
    with pytest.raises(ValueError, match="all hard minimum-effect gates"):
        analyze_confirmatory_accuracy(
            [_case("case-1", **arm_values)],
            contrasts=(("resonance_field", "provenance_graph"),),
            bootstrap_resamples=10,
            randomization_resamples=10,
        )


def test_case_validation_rejects_nonbinary_or_unequal_nested_draws() -> None:
    unequal = _case(
        "unequal",
        pile=(1.0, 0.0),
        shared_memory=(1.0,),
        provenance_graph=(1.0, 0.0),
        resonance_field=(1.0, 0.0),
    )
    with pytest.raises(ValueError, match="equal nonzero draw counts"):
        unequal.validate()

    nonbinary = _case(
        "nonbinary",
        **{arm: (1.0, 0.5) if arm == "pile" else (1.0, 0.0) for arm in ARMS},
    )
    with pytest.raises(ValueError, match="non-binary primary score"):
        nonbinary.validate()


def test_duplicate_case_ids_are_rejected() -> None:
    arm_values = {arm: (1.0, 0.0) for arm in ARMS}
    cases = [_case("duplicate", **arm_values), _case("duplicate", **arm_values)]
    with pytest.raises(ValueError, match="case IDs must be unique"):
        analyze_confirmatory_accuracy(
            cases,
            minimum_effects=None,
            bootstrap_resamples=10,
            randomization_resamples=10,
        )
