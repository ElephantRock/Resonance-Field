from __future__ import annotations

import json
from pathlib import Path

import pytest

from resonance.experiments.epistemic_substrate_config import (
    EXPECTED_CONFIRMATORY_CONTRASTS,
    EXPECTED_EXPERIMENTS,
    load_epistemic_substrate_config,
)


CONFIG_PATH = Path("configs/experiments/epistemic-substrate-138-141.json")


def _mutated_config(tmp_path: Path, value: dict[str, object]) -> Path:
    mutated = tmp_path / "mutated.json"
    mutated.write_text(json.dumps(value))
    return mutated


def test_epistemic_substrate_config_is_frozen_and_loadable() -> None:
    config, digest = load_epistemic_substrate_config(CONFIG_PATH)

    assert dict(config.experiments) == EXPECTED_EXPERIMENTS
    assert config.confirmatory_contrasts == EXPECTED_CONFIRMATORY_CONTRASTS
    assert config.primary_endpoints == (
        "transfer_accuracy",
        "collective_emergence_ratio",
    )
    assert len(config.instrumentation_seeds) == 8
    assert len(config.confirmatory_seeds) == 64
    assert len(digest) == 64


def test_epistemic_substrate_rejects_agent_population_change(tmp_path: Path) -> None:
    value = json.loads(CONFIG_PATH.read_text())
    value["benchmark"]["agent_count"] = 33

    with pytest.raises(ValueError, match="population or evidence geometry"):
        load_epistemic_substrate_config(_mutated_config(tmp_path, value))


def test_epistemic_substrate_rejects_treatment_relabeling(tmp_path: Path) -> None:
    value = json.loads(CONFIG_PATH.read_text())
    value["experiments"]["141"] = "provenance_graph"

    with pytest.raises(ValueError, match="experiment-to-arm assignment"):
        load_epistemic_substrate_config(_mutated_config(tmp_path, value))


def test_epistemic_substrate_rejects_arm_semantics_change(tmp_path: Path) -> None:
    value = json.loads(CONFIG_PATH.read_text())
    value["arms"]["pile"]["cross_agent_reads_during_discovery"] = True

    with pytest.raises(ValueError, match="substrate arm semantics"):
        load_epistemic_substrate_config(_mutated_config(tmp_path, value))


def test_epistemic_substrate_rejects_resonance_parameter_change(tmp_path: Path) -> None:
    value = json.loads(CONFIG_PATH.read_text())
    value["resonance"]["bridge_gain"] = 0.25

    with pytest.raises(ValueError, match="resonance dynamics"):
        load_epistemic_substrate_config(_mutated_config(tmp_path, value))


def test_epistemic_substrate_requires_producer_death_before_transfer(
    tmp_path: Path,
) -> None:
    value = json.loads(CONFIG_PATH.read_text())
    value["benchmark"]["producer_memory_destroyed_before_transfer"] = False

    with pytest.raises(ValueError, match="producer memory must be destroyed"):
        load_epistemic_substrate_config(_mutated_config(tmp_path, value))
