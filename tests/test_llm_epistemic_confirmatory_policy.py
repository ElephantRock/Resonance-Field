from __future__ import annotations

from dataclasses import replace

from resonance.experiments.llm_epistemic_confirmatory_policy import (
    CONFIRMATORY_CHALLENGE_TYPES,
    CONFIRMATORY_DOMAINS,
    load_confirmatory_policy,
    validate_confirmatory_manifest,
    validate_evaluable_confirmatory_cases,
)
from resonance.experiments.llm_epistemic_corpus import (
    CorpusManifest,
    ResearchCaseManifest,
    SemanticAnswerRequirements,
    SourceManifestEntry,
)

POLICY_PATH = "configs/experiments/llm-epistemic-confirmatory-policy-142-145.json"
STALE_TIME = "2016-01-04T21:29:34Z"
CURRENT_TIME = "2026-08-12T17:15:48Z"


def _synthetic_manifest() -> CorpusManifest:
    sources: list[SourceManifestEntry] = []
    cases: list[ResearchCaseManifest] = []
    for domain_index, domain in enumerate(CONFIRMATORY_DOMAINS):
        for challenge_index, challenge in enumerate(CONFIRMATORY_CHALLENGE_TYPES):
            for case_index in range(16):
                stem = f"d{domain_index}-c{challenge_index}-n{case_index:02d}"
                source_ids = tuple(f"{stem}-s{source_index}" for source_index in range(1, 5))
                for source_index, source_id in enumerate(source_ids, start=1):
                    project = f"project-{stem}-{source_index}"
                    if challenge == "temporal_update" and source_index in (1, 2):
                        project = f"project-{stem}-temporal"
                    observed_at = None
                    if challenge == "temporal_update":
                        observed_at = STALE_TIME if source_index == 1 else CURRENT_TIME
                    sources.append(
                        SourceManifestEntry(
                            source_id=source_id,
                            sha256=(f"{(source_index + case_index) % 16:x}" * 64)[:64],
                            media_type="text/plain",
                            title=f"Synthetic {source_id}",
                            acquired_at=CURRENT_TIME,
                            local_path=f"sources/{source_id}.txt",
                            canonical_url=f"https://example.invalid/{source_id}",
                            evidence_observed_at=observed_at,
                            upstream_project_id=project,
                            upstream_organization_id=f"organization-{stem}-{source_index}",
                        )
                    )
                if challenge == "distributed_composition":
                    required = source_ids[:3]
                elif challenge == "temporal_update":
                    required = (source_ids[1], source_ids[2])
                else:
                    required = source_ids[:2]
                minimum_conflict = 1 if challenge == "adjudicated_conflict" else None
                minimum_temporal = 1 if challenge == "temporal_update" else None
                cases.append(
                    ResearchCaseManifest(
                        case_id=f"case-{stem}",
                        cohort="confirmatory",
                        source_ids=source_ids,
                        producer_source_allocations=tuple(
                            (f"producer-{stem}-{source_index}", (source_id,))
                            for source_index, source_id in enumerate(source_ids, start=1)
                        ),
                        held_out_question_id=f"question-{stem}",
                        question="Return the two requested values in order.",
                        accepted_answers=("alpha; beta",),
                        required_source_ids=required,
                        semantic_answer_requirements=SemanticAnswerRequirements(
                            required_slots=(("alpha",), ("beta",)),
                        ),
                        minimum_events_per_producer=1,
                        minimum_conflict_keys=minimum_conflict,
                        minimum_temporal_conflict_keys=minimum_temporal,
                        domain_id=domain,
                        challenge_type=challenge,
                    )
                )
    return CorpusManifest(manifest_version="1.0", sources=tuple(sources), cases=tuple(cases))


def test_frozen_confirmatory_policy_file_loads() -> None:
    policy = load_confirmatory_policy(POLICY_PATH)
    assert policy["confirmatory_case_count"] == 512
    assert policy["minimum_evaluable_case_count"] == 496


def test_balanced_512_case_manifest_passes_policy() -> None:
    manifest = _synthetic_manifest()
    validate_confirmatory_manifest(manifest)
    assert len(manifest.cases) == 512


def test_manifest_rejects_domain_challenge_imbalance() -> None:
    manifest = _synthetic_manifest()
    first = manifest.cases[0]
    replacement = replace(first, domain_id=CONFIRMATORY_DOMAINS[1])
    broken = replace(manifest, cases=(replacement,) + manifest.cases[1:])
    try:
        validate_confirmatory_manifest(broken)
    except ValueError as exc:
        assert "16 cases in every domain/challenge cell" in str(exc)
    else:
        raise AssertionError("unbalanced confirmatory strata were accepted")


def test_manifest_rejects_legacy_unordered_semantic_groups() -> None:
    manifest = _synthetic_manifest()
    first = manifest.cases[0]
    legacy = replace(
        first,
        semantic_answer_requirements=SemanticAnswerRequirements(
            required_groups=(("alpha",), ("beta",)),
        ),
    )
    broken = replace(manifest, cases=(legacy,) + manifest.cases[1:])
    try:
        validate_confirmatory_manifest(broken)
    except ValueError as exc:
        assert "ordered required_slots only" in str(exc)
    else:
        raise AssertionError("legacy unordered confirmatory scoring was accepted")


def test_manifest_rejects_temporal_case_without_exact_conflict_floor() -> None:
    manifest = _synthetic_manifest()
    index = next(
        i for i, case in enumerate(manifest.cases) if case.challenge_type == "temporal_update"
    )
    broken_case = replace(manifest.cases[index], minimum_temporal_conflict_keys=None)
    cases = list(manifest.cases)
    cases[index] = broken_case
    broken = replace(manifest, cases=tuple(cases))
    try:
        validate_confirmatory_manifest(broken)
    except ValueError as exc:
        assert "wrong temporal conflict floor" in str(exc)
    else:
        raise AssertionError("temporal case without collision gate was accepted")


def test_evaluable_policy_accepts_496_with_stratum_coverage() -> None:
    manifest = _synthetic_manifest()
    removed: set[str] = set()
    seen_strata: set[tuple[str | None, str | None]] = set()
    for case in manifest.cases:
        stratum = (case.domain_id, case.challenge_type)
        if stratum not in seen_strata and len(removed) < 16:
            removed.add(case.case_id)
            seen_strata.add(stratum)
    evaluable = {case.case_id for case in manifest.cases} - removed
    status = validate_evaluable_confirmatory_cases(manifest, evaluable)
    assert status.evaluable_case_count == 496
    assert min(count for _domain, _challenge, count in status.stratum_counts) >= 15


def test_evaluable_policy_rejects_concentrated_stratum_attrition() -> None:
    manifest = _synthetic_manifest()
    target = (CONFIRMATORY_DOMAINS[0], CONFIRMATORY_CHALLENGE_TYPES[0])
    target_cases = [
        case.case_id
        for case in manifest.cases
        if (case.domain_id, case.challenge_type) == target
    ]
    removed = set(target_cases[:3])
    for case in manifest.cases:
        if len(removed) == 16:
            break
        if case.case_id not in removed and (case.domain_id, case.challenge_type) != target:
            removed.add(case.case_id)
    evaluable = {case.case_id for case in manifest.cases} - removed
    assert len(evaluable) == 496
    try:
        validate_evaluable_confirmatory_cases(manifest, evaluable)
    except ValueError as exc:
        assert "minimum is 14" in str(exc)
    else:
        raise AssertionError("concentrated stratum attrition was accepted")
