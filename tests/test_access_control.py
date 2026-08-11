from __future__ import annotations

from pathlib import Path

from resonance.experiments.access_checkpoint import AccessMechanism, _arm, _hard_gate, _scaled
from resonance.experiments.access_config import load_access_config
from resonance.experiments.lifecycle_corrections import install_lifecycle_corrections


_CONFIG = Path("configs/experiments/access-075-080.json")


def _result(
    *,
    success: float,
    logical_incumbent: float,
    identity_incumbent: float,
    knowledge: float,
) -> dict[str, object]:
    return {
        "label": "candidate",
        "metrics": {
            "success_rate": success,
            "early_incumbent_share": logical_incumbent,
            "identity_early_incumbent_share": identity_incumbent,
            "mean_winner_hhi": 0.18,
            "late_public_knowledge_coverage": knowledge,
            "public_knowledge_coverage": knowledge,
            "late_cultural_lineage_hhi": 0.45,
            "cultural_lineage_hhi": 0.45,
            "mean_winning_price_fraction": 0.60,
            "credit_gini": 0.10,
        },
        "invariants": {"ledger_balanced": True, "cell_trace_isolated": True},
    }


def test_exposure_limit_is_non_destructive_and_reputation_neutral() -> None:
    config, _ = load_access_config(_CONFIG)
    mechanism = AccessMechanism(
        exposure_penalty=0.14,
        exposure_window=12,
        challenger_inflation=0.10,
    )
    arm = _arm(config, label="candidate", mechanism=mechanism)

    assert arm.lifecycle.mode == "immortal"
    assert not arm.lifecycle.finite
    assert arm.policy.mode == "reputation"
    assert arm.policy.weight == 0.0
    assert arm.policy.exposure_penalty == 0.14
    assert arm.environment.confidence_inflation == 0.10


def test_hard_gate_requires_logical_not_uuid_turnover() -> None:
    install_lifecycle_corrections()
    config, _ = load_access_config(_CONFIG)
    control = _result(
        success=0.50,
        logical_incumbent=0.12,
        identity_incumbent=0.12,
        knowledge=0.80,
    )
    uuid_only = _result(
        success=0.50,
        logical_incumbent=0.12,
        identity_incumbent=0.05,
        knowledge=0.80,
    )
    logical = _result(
        success=0.50,
        logical_incumbent=0.09,
        identity_incumbent=0.09,
        knowledge=0.80,
    )

    uuid_valid, uuid_effects = _hard_gate(uuid_only, control, config=config)
    logical_valid, logical_effects = _hard_gate(logical, control, config=config)

    assert uuid_effects["identity_incumbent_reduction"] > 0.02
    assert uuid_effects["logical_incumbent_reduction"] == 0.0
    assert not uuid_valid
    assert logical_effects["logical_incumbent_reduction"] >= 0.02
    assert logical_valid


def test_bounded_response_scales_strength_without_enabling_exit() -> None:
    mechanism = AccessMechanism(
        exposure_penalty=0.10,
        exposure_window=12,
        challenger_inflation=0.08,
        diversified_retrieval=True,
        diversified_lineages=3,
    )
    weaker = _scaled(mechanism, 0.65)
    stronger = _scaled(mechanism, 1.35)

    assert weaker.exposure_penalty < mechanism.exposure_penalty < stronger.exposure_penalty
    assert weaker.challenger_inflation < mechanism.challenger_inflation < stronger.challenger_inflation
    assert weaker.diversified_retrieval and stronger.diversified_retrieval
