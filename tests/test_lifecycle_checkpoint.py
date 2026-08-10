from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from resonance.experiments import lifecycle_checkpoint as checkpoint
from resonance.experiments.lifecycle_campaign import (
    LifecyclePolicy,
    SuccessionArm,
    _actor_incumbency,
    _replacement_due,
)


def _mapping() -> dict[str, object]:
    return {
        "name": "lifecycle-test",
        "environment": {
            "agents": 6,
            "domains": ["a", "b", "c"],
            "cycles": 36,
            "cycle_seconds": 10,
            "shift_period": 12,
            "candidate_count": 3,
            "task_budget": 10,
            "bid_deadline_seconds": 6,
            "trace_half_life_cycles": 6.0,
            "initial_credits": 500,
            "base_success_probability": 0.38,
            "practice_gain": 0.14,
            "maximum_success_probability": 0.90,
            "confidence_base": 0.35,
            "confidence_evidence_weight": 0.35,
            "confidence_noise_weight": 0.20,
            "price_floor": 0.45,
            "price_span": 0.35,
            "completion_min_seconds": 2,
            "completion_span_seconds": 3,
        },
        "seeds": [11],
        "holdout_seeds": [99],
        "holdout_cycles": 42,
        "holdout_shift_period": 10,
        "holdout_candidate_count": 3,
        "success_tolerance": 0.02,
        "incumbent_tolerance": 0.05,
        "economic_tolerance": 0.08,
        "lifecycle": {
            "expected_lifetime": 12,
            "short_lifetime": 8,
            "long_lifetime": 18,
            "holdout_lifetime": 15,
            "minimum_actor_incumbency_reduction": 0.03,
            "minimum_knowledge_retention": 0.80,
            "public_retrieval_k": 4,
            "public_success_gain": 0.04,
            "public_confidence_gain": 0.08,
            "advisory_success_gain": 0.03,
            "cultural_diversity_per_lineage": 1,
            "rapid_shift_period": 6,
            "replication_seeds": [55],
        },
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


def _summary(arm: SuccessionArm) -> dict[str, object]:
    finite = arm.lifecycle.mode != "immortal"
    no_rep = arm.policy.mode == "none"
    diversified = arm.lifecycle.public_retrieval == "diversified"
    advisor = arm.lifecycle.advisory
    success = 0.50 if no_rep else 0.54
    if finite:
        success -= 0.005
    if advisor:
        success += 0.012
    actor_inc = 0.16 if not finite else 0.05
    lineage_inc = 0.13 if not finite else 0.09
    knowledge = 0.80 if not finite else 0.76
    hhi = 0.34 if not diversified else 0.20
    if diversified:
        knowledge *= 0.97
    metrics = {
        "success_rate": success,
        "agent_domain_mutual_information": 0.50 if not no_rep else 0.35,
        "mean_specialization": 0.40 if not no_rep else 0.30,
        "mean_winner_hhi": 0.16,
        "early_incumbent_share": lineage_inc,
        "winner_replacement_rate": 0.90 if finite else 0.75,
        "reputation_brier_score": 0.25,
        "mean_winning_price_fraction": 0.52,
        "credit_gini": 0.02,
        "early_actor_incumbent_share": actor_inc,
        "turnover_events": 12.0 if finite else 0.0,
        "turnover_rate": 0.05 if finite else 0.0,
        "mean_public_knowledge_signal": knowledge,
        "mean_retrieval_lineage_hhi": hhi,
        "mean_predecessor_lineage_share": 0.18 if finite else 0.30,
        "newborn_success_rate": 0.48 if finite else 0.0,
        "max_generation": 2.0 if finite else 0.0,
    }
    return {
        "label": arm.label,
        "policy": arm.policy.as_dict(),
        "environment": {**arm.environment.as_dict(), "lifecycle": arm.lifecycle.as_dict()},
        "lifecycle": arm.lifecycle.as_dict(),
        "metrics": metrics,
        "invariants": _invariants(),
        "run_ids": [f"run-{arm.label}"],
        "utility": success - 0.10 * actor_inc - 0.06 * lineage_inc + 0.04 * knowledge - 0.03 * hhi,
    }


def _fake_run_succession_experiment(*args, **kwargs):
    del args
    return [_summary(arm) for arm in kwargs["arms"]]


def _fake_write_artifacts(connection, *, output_dir, record, checkpoint, **kwargs) -> None:
    del connection, kwargs
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "checkpoint.json").write_text(json.dumps(dict(checkpoint)))
    (output / "notebook.md").write_text(
        f"<!-- lifecycle-063-074:experiment-{int(record['number']):03d} -->\n"
    )
    if int(record["number"]) == 74:
        (output / "campaign-summary.md").write_text("complete\n")


