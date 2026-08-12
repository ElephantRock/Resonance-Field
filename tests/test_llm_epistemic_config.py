from pathlib import Path

from resonance.experiments.llm_epistemic_config import load_llm_epistemic_config


def test_llm_epistemic_config_smoke() -> None:
    config = load_llm_epistemic_config(
        Path("configs/experiments/llm-epistemic-substrate-142-145.json")
    )
    assert config.instrumentation_case_count == 24
    assert config.confirmatory_case_count == 96
    assert config.primary_endpoint == "post_agent_task_accuracy"
    assert dict(config.experiments)["145"] == "resonance_field"
