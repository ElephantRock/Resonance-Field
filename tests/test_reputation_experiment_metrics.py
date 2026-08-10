from __future__ import annotations

from uuid import UUID

from resonance.experiments.reputation_metrics import summarize_reputation_experiment

A = UUID("00000000-0000-0000-0000-000000000001")
B = UUID("00000000-0000-0000-0000-000000000002")


def test_metrics_detect_incumbent_replacement_after_shift() -> None:
    rows = []
    for cycle in range(8):
        rows.append(
            {
                "cycle": cycle,
                "task_domain": "alpha" if cycle % 2 == 0 else "beta",
                "winner_agent_id": A,
                "reputation_score": 0.75,
                "success": True,
            }
        )
    for cycle in range(8, 16):
        rows.append(
            {
                "cycle": cycle,
                "task_domain": "alpha" if cycle % 2 == 0 else "beta",
                "winner_agent_id": B,
                "reputation_score": 0.55,
                "success": cycle % 3 != 0,
            }
        )
    metrics = summarize_reputation_experiment(
        rows,
        domains=("alpha", "beta"),
        shift_cycle=8,
        early_post_shift_cycles=4,
        late_post_shift_cycles=4,
    )
    assert metrics["pre_shift_incumbent_share_early_post"] == 0.0
    assert metrics["post_shift_winner_replacement_rate"] == 1.0
    assert metrics["adaptation_latency_cycles"] == 4
    assert metrics["unique_winners"] == 2
