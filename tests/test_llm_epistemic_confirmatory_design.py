from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from resonance.experiments.llm_epistemic_confirmatory_design import (
    EXPECTED_CHALLENGE_TYPES,
    EXPECTED_DOMAINS,
    load_confirmatory_design,
    validate_confirmatory_manifest_against_design,
)
from resonance.experiments.llm_epistemic_corpus import (
    CorpusManifest,
    ResearchCaseManifest,
    SemanticAnswerRequirements,
    SourceManifestEntry,
)

DESIGN_PATH = Path(
    "configs/experiments/llm-epistemic-substrate-142-145-confirmatory-design.json"
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _synthetic_manifest() -> CorpusManifest:
    sources: list[SourceManifestEntry] = []
    cases: list[ResearchCaseManifest] = []
    for domain_index, domain in enumerate(EXPECTED_DOMAINS):
        for challenge_index, challenge in enumerate(EXPECTED_CHALLENGE_TYPES):
            project_id = f"project-{domain_index:02d}-{challenge_index:02d}"
            organization_id = f"organization-{(domain_index * 4 + challenge_index) // 2:02d}"
            source_count = 8 if challenge == "high_load_distractor_synthesis" else 4
            for case_index in range(16):
                case_id = f"case-{domain_index:02d}-{challenge_index:02d}-{case_index:02d}"
                source_ids: list[str] = []
                for source_index in range(source_count):
                    source_id = f"{case_id}-source-{source_index}"
                    source_ids.append(source_id)
                    observed_at = "2026-01-01T00:00:00Z"
                    if challenge == "temporal_update_conflict" and source_index == 0:
                        observed_at = "2025-01-01T00:00:00Z"
                    sources.append(
                        SourceManifestEntry(
                            source_id=source_id,
                            sha256=_sha(source_id),
                            media_type="text/plain",
                            title=source_id,
                            acquired_at="2026-08-12T00:00:00Z",
                            canonical_url=f"https://example.invalid/{source_id}",
                            evidence_observed_at=observed_at,
                            upstream_project_id=project_id,
                            upstream_organization_id=organization_id,
                        )
                    )

                if source_count == 8:
                    allocations = tuple(
                        (
                            f"producer-{producer_index}",
                            tuple(source_ids[producer_index * 2 : producer_index * 2 + 2]),
                        )
                        for producer_index in range(4)
                    )
                    required_source_ids = (source_ids[0], source_ids[2], source_ids[4])
                else:
                    allocations = tuple(
                        (f"producer-{producer_index}", (source_ids[producer_index],))
                        for producer_index in range(4)
                    )
                    required_source_ids = tuple(source_ids[:3])

                minimum_conflict_keys = None
                minimum_temporal_conflict_keys = None
                if challenge == "non_stale_exact_conflict":
                    minimum_conflict_keys = 1
                elif challenge == "temporal_update_conflict":
                    minimum_conflict_keys = 1
                    minimum_temporal_conflict_keys = 1

                cases.append(
                    ResearchCaseManifest(
                        case_id=case_id,
                        cohort="confirmatory",
                        source_ids=tuple(source_ids),
                        producer_source_allocations=allocations,
                        held_out_question_id=f"question-{case_id}",
                        question="Synthetic pre-seal design validator question.",
                        accepted_answers=("alpha; beta",),
                        required_source_ids=required_source_ids,
                        semantic_answer_requirements=SemanticAnswerRequirements(
                            required_slots=(("alpha",), ("beta",)),
                        ),
                        minimum_events_per_producer=1,
                        minimum_conflict_keys=minimum_conflict_keys,
                        minimum_temporal_conflict_keys=minimum_temporal_conflict_keys,
                        domain_id=domain,
                        challenge_type=challenge,
                    )
                )
    return CorpusManifest(
        manifest_version="1.0",
        sources=tuple(sources),
        cases=tuple(cases),
    )


def test_confirmatory_design_config_is_exactly_balanced() -> None:
    design = load_confirmatory_design(DESIGN_PATH)
    assert design.confirmatory_case_count == 512
    assert design.cases_per_cell == 16
    assert design.minimum_evaluable_cases == 496
    assert design.minimum_evaluable_per_cell == 15
    assert design.domains == EXPECTED_DOMAINS
    assert design.challenges == EXPECTED_CHALLENGE_TYPES


def test_synthetic_512_case_manifest_satisfies_frozen_design() -> None:
    design = load_confirmatory_design(DESIGN_PATH)
    manifest = _synthetic_manifest()

    validate_confirmatory_manifest_against_design(manifest, design)

    assert len(manifest.cases) == 512
    assert len(manifest.sources) == 2560


def test_cell_imbalance_is_rejected() -> None:
    design = load_confirmatory_design(DESIGN_PATH)
    manifest = _synthetic_manifest()
    first = manifest.cases[0]
    altered = replace(first, domain_id=EXPECTED_DOMAINS[1])
    broken = replace(manifest, cases=(altered,) + manifest.cases[1:])

    with pytest.raises(ValueError, match="not exactly balanced"):
        validate_confirmatory_manifest_against_design(broken, design)


def test_source_reuse_across_cases_is_rejected() -> None:
    design = load_confirmatory_design(DESIGN_PATH)
    manifest = _synthetic_manifest()
    first, second = manifest.cases[:2]
    reused_source = first.source_ids[0]
    second_source_ids = (reused_source,) + second.source_ids[1:]
    allocations = (
        ("producer-0", (second_source_ids[0],)),
        ("producer-1", (second_source_ids[1],)),
        ("producer-2", (second_source_ids[2],)),
        ("producer-3", (second_source_ids[3],)),
    )
    altered_second = replace(
        second,
        source_ids=second_source_ids,
        producer_source_allocations=allocations,
        required_source_ids=tuple(second_source_ids[:3]),
    )
    broken = replace(manifest, cases=(first, altered_second) + manifest.cases[2:])

    with pytest.raises(ValueError, match="source bytes are reused"):
        validate_confirmatory_manifest_against_design(broken, design)


def test_temporal_cell_requires_curated_180_day_required_evidence_gap() -> None:
    design = load_confirmatory_design(DESIGN_PATH)
    manifest = _synthetic_manifest()
    temporal_index = next(
        index
        for index, case in enumerate(manifest.cases)
        if case.challenge_type == "temporal_update_conflict"
    )
    case = manifest.cases[temporal_index]
    altered_sources = tuple(
        replace(source, evidence_observed_at="2026-01-01T00:00:00Z")
        if source.source_id in case.required_source_ids
        else source
        for source in manifest.sources
    )
    broken = replace(manifest, sources=altered_sources)

    with pytest.raises(ValueError, match="lacks the required stale/current time gap"):
        validate_confirmatory_manifest_against_design(broken, design)