def _install_fakes(monkeypatch) -> None:
    monkeypatch.setattr(checkpoint, "run_succession_experiment", _fake_run_succession_experiment)
    monkeypatch.setattr(checkpoint, "write_step_artifacts", _fake_write_artifacts)


def test_actor_incumbency_uses_identity_not_slot() -> None:
    a = UUID("00000000-0000-0000-0000-000000000001")
    b = UUID("00000000-0000-0000-0000-000000000002")
    successor = UUID("00000000-0000-0000-0000-000000000003")
    rows = []
    for cycle in range(12):
        rows.append(
            {
                "cycle": cycle,
                "task_domain": "a" if cycle % 2 == 0 else "b",
                "winner_agent_id": a if cycle % 2 == 0 else b,
                "winner": cycle % 2,
            }
        )
    for cycle in range(12, 24):
        rows.append(
            {
                "cycle": cycle,
                "task_domain": "a" if cycle % 2 == 0 else "b",
                "winner_agent_id": successor if cycle % 2 == 0 else b,
                "winner": cycle % 2,
            }
        )
    assert _actor_incumbency(rows, shift_period=12, window=12) == pytest.approx(0.5)


def test_fixed_lifecycle_exits_at_lifetime() -> None:
    lifecycle = LifecyclePolicy(mode="fixed", lifetime_cycles=12, disposition="retire")
    assert not _replacement_due(lifecycle, seed=1, cycle=11, slot=0, birth_cycle=0)
    assert _replacement_due(lifecycle, seed=1, cycle=12, slot=0, birth_cycle=0)


def test_retirement_and_death_are_distinct_dispositions() -> None:
    retirement = LifecyclePolicy(mode="fixed", lifetime_cycles=12, disposition="retire")
    death = LifecyclePolicy(mode="fixed", lifetime_cycles=12, disposition="death")
    assert retirement.as_dict() != death.as_dict()


def test_checkpointed_campaign_runs_63_through_74(monkeypatch, tmp_path: Path) -> None:
    config = checkpoint.LifecycleConfig.from_mapping(_mapping())
    _install_fakes(monkeypatch)
    state = None
    results = []
    for number in range(63, 75):
        output = tmp_path / f"exp-{number}"
        result = checkpoint.run_lifecycle_step(
            object(),  # type: ignore[arg-type]
            config=config,
            config_hash="lifecycle-config",
            code_sha="lifecycle-sha",
            number=number,
            checkpoint=state,
            output_dir=output,
        )
        results.append(result)
        state = json.loads((output / "checkpoint.json").read_text())
        assert state["last_completed"] == number
        assert (output / "notebook.md").read_text().startswith(
            f"<!-- lifecycle-063-074:experiment-{number:03d} -->"
        )

    assert [item["record"]["number"] for item in results] == list(range(63, 75))
    assert state["next_experiment"] is None
    assert state["candidate_lifecycle"] is not None
    assert state["candidate_policy"] is not None
    assert state["mechanism_validated"] is True
    assert state["replication_validated"] is True
    assert state["validated"] is True
    assert (tmp_path / "exp-74" / "campaign-summary.md").exists()


def test_checkpoint_rejects_skipped_experiment(monkeypatch, tmp_path: Path) -> None:
    config = checkpoint.LifecycleConfig.from_mapping(_mapping())
    _install_fakes(monkeypatch)
    result = checkpoint.run_lifecycle_step(
        object(),  # type: ignore[arg-type]
        config=config,
        config_hash="lifecycle-config",
        code_sha="lifecycle-sha",
        number=63,
        checkpoint=None,
        output_dir=tmp_path / "exp-63",
    )
    with pytest.raises(ValueError, match="immediately precede"):
        checkpoint.run_lifecycle_step(
            object(),  # type: ignore[arg-type]
            config=config,
            config_hash="lifecycle-config",
            code_sha="lifecycle-sha",
            number=65,
            checkpoint=result["checkpoint"],
            output_dir=tmp_path / "exp-65",
        )
