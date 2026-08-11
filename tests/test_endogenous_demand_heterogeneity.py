from resonance.experiments import endogenous_demand_heterogeneity as h


def test_threshold_fit_finds_simple_high_phase_boundary() -> None:
    values = [0.1, 0.2, 0.3, 0.8, 0.9, 1.0]
    labels = [False, False, False, True, True, True]
    fit = h._fit_threshold(values, labels)
    assert fit["direction"] == "positive_if_high"
    assert fit["accuracy"] == 1.0
    assert fit["balanced_accuracy"] == 1.0


def test_common_prefix_rejects_difference_only_after_boundary() -> None:
    control = [
        {"cycle": 0, "domain_index": 1, "required_skill": "a", "winner_slot": 2, "success": True},
        {"cycle": 1, "domain_index": 2, "required_skill": "b", "winner_slot": 3, "success": False},
        {"cycle": 2, "domain_index": 3, "required_skill": "c", "winner_slot": 4, "success": True},
    ]
    feedback = [dict(row) for row in control]
    feedback[2]["winner_slot"] = 5
    assert h._common_prefix_exact(control, feedback, end=2)
    assert not h._common_prefix_exact(control, feedback, end=3)


def test_feature_selection_returns_none_when_no_candidate_qualifies() -> None:
    evaluations = [
        {
            "feature": "common_prefix_cycles",
            "loo_balanced_accuracy": 0.5,
            "loo_accuracy": 0.5,
            "spearman_delta_incumbency": 0.1,
            "familywise_permutation_p": 1.0,
            "loo_direction_stable": True,
            "qualifies_phase_candidate": False,
        }
    ]
    assert h._select_phase_condition(evaluations) is None
