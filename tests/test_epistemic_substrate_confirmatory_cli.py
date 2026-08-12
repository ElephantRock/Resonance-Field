from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from resonance.experiments.epistemic_substrate_campaign import ArmMetrics
from resonance.experiments.epistemic_substrate_config import load_epistemic_substrate_config
from resonance.experiments.epistemic_substrate_confirmatory_cli import (
    _quality_gates,
    _validate_instrumentation_evidence,
)

CONFIG_PATH = Path("configs/experiments/epistemic-substrate-138-141.json")


def _metric(arm: str) -> ArmMetrics:
    return ArmMetrics(
        arm=arm,
        transfer_accuracy=0.5,
        collective_emergence_ratio=0.5,
        evidence_coverage=1.0,
        contradiction_resolution_f1=0.5,
        bridge_recall=0.5,
        provenance_completeness=float(arm != "pile"),
        knowledge_survival_rate=1.0,
        duplicate_work_rate=0.0,
        false_synthesis_rate=0.0,
        retrieval_items_consumed=1.0,
    )


def test_confirmatory_gate_requires_matching_instrumentation(tmp_path: Path) -> None:
    config, config_hash = load_epistemic_substrate_config(CONFIG_PATH)
    evidence = {
        "campaign": config.name,
        "config_hash": config_hash,
        "inferential": False,
        "confirmatory_seeds_evaluated": False,
        "instrumentation_validated": True,
        "seeds": list(config.instrumentation_seeds),
    }
    path = tmp_path / "instrumentation.json"
    path.write_text(json.dumps(evidence))
    _validate_instrumentation_evidence(path, config, config_hash)

    evidence["config_hash"] = "wrong"
    path.write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match="config hash"):
        _validate_instrumentation_evidence(path, config, config_hash)


def test_quality_gate_can_be_tested_without_confirmatory_cohort() -> None:
    config, _digest = load_epistemic_substrate_config(CONFIG_PATH)
    synthetic = replace(config, confirmatory_seeds=(1,))
    metrics = (
        _metric("pile"),
        _metric("shared_memory"),
        _metric("provenance_graph"),
        _metric("resonance_field"),
    )
    valid, failures = _quality_gates({1: metrics}, synthetic)
    assert valid is True
    assert failures == []
