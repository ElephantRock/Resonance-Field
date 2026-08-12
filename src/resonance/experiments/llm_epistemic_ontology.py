"""Shared substrate-neutral relation ontology for Experiments 142–145."""

from __future__ import annotations

RELATION_ONTOLOGY = (
    "affects",
    "authored_by",
    "compatible_with",
    "default_is",
    "depends_on",
    "enables",
    "fixed_in",
    "has_value",
    "introduced_in",
    "is_a",
    "links_to",
    "located_in",
    "member_of",
    "owned_by",
    "part_of",
    "produces",
    "related_to",
    "released_on",
    "removed_in",
    "required_by",
    "requires",
    "supersedes",
    "supports",
    "uses",
)
RELATION_SET = frozenset(RELATION_ONTOLOGY)


def validate_relation(value: str) -> None:
    if value not in RELATION_SET:
        raise ValueError(f"predicate is outside the frozen relation ontology: {value}")


__all__ = ["RELATION_ONTOLOGY", "RELATION_SET", "validate_relation"]
