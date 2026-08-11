from __future__ import annotations

from resonance.experiments.endogenous_demand_campaign import _FeedbackController
from resonance.experiments.endogenous_demand_config import EndogenousDemandSpec


def _domain(seed: int, cycle: int, count: int) -> int:
    del seed
    return cycle % count


def _draw(seed: int, cycle: int, slot: int, label: str) -> float:
    del seed, cycle, slot
    if label == "endogenous-demand-switch":
        return 0.0
    if label == "endogenous-demand-domain":
        return 0.1
    return 0.5


def test_feedback_is_inert_until_success() -> None:
    controller = _FeedbackController(
        spec=EndogenousDemandSpec(mode="closed_loop", strength=0.75),
        seed=1,
        cycles=9,
        domain_count=3,
        window=12,
        domain_fn=_domain,
        draw_fn=_draw,
    )
    assert controller.choose_domain(1, 0, 3) == 0
    assert controller.events[-1]["feedback_branch_taken"] is False
    assert controller.choose_domain(1, 1, 3) == 1
    assert controller.events[-1]["feedback_branch_taken"] is False


def test_success_reinforces_same_domain_on_next_cycle() -> None:
    controller = _FeedbackController(
        spec=EndogenousDemandSpec(mode="closed_loop", strength=0.75),
        seed=1,
        cycles=9,
        domain_count=3,
        window=12,
        domain_fn=_domain,
        draw_fn=_draw,
    )
    assert controller.choose_domain(1, 0, 3) == 0
    controller.observe_success()
    assert controller.choose_domain(1, 1, 3) == 0
    assert controller.events[-1]["feedback_branch_taken"] is True
    assert controller.events[-1]["rolling_success_counts"] == [1, 0, 0]


def test_permuted_source_breaks_same_domain_alignment() -> None:
    controller = _FeedbackController(
        spec=EndogenousDemandSpec(mode="permuted_source", strength=0.75),
        seed=1,
        cycles=9,
        domain_count=3,
        window=12,
        domain_fn=_domain,
        draw_fn=_draw,
    )
    assert controller.choose_domain(1, 0, 3) == 0
    controller.observe_success()
    assert controller.choose_domain(1, 1, 3) == 1
    assert controller.events[-1]["rolling_success_counts"] == [0, 1, 0]


def test_on_off_on_strength_schedule_uses_thirds() -> None:
    spec = EndogenousDemandSpec(
        mode="closed_loop",
        strength=0.5,
        phase_strengths=(0.5, 0.0, 0.5),
    )
    assert spec.strength_for_cycle(0, 72) == 0.5
    assert spec.strength_for_cycle(24, 72) == 0.0
    assert spec.strength_for_cycle(48, 72) == 0.5
