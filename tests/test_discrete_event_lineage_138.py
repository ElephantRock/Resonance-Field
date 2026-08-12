from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from resonance.experiments.discrete_event_lineage_138 import (
    _aggregate_calibration,
    _event_id,
    _trace_catalog,
)
from resonance.experiments.lineage_instrumentation_config import load_lineage_config

_CONFIG = Path("configs/experiments/discrete-event-lineage-138.json")


def test_experiment_138_config_freezes_split_gates_and_ontology() -> None:
    config, _ = load_lineage_config(_CONFIG)
    assert config.schema_version == "v1"
    assert config.calibration_seeds == tuple(range(3101, 3107))
    assert config.validation_seeds == tuple(range(3107, 3113))
    assert set(config.calibration_seeds).isdisjoint(config.validation_seeds)
    assert config.primary_window == (36, 53)
    assert config.attribution_threshold == 0.90
    assert config.single_parent_threshold == 0.75
    assert config.maximum_corrective_revisions == 2
    assert config.channel_edge_share_threshold == 0.25
    assert config.channel_pair_prevalence == 4
    assert config.event_classes == (
        "auction_award",
        "settlement_transfer",
        "success_outcome",
        "practice_update",
        "trace_evidence_gate",
        "trace_retrieval_selection",
        "feedback_domain_choice",
        "public_knowledge_write",
    )


def test_event_ids_are_stable_runtime_coordinates() -> None:
    assert _event_id(3101, 36, "auction_award", "winner") == (
        "e138:3101:036:40:auction_award:winner"
    )
    assert _event_id(3101, 41, "trace_evidence_gate", "slot:3") == (
        "e138:3101:041:30:trace_evidence_gate:slot:3"
    )


def test_trace_catalog_uses_only_prior_successful_writes_and_frozen_decay() -> None:
    env = SimpleNamespace(
        trace_half_life_cycles=8.0,
        cycle_seconds=30,
        bid_deadline_seconds=20,
    )
    outcomes = {
        4: {"cycle": 4, "winner_slot": 2, "required_skill": "a", "success": True},
        5: {"cycle": 5, "winner_slot": 3, "required_skill": "a", "success": False},
        6: {"cycle": 6, "winner_slot": 1, "required_skill": "b", "success": True},
    }
    rows = _trace_catalog(outcomes, cycle=6, env=env)
    assert len(rows) == 1
    assert rows[0]["key"] == "trace:4:2:a"
    assert 0.0 < float(rows[0]["energy"]) < 0.9


def _pair(
    *,
    seed: int,
    downstream: int,
    attributable: int,
    root_path_share: float,
    root_gate: bool = True,
) -> dict[str, object]:
    return {
        "seed": seed,
        "primary_downstream_event_count": downstream,
        "attributable_primary_event_count": attributable,
        "orphan_primary_event_count": downstream - attributable,
        "root_path_share": root_path_share,
        "root_gate": root_gate,
        "single_parent_count": attributable,
        "multi_parent_count": 0,
        "channel_edge_counts": {},
    }


def test_calibration_capture_is_pooled_but_retains_per_seed_root_path_guard() -> None:
    config, _ = load_lineage_config(_CONFIG)
    pairs = [
        _pair(seed=3101, downstream=90, attributable=90, root_path_share=1.0),
        _pair(seed=3102, downstream=10, attributable=0, root_path_share=1.0),
        *[
            _pair(seed=seed, downstream=0, attributable=0, root_path_share=1.0)
            for seed in range(3103, 3107)
        ],
    ]
    result = _aggregate_calibration(pairs, config=config)
    assert result["pooled_capture"] == 0.9
    assert result["calibration_ready"] is True

    pairs[0]["root_path_share"] = 0.89
    result = _aggregate_calibration(pairs, config=config)
    assert result["pooled_capture"] == 0.9
    assert result["per_seed_root_path_guard"] is False
    assert result["calibration_ready"] is False


def test_zero_downstream_events_never_pass_vacuously() -> None:
    config, _ = load_lineage_config(_CONFIG)
    pairs = [
        _pair(seed=seed, downstream=0, attributable=0, root_path_share=1.0)
        for seed in config.calibration_seeds
    ]
    result = _aggregate_calibration(pairs, config=config)
    assert result["pooled_primary_downstream_events"] == 0
    assert result["calibration_ready"] is False
    assert result["calibration_conclusion"] == "lineage_capture_not_calibration_ready"
