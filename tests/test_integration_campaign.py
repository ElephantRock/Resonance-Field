from __future__ import annotations

from pathlib import Path

from resonance.experiments import integration_campaign as campaign


def _config() -> campaign.IntegrationCampaignConfig:
    environment = campaign.IntegrationEnvironment(
        agents=6,
        domains=("a", "b", "c"),
        cycles=16,
        cycle_seconds=10,
        shift_period=8,
        candidate_count=3,
        task_budget=10,
        bid_deadline_seconds=6,
        trace_half_life_cycles=6.0,
        initial_credits=500,
        base_success_probability=0.38,
        practice_gain=0.10,
        maximum_success_probability=0.90,
        confidence_base=0.35,
        confidence_evidence_weight=0.35,
        confidence_noise_weight=0.20,
        price_floor=0.45,
        price_span=0.35,
        completion_min_seconds=2,
        completion_span_seconds=3,
    )
    return campaign.IntegrationCampaignConfig(
        name="integration-test",
        environment=environment,
        seeds=(11,),
        holdout_seeds=(99,),
        holdout_cycles=18,
        holdout_shift_period=6,
        holdout_candidate_count=3,
        success_tolerance=0.02,
        incumbent_tolerance=0.05,
        economic_tolerance=0.08,
    )


def _metrics(*, reputation: bool) -> dict[str, float]:
    return {
        "success_rate": 0.54 if reputation else 0.50,
        "agent_domain_mutual_information": 0.18 if reputation else 0.10,
        "mean_specialization": 0.20 if reputation else 0.10,
        "mean_winner_hhi": 0.12,
        "early_incumbent_share": 0.08,
        "winner_replacement_rate": 0.80,
        "reputation_brier_score": 0.20 if reputation else 0.25,
        "mean_winning_price_fraction": 0.55,
        "credit_gini": 0.08,
    }


def _invariants() -> dict[str, bool]:
    return {
        "ledger_conserved": True,
        "balanced_ledger": True,
        "zero_completed_escrow": True,
        "score_provenance_complete": True,
        "reputation_evidence_idempotent": True,
        "sealed_bids_immutable": True,
        "score_provenance_immutable": True,
        "reputation_nonspendable": True,
    }


def test_campaign_has_27_result_driven_experiments(monkeypatch, tmp_path: Path) -> None:
    config = _config()

    def fake_run_experiment(*args, **kwargs):
        del args
        arms = kwargs["arms"]
        summaries = []
        for arm in arms:
            reputation = arm.policy.mode == "reputation"
            summaries.append(
                {
                    "label": arm.label,
                    "policy": arm.policy.as_dict(),
                    "environment": arm.environment.as_dict(),
                    "metrics": _metrics(reputation=reputation),
                    "invariants": _invariants(),
                    "run_ids": [f"run-{arm.label}"],
                    "feasible": True,
                    "utility": 0.60 if reputation else 0.50,
                }
            )
        control = next(item for item in summaries if item["label"] == "no_reputation")
        candidates = [item for item in summaries if item["label"] != "no_reputation"]
        selected = max(candidates, key=lambda item: float(item["utility"]))
        return summaries, selected, control

    monkeypatch.setattr(campaign, "_run_experiment", fake_run_experiment)
    monkeypatch.setattr(campaign, "export_integration_campaign_artifacts", lambda *args, **kwargs: None)

    result = campaign.run_integration_campaign(
        object(),  # type: ignore[arg-type]
        config=config,
        config_hash="test-config",
        code_sha="test-sha",
        output_dir=tmp_path,
    )
    experiments = result["experiments"]
    assert [item["number"] for item in experiments] == list(range(14, 41))
    assert len(experiments) == 27
    assert experiments[0]["focus"] == "integration_bridge"

    local_focuses = [item["focus"] for item in experiments if 15 <= item["number"] <= 37]
    assert len(local_focuses) == 23
    assert len(set(local_focuses)) == 23
    assert set(local_focuses) == set(campaign._DIMENSIONS)

    assert experiments[37 - 14]["next_experiment_focus"].startswith("stress:")
    assert experiments[38 - 14]["next_experiment_focus"].startswith("replication:")
    assert experiments[39 - 14]["next_experiment_focus"].startswith("holdout:")
    assert experiments[-1]["next_experiment_focus"] is None
    assert isinstance(experiments[-1]["validated"], bool)


def test_validated_policy_is_nonspendable_configuration_only() -> None:
    policy = campaign.validated_policy()
    assert policy.mode == "reputation"
    assert policy.weight == 0.55
    assert policy.freshness_half_life_cycles == 24.0
    assert policy.mass_gate == 2.0
    assert policy.positive_weight == 2.0
    assert policy.shift_reset == 0.8
