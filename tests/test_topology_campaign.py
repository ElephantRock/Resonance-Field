from __future__ import annotations

from pathlib import Path

import pytest

from resonance.experiments.topology_checkpoint import _decomposition_specs, _hard_gate
from resonance.experiments.topology_config import (
    TopologySpec,
    load_topology_config,
    with_fraction,
)

_CONFIG = Path("configs/experiments/topology-087-092.json")


def test_topology_spec_separates_baseline_from_intervention() -> None:
    baseline = TopologySpec()
    assert not baseline.intervention

    hybrid = TopologySpec(
        mode="hybrid",
        structured_fraction=0.75,
        cooldown_cycles=12,
    )
    assert hybrid.intervention
    assert hybrid.structured_fraction == 0.75
    assert hybrid.cooldown_cycles == 12

    with pytest.raises(ValueError):
        TopologySpec(mode="winner_cooldown", structured_fraction=1.0)


def test_response_scaling_changes_routing_fraction_only() -> None:
    spec = TopologySpec(
        mode="hybrid",
        structured_fraction=1.0,
        cooldown_cycles=12,
        reset_each_regime=True,
    )
    scaled = with_fraction(spec, 0.5)
    assert scaled.mode == spec.mode
    assert scaled.structured_fraction == 0.5
    assert scaled.cooldown_cycles == spec.cooldown_cycles
    assert scaled.reset_each_regime


def test_hybrid_decomposition_removes_coordination_components_independently() -> None:
    spec = TopologySpec(
        mode="hybrid",
        structured_fraction=0.75,
        cooldown_cycles=12,
    )
    items = dict(_decomposition_specs(spec))
    assert items["candidate_full"] == spec
    assert items["without_winner_cooldown"].mode == "domain_balance"
    assert items["without_domain_balance"].mode == "winner_cooldown"


def _arm(metrics: dict[str, float]) -> dict[str, object]:
    return {
        "metrics": metrics,
        "invariants": {
            "ledger_conserved": True,
            "balanced_ledger": True,
            "zero_completed_escrow": True,
            "score_provenance_complete": True,
            "reputation_evidence_idempotent": True,
            "sealed_bids_immutable": True,
            "score_provenance_immutable": True,
            "reputation_nonspendable": True,
            "cell_trace_isolated": True,
            "succession_balance_preserved": True,
            "topology_observation_complete": True,
            "identity_turnover_absent": True,
        },
    }


def test_hard_gate_requires_both_logical_and_preaward_topology_change() -> None:
    config, _ = load_topology_config(_CONFIG)
    control = {
        "success_rate": 0.50,
        "early_incumbent_share": 0.11,
        "identity_early_incumbent_share": 0.11,
        "mean_winner_hhi": 0.18,
        "late_public_knowledge_coverage": 0.80,
        "late_cultural_lineage_hhi": 0.30,
        "mean_winning_price_fraction": 0.60,
        "credit_gini": 0.10,
        "incumbent_opportunity_share": 0.65,
        "opportunity_agent_gini": 0.12,
        "opportunity_edge_hhi": 0.03,
        "opportunity_repeat_rate": 0.45,
        "exit_count": 0.0,
    }
    candidate = dict(control)
    candidate.update(
        {
            "success_rate": 0.495,
            "early_incumbent_share": 0.08,
            "identity_early_incumbent_share": 0.08,
            "incumbent_opportunity_share": 0.50,
            "opportunity_agent_gini": 0.08,
            "opportunity_edge_hhi": 0.02,
            "opportunity_repeat_rate": 0.30,
        }
    )
    hard, feasible, effects = _hard_gate(_arm(candidate), _arm(control), config=config)
    assert feasible
    assert hard
    assert effects["logical_incumbent_reduction"] >= 0.02
    assert effects["incumbent_opportunity_reduction"] >= 0.08

    candidate["incumbent_opportunity_share"] = 0.60
    hard, _, _ = _hard_gate(_arm(candidate), _arm(control), config=config)
    assert not hard

    candidate["incumbent_opportunity_share"] = 0.50
    candidate["early_incumbent_share"] = 0.10
    hard, _, _ = _hard_gate(_arm(candidate), _arm(control), config=config)
    assert not hard
