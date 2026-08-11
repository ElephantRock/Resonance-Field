from __future__ import annotations

from resonance.experiments import lifecycle_campaign as lc
from resonance.experiments import lifecycle_checkpoint as cp
from resonance.experiments.lifecycle_config import load_lifecycle_config
from resonance.experiments.lifecycle_corrections import (
    _plasticity_valid,
    corrected_lifecycle_effects,
    corrected_lifecycle_feasible,
    corrected_lifecycle_utility,
    install_lifecycle_corrections,
    stochastic_exit_hazard,
)
from resonance.experiments.lifecycle_notebook import render_record


def _metrics(**overrides: float) -> dict[str, float]:
    values = {
        "success_rate": 0.50,
        "early_incumbent_share": 0.20,
        "identity_early_incumbent_share": 0.20,
        "identity_replacement_rate": 0.10,
        "mean_winner_hhi": 0.20,
        "public_knowledge_coverage": 0.70,
        "late_public_knowledge_coverage": 0.80,
        "cultural_lineage_hhi": 0.30,
        "late_cultural_lineage_hhi": 0.25,
        "mean_winning_price_fraction": 0.60,
        "credit_gini": 0.10,
        "agent_domain_mutual_information": 0.10,
        "reputation_brier_score": 0.20,
        "exit_count": 3.0,
    }
    values.update(overrides)
    return values


def _arm(label: str, **overrides: float) -> dict[str, object]:
    return {
        "label": label,
        "metrics": _metrics(**overrides),
        "invariants": {"ledger": True, "cell_trace_isolated": True},
        "policy": {},
        "lifecycle": {},
        "environment": {},
    }


def test_stochastic_hazard_matches_total_expected_lifetime() -> None:
    hazard = stochastic_exit_hazard(lifetime_cycles=24, minimum_age=6)
    assert hazard == 1 / 19
    expected_age = 6 + (1 - hazard) / hazard
    assert expected_age == 24


def test_lifecycle_effects_distinguish_uuid_from_logical_turnover() -> None:
    control = _arm("immortal", early_incumbent_share=0.30, identity_early_incumbent_share=0.30)
    renamed_only = _arm("finite", early_incumbent_share=0.30, identity_early_incumbent_share=0.05)
    effects = corrected_lifecycle_effects(renamed_only, control)
    assert effects["identity_incumbent_reduction"] == 0.25
    assert effects["logical_incumbent_reduction"] == 0.0


def test_utility_does_not_reward_forced_uuid_replacement() -> None:
    first = _metrics(identity_early_incumbent_share=0.40, identity_replacement_rate=0.0)
    second = _metrics(identity_early_incumbent_share=0.01, identity_replacement_rate=1.0)
    assert corrected_lifecycle_utility(first) == corrected_lifecycle_utility(second)


def test_feasibility_uses_matched_late_knowledge_window() -> None:
    config, _ = load_lifecycle_config("configs/experiments/lifecycle-063-074.json")
    control = _arm(
        "immortal_control",
        public_knowledge_coverage=0.10,
        late_public_knowledge_coverage=0.90,
    )
    candidate = _arm(
        "finite",
        public_knowledge_coverage=1.00,
        late_public_knowledge_coverage=0.70,
    )
    assert not corrected_lifecycle_feasible(
        candidate,
        control,
        config=config.integration,
        knowledge_tolerance=config.knowledge_tolerance,
    )


def test_plasticity_gate_rejects_uuid_only_improvement() -> None:
    config, _ = load_lifecycle_config("configs/experiments/lifecycle-063-074.json")
    effects = {
        "identity_incumbent_reduction": 0.30,
        "logical_incumbent_reduction": 0.0,
        "hhi_reduction": 0.0,
    }
    assert not _plasticity_valid(effects, config)


def test_install_patches_operational_checkpoint_path() -> None:
    install_lifecycle_corrections()
    assert lc.run_lifecycle_arm.__name__ == "corrected_run_lifecycle_arm"
    assert cp._holdout.__name__ == "_holdout_corrected"
    assert cp._replication.__name__ == "_replication_corrected"


def test_notebook_renders_record_without_legacy_selected_metrics() -> None:
    arm = _arm("candidate")
    arm["feasible"] = True
    arm["utility"] = 0.5
    record = {
        "number": 63,
        "focus": "immortal_baseline",
        "question": "baseline?",
        "selected_label": "candidate",
        "arms": [arm],
        "next_experiment_focus": "fixed_competitive_exit",
    }
    rendered = render_record(record)
    assert "Experiment 063 — completed" in rendered
    assert "Logical-slot incumbent share" in rendered
