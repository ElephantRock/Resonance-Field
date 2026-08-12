from pathlib import Path

from resonance.experiments.llm_epistemic_config import (
    EXPECTED_CONFIRMATORY_CASE_COUNT,
    EXPECTED_MINIMUM_EVALUABLE_CASE_COUNT,
    load_llm_epistemic_config,
)


def test_llm_epistemic_config_smoke() -> None:
    config = load_llm_epistemic_config(
        Path("configs/experiments/llm-epistemic-substrate-142-145.json")
    )
    assert config.instrumentation_case_count == 24
    assert config.confirmatory_case_count == EXPECTED_CONFIRMATORY_CASE_COUNT == 512
    assert config.minimum_evaluable_case_count == EXPECTED_MINIMUM_EVALUABLE_CASE_COUNT == 496
    assert config.post_seal_case_replacement_allowed is False
    assert config.primary_endpoint == "post_agent_task_accuracy"
    assert dict(config.experiments)["145"] == "resonance_field"
    assert config.minimum_incremental_effect == 0.03
    assert config.minimum_total_effect == 0.08
    assert config.minimum_effects_are_hard_gates is True
    assert config.success_requires_all_priority_contrasts is True
    assert config.success_requires_holm_significance is True
    assert config.success_requires_positive_ci_lower is True
    assert config.power_detection_target == 0.80
    assert config.power_planning_paired_sd_ceiling_r_minus_g == 0.20
