"""Multi-objective substrate retrieval scoring."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievalWeights:
    semantic: float = 0.40
    energy: float = 0.15
    quality: float = 0.15
    context: float = 0.10
    adoption: float = 0.05
    exploration: float = 0.15
    repetition_penalty: float = 0.10


def retrieval_score(
    *,
    semantic_similarity: float,
    energy: float,
    quality: float,
    context_compatibility: float,
    adoption: float,
    exploration_bonus: float,
    repetition_penalty: float = 0.0,
    weights: RetrievalWeights | None = None,
) -> float:
    """Compute a configurable multi-objective trace retrieval score."""
    w = weights or RetrievalWeights()
    return (
        w.semantic * semantic_similarity
        + w.energy * energy
        + w.quality * quality
        + w.context * context_compatibility
        + w.adoption * adoption
        + w.exploration * exploration_bonus
        - w.repetition_penalty * repetition_penalty
    )
