from __future__ import annotations

from resonance.substrate import retrieval_score


def test_exploration_bonus_can_break_semantic_tie() -> None:
    common = dict(
        semantic_similarity=0.7,
        energy=0.5,
        quality=0.6,
        context_compatibility=0.5,
        adoption=0.2,
    )

    dense_score = retrieval_score(**common, exploration_bonus=0.0)
    frontier_score = retrieval_score(**common, exploration_bonus=0.8)

    assert frontier_score > dense_score


def test_repetition_penalty_reduces_score() -> None:
    common = dict(
        semantic_similarity=0.8,
        energy=0.8,
        quality=0.8,
        context_compatibility=0.8,
        adoption=0.8,
        exploration_bonus=0.2,
    )

    clean = retrieval_score(**common, repetition_penalty=0.0)
    repeated = retrieval_score(**common, repetition_penalty=1.0)

    assert repeated < clean
