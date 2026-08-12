from __future__ import annotations

import pytest

from resonance.experiments.llm_epistemic_power import (
    MINIMUM_EVALUABLE_CASES,
    PLANNED_CONFIRMATORY_CASES,
    R_MINUS_G_INSTRUMENTATION_DIFFERENCES,
    R_MINUS_P_INSTRUMENTATION_DIFFERENCES,
    build_frozen_power_report,
    normal_detection_power,
    two_point_residual_model,
    validate_frozen_power_adequacy,
)


def _by_effect(report):
    return {point.true_effect: point for point in report.empirical_grid}


def test_frozen_residual_models_use_variance_not_instrumentation_mean() -> None:
    rg = two_point_residual_model(R_MINUS_G_INSTRUMENTATION_DIFFERENCES)
    rp = two_point_residual_model(R_MINUS_P_INSTRUMENTATION_DIFFERENCES)

    assert rg.planning_sd == pytest.approx(0.1788854382)
    assert rp.planning_sd == pytest.approx(0.1095445115)
    assert (1.0 - rg.high_probability) * rg.low + rg.high_probability * rg.high == pytest.approx(0.0)
    assert (1.0 - rp.high_probability) * rp.low + rp.high_probability * rp.high == pytest.approx(0.0)


def test_496_is_the_frozen_sd_020_eighty_percent_detection_boundary() -> None:
    below = normal_detection_power(n=495, true_effect=0.03, paired_sd=0.20)
    boundary = normal_detection_power(n=496, true_effect=0.03, paired_sd=0.20)
    full = normal_detection_power(n=512, true_effect=0.03, paired_sd=0.20)

    assert below < 0.80
    assert boundary >= 0.80
    assert full > boundary


def test_empirical_power_report_separates_detection_from_hard_gate_pass() -> None:
    report = build_frozen_power_report()
    assert report.planned_case_count == PLANNED_CONFIRMATORY_CASES == 512
    assert report.minimum_evaluable_case_count == MINIMUM_EVALUABLE_CASES == 496

    rg = _by_effect(report.r_minus_g)
    assert rg[0.0].detection_power < 0.01
    assert rg[0.0].hard_gate_pass_probability < 0.001
    assert rg[0.03].detection_power > 0.90
    assert 0.45 < rg[0.03].hard_gate_pass_probability < 0.55
    assert rg[0.04].hard_gate_pass_probability > 0.85
    assert rg[0.05].hard_gate_pass_probability > 0.98

    rp = _by_effect(report.r_minus_p)
    assert rp[0.0].detection_power < 0.01
    assert rp[0.08].detection_power > 0.99
    assert 0.45 < rp[0.08].hard_gate_pass_probability < 0.55
    assert rp[0.09].hard_gate_pass_probability > 0.95


def test_power_report_rejects_fewer_than_minimum_evaluable_cases() -> None:
    with pytest.raises(ValueError, match="at least 496 evaluable cases"):
        build_frozen_power_report(case_count=495)


def test_frozen_power_adequacy_gate_passes() -> None:
    report = validate_frozen_power_adequacy()
    assert report.r_minus_g.normal_detection_power_at_gate_sd_020 >= 0.80
    assert report.r_minus_p.normal_detection_power_at_gate_sd_020 >= 0.80
