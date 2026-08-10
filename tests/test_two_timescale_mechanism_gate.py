from __future__ import annotations

from resonance.experiments import two_timescale_checkpoint as checkpoint
from resonance.experiments.integration_campaign import ReputationPolicy
from resonance.experiments.two_timescale_config import load_two_timescale_config


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


def _arm(label: str, policy: ReputationPolicy, environment, *, feasible: bool, utility: float):
    return {
        "label": label,
        "policy": policy.as_dict(),
        "environment": environment.as_dict(),
        "metrics": {
            "success_rate": 0.50,
            "agent_domain_mutual_information": 0.20,
            "mean_specialization": 0.22,
            "mean_winner_hhi": 0.14,
            "early_incumbent_share": 0.05,
            "winner_replacement_rate": 0.88,
            "reputation_brier_score": 0.24,
            "mean_winning_price_fraction": 0.52,
            "credit_gini": 0.01,
        },
        "invariants": _invariants(),
        "run_ids": [f"run-{label}"],
        "feasible": feasible,
        "utility": utility,
    }


def test_failed_derived_gate_cannot_become_valid_candidate(monkeypatch) -> None:
    config, _ = load_two_timescale_config("configs/experiments/two-timescale-053-062.json")
    reference = checkpoint.reference_policy()

    def fake_run_experiment(*args, **kwargs):
        del args
        env = kwargs["arms"][0].environment
        gated = kwargs["arms"][2].policy
        return (
            [
                _arm("no_reputation", ReputationPolicy(), env, feasible=True, utility=0.50),
                _arm("full_reputation", reference, env, feasible=True, utility=0.55),
                _arm("two_timescale_gated", gated, env, feasible=False, utility=0.60),
            ],
            None,
            None,
        )

    monkeypatch.setattr(checkpoint, "_run_experiment", fake_run_experiment)
    state: dict[str, object] = {
        "model": {"theta_f": 1.5, "theta_d": 2.0, "accuracy": 1.0},
        "model_test": {
            "practice_gain": config.interpolation_practice_gain,
            "tau_f": 12.0,
            "tau_d": 9.0,
            "shift_period": 18,
        },
        "mechanism_validated": False,
    }

    record = checkpoint._run_mechanism_test(  # noqa: SLF001
        object(),  # type: ignore[arg-type]
        config=config,
        config_hash="config",
        code_sha="sha",
        state=state,
    )

    assert record["selected_label"] == "no_reputation"
    assert record["validated"] is False
    assert state["mechanism_validated"] is False
    assert state["candidate_label"] == "no_reputation"
    assert state["candidate_policy"] == ReputationPolicy().as_dict()
