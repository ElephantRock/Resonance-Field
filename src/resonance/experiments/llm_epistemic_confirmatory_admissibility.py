"""Post-seal arm-independent evaluability gates for Experiments 142–145."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Set
from dataclasses import dataclass

from .llm_epistemic_confirmatory_design import ConfirmatoryDesign


@dataclass(frozen=True, slots=True)
class ConfirmatoryEvaluability:
    evaluable_case_count: int
    cell_counts: tuple[tuple[str, str, int], ...]


def validate_evaluable_case_ids(
    case_strata: Mapping[str, tuple[str, str]],
    evaluable_case_ids: Set[str],
    design: ConfirmatoryDesign,
) -> ConfirmatoryEvaluability:
    """Reject global or cell-local attrition beyond the frozen admissibility limits."""

    design.validate()
    expected_ids = set(case_strata)
    if len(expected_ids) != design.confirmatory_case_count:
        raise ValueError("sealed case-stratum mapping does not contain the frozen case count")
    expected_cells = {
        (domain, challenge)
        for domain in design.domains
        for challenge in design.challenges
    }
    if set(case_strata.values()) - expected_cells:
        raise ValueError("sealed case-stratum mapping contains an unknown domain/challenge cell")

    evaluable = set(evaluable_case_ids)
    if not evaluable <= expected_ids:
        raise ValueError("evaluable case set contains IDs outside the sealed manifest")
    if len(evaluable) < design.minimum_evaluable_cases:
        raise ValueError(
            f"only {len(evaluable)} confirmatory cases are evaluable; "
            f"minimum is {design.minimum_evaluable_cases}"
        )

    counts: Counter[tuple[str, str]] = Counter(case_strata[case_id] for case_id in evaluable)
    status: list[tuple[str, str, int]] = []
    for domain in design.domains:
        for challenge in design.challenges:
            count = counts[(domain, challenge)]
            if count < design.minimum_evaluable_per_cell:
                raise ValueError(
                    f"confirmatory cell {domain}/{challenge} has {count} evaluable cases; "
                    f"minimum is {design.minimum_evaluable_per_cell}"
                )
            status.append((domain, challenge, count))
    return ConfirmatoryEvaluability(
        evaluable_case_count=len(evaluable),
        cell_counts=tuple(status),
    )


__all__ = ["ConfirmatoryEvaluability", "validate_evaluable_case_ids"]
