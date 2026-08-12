"""Prospectively frozen confirmatory corpus policy for Experiments 142–145."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .llm_epistemic_corpus import CorpusManifest, ResearchCaseManifest, SourceManifestEntry

CONFIRMATORY_DOMAINS = (
    "programming_languages_runtimes",
    "databases_storage",
    "cloud_orchestration",
    "operating_systems_toolchains",
    "networking_protocols",
    "web_platforms_frameworks",
    "data_ml_systems",
    "open_standards_formats",
)
CONFIRMATORY_CHALLENGE_TYPES = (
    "distributed_composition",
    "temporal_update",
    "adjudicated_conflict",
    "independent_confirmation",
)
CONFIRMATORY_CASE_COUNT = 512
MINIMUM_EVALUABLE_CASE_COUNT = 496
CASES_PER_STRATUM = 16
MINIMUM_EVALUABLE_PER_STRATUM = 14
SOURCES_PER_CASE = 4
PRODUCERS_PER_CASE = 4
SOURCES_PER_PRODUCER = 1
MINIMUM_EVENTS_PER_PRODUCER = 1
MINIMUM_SEMANTIC_SLOTS = 2
MAXIMUM_SEMANTIC_SLOTS = 4
MAXIMUM_CASES_PER_PROJECT = 16
MAXIMUM_CASES_PER_ORGANIZATION = 64
REQUIRED_SOURCES_BY_CHALLENGE = {
    "distributed_composition": 3,
    "temporal_update": 2,
    "adjudicated_conflict": 2,
    "independent_confirmation": 2,
}
GATES_BY_CHALLENGE = {
    "distributed_composition": (None, None),
    "temporal_update": (None, 1),
    "adjudicated_conflict": (1, None),
    "independent_confirmation": (None, None),
}


@dataclass(frozen=True, slots=True)
class EvaluableCohortStatus:
    evaluable_case_count: int
    stratum_counts: tuple[tuple[str, str, int], ...]


def _parse_time(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("evidence timestamps must be timezone-aware")
    return parsed


def _source_map(manifest: CorpusManifest) -> dict[str, SourceManifestEntry]:
    return {source.source_id: source for source in manifest.sources}


def _validate_semantic_scoring(case: ResearchCaseManifest) -> None:
    requirements = case.semantic_answer_requirements
    if requirements is None:
        raise ValueError(f"confirmatory case {case.case_id} requires semantic_answer_requirements")
    requirements.validate()
    if requirements.required_groups or not requirements.required_slots:
        raise ValueError(f"confirmatory case {case.case_id} must use ordered required_slots only")
    slot_count = len(requirements.required_slots)
    if not MINIMUM_SEMANTIC_SLOTS <= slot_count <= MAXIMUM_SEMANTIC_SLOTS:
        raise ValueError(
            f"confirmatory case {case.case_id} must contain {MINIMUM_SEMANTIC_SLOTS}-"
            f"{MAXIMUM_SEMANTIC_SLOTS} ordered semantic slots"
        )
    if len(case.accepted_answers) != 1:
        raise ValueError(f"confirmatory case {case.case_id} needs one canonical accepted answer")
    canonical_slots = tuple(part.strip() for part in case.accepted_answers[0].split(";"))
    if len(canonical_slots) != slot_count or any(not value for value in canonical_slots):
        raise ValueError(
            f"confirmatory case {case.case_id} canonical answer must match ordered slot count"
        )


def _validate_case_shape(case: ResearchCaseManifest) -> None:
    if case.cohort != "confirmatory":
        raise ValueError("confirmatory policy may contain only confirmatory cases")
    if case.domain_id not in CONFIRMATORY_DOMAINS:
        raise ValueError(f"case {case.case_id} has invalid confirmatory domain")
    if case.challenge_type not in CONFIRMATORY_CHALLENGE_TYPES:
        raise ValueError(f"case {case.case_id} has invalid confirmatory challenge type")
    if len(case.source_ids) != SOURCES_PER_CASE:
        raise ValueError(f"case {case.case_id} must contain exactly four sources")
    if len(case.producer_source_allocations) != PRODUCERS_PER_CASE:
        raise ValueError(f"case {case.case_id} must contain exactly four producers")
    producer_ids = [producer_id for producer_id, _ in case.producer_source_allocations]
    if len(producer_ids) != len(set(producer_ids)):
        raise ValueError(f"case {case.case_id} producer IDs must be unique")
    allocated: list[str] = []
    for _producer_id, source_ids in case.producer_source_allocations:
        if len(source_ids) != SOURCES_PER_PRODUCER:
            raise ValueError(f"case {case.case_id} requires one source per producer")
        allocated.extend(source_ids)
    if len(allocated) != len(set(allocated)) or set(allocated) != set(case.source_ids):
        raise ValueError(f"case {case.case_id} must allocate each source to exactly one producer")
    if case.minimum_events_per_producer != MINIMUM_EVENTS_PER_PRODUCER:
        raise ValueError(f"case {case.case_id} must require one deposited event per producer")
    expected_required = REQUIRED_SOURCES_BY_CHALLENGE[case.challenge_type]
    if len(set(case.required_source_ids)) != expected_required:
        raise ValueError(
            f"case {case.case_id} challenge {case.challenge_type} requires "
            f"{expected_required} required sources"
        )
    expected_generic, expected_temporal = GATES_BY_CHALLENGE[case.challenge_type]
    if case.minimum_conflict_keys != expected_generic:
        raise ValueError(f"case {case.case_id} has wrong generic conflict floor")
    if case.minimum_temporal_conflict_keys != expected_temporal:
        raise ValueError(f"case {case.case_id} has wrong temporal conflict floor")
    _validate_semantic_scoring(case)


def _validate_source_metadata(source: SourceManifestEntry) -> None:
    if not source.local_path:
        raise ValueError(f"confirmatory source {source.source_id} requires frozen local bytes")
    if not source.canonical_url:
        raise ValueError(f"confirmatory source {source.source_id} requires canonical_url")
    if not source.upstream_project_id:
        raise ValueError(f"confirmatory source {source.source_id} requires upstream_project_id")
    if not source.upstream_organization_id:
        raise ValueError(
            f"confirmatory source {source.source_id} requires upstream_organization_id"
        )


def _validate_challenge_sources(
    case: ResearchCaseManifest,
    sources: dict[str, SourceManifestEntry],
) -> None:
    case_sources = tuple(sources[source_id] for source_id in case.source_ids)
    required_sources = tuple(sources[source_id] for source_id in case.required_source_ids)
    if case.challenge_type == "independent_confirmation":
        projects = {source.upstream_project_id for source in required_sources}
        organizations = {source.upstream_organization_id for source in required_sources}
        if len(projects) < 2 or len(organizations) < 2:
            raise ValueError(
                f"case {case.case_id} independent confirmation requires two projects and organizations"
            )
    if case.challenge_type == "temporal_update":
        if any(source.evidence_observed_at is None for source in case_sources):
            raise ValueError(
                f"case {case.case_id} temporal update requires explicit evidence_observed_at"
            )
        observed = {_parse_time(source.evidence_observed_at or "") for source in case_sources}
        if len(observed) < 2:
            raise ValueError(f"case {case.case_id} temporal update needs multiple evidence times")
        project_times: dict[str, set[datetime]] = {}
        for source in case_sources:
            project = source.upstream_project_id or ""
            project_times.setdefault(project, set()).add(
                _parse_time(source.evidence_observed_at or "")
            )
        if not any(len(times) >= 2 for times in project_times.values()):
            raise ValueError(
                f"case {case.case_id} temporal update needs one upstream project across times"
            )
        latest = max(observed)
        if max(_parse_time(source.evidence_observed_at or "") for source in required_sources) != latest:
            raise ValueError(
                f"case {case.case_id} required evidence must include the latest evidence state"
            )


def validate_confirmatory_manifest(manifest: CorpusManifest) -> None:
    """Fail closed unless a manifest satisfies the frozen 512-case construction policy."""

    manifest.validate()
    if len(manifest.cases) != CONFIRMATORY_CASE_COUNT:
        raise ValueError(f"confirmatory manifest must contain {CONFIRMATORY_CASE_COUNT} cases")
    sources = _source_map(manifest)
    used_source_ids = {source_id for case in manifest.cases for source_id in case.source_ids}
    if used_source_ids != set(sources):
        raise ValueError("confirmatory manifest may not contain unused or missing source entries")
    for source in manifest.sources:
        _validate_source_metadata(source)

    strata: Counter[tuple[str, str]] = Counter()
    project_cases: Counter[str] = Counter()
    organization_cases: Counter[str] = Counter()
    for case in manifest.cases:
        _validate_case_shape(case)
        _validate_challenge_sources(case, sources)
        strata[(case.domain_id or "", case.challenge_type or "")] += 1
        for project in {sources[source_id].upstream_project_id or "" for source_id in case.source_ids}:
            project_cases[project] += 1
        for organization in {
            sources[source_id].upstream_organization_id or "" for source_id in case.source_ids
        }:
            organization_cases[organization] += 1

    expected_strata = {
        (domain, challenge): CASES_PER_STRATUM
        for domain in CONFIRMATORY_DOMAINS
        for challenge in CONFIRMATORY_CHALLENGE_TYPES
    }
    if dict(strata) != expected_strata:
        raise ValueError("confirmatory manifest must contain exactly 16 cases in every domain/challenge cell")
    if any(count > MAXIMUM_CASES_PER_PROJECT for count in project_cases.values()):
        raise ValueError("an upstream project exceeds the frozen 16-case exposure cap")
    if any(count > MAXIMUM_CASES_PER_ORGANIZATION for count in organization_cases.values()):
        raise ValueError("an upstream organization exceeds the frozen 64-case exposure cap")


def validate_evaluable_confirmatory_cases(
    manifest: CorpusManifest,
    evaluable_case_ids: set[str] | frozenset[str],
) -> EvaluableCohortStatus:
    """Validate global and stratum-level arm-independent post-seal attrition floors."""

    validate_confirmatory_manifest(manifest)
    known = {case.case_id for case in manifest.cases}
    evaluable = set(evaluable_case_ids)
    if not evaluable <= known:
        raise ValueError("evaluable case set contains IDs outside the sealed manifest")
    if len(evaluable) < MINIMUM_EVALUABLE_CASE_COUNT:
        raise ValueError("fewer than 496 sealed cases remain evaluable")
    counts: Counter[tuple[str, str]] = Counter()
    for case in manifest.cases:
        if case.case_id in evaluable:
            counts[(case.domain_id or "", case.challenge_type or "")] += 1
    statuses: list[tuple[str, str, int]] = []
    for domain in CONFIRMATORY_DOMAINS:
        for challenge in CONFIRMATORY_CHALLENGE_TYPES:
            count = counts[(domain, challenge)]
            if count < MINIMUM_EVALUABLE_PER_STRATUM:
                raise ValueError(
                    f"stratum {domain}/{challenge} has {count} evaluable cases; minimum is 14"
                )
            statuses.append((domain, challenge, count))
    return EvaluableCohortStatus(
        evaluable_case_count=len(evaluable),
        stratum_counts=tuple(statuses),
    )


def load_confirmatory_policy(path: str | Path) -> dict[str, object]:
    """Load the machine-readable policy and reject drift from frozen constants."""

    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("confirmatory policy must be a JSON object")
    if value.get("policy_version") != "1.0":
        raise ValueError("confirmatory policy version changed")
    if value.get("campaign") != "llm-epistemic-substrate-142-145-v0.1":
        raise ValueError("confirmatory policy campaign changed")
    if tuple(value.get("domains", ())) != CONFIRMATORY_DOMAINS:
        raise ValueError("confirmatory domain strata changed")
    if tuple(value.get("challenge_types", ())) != CONFIRMATORY_CHALLENGE_TYPES:
        raise ValueError("confirmatory challenge strata changed")
    frozen_scalars = {
        "confirmatory_case_count": CONFIRMATORY_CASE_COUNT,
        "minimum_evaluable_case_count": MINIMUM_EVALUABLE_CASE_COUNT,
        "cases_per_domain_challenge_stratum": CASES_PER_STRATUM,
        "minimum_evaluable_cases_per_stratum": MINIMUM_EVALUABLE_PER_STRATUM,
        "sources_per_case": SOURCES_PER_CASE,
        "producers_per_case": PRODUCERS_PER_CASE,
        "sources_per_producer": SOURCES_PER_PRODUCER,
        "minimum_events_per_producer": MINIMUM_EVENTS_PER_PRODUCER,
    }
    for key, expected in frozen_scalars.items():
        if value.get(key) != expected:
            raise ValueError(f"confirmatory policy field {key} changed")
    if value.get("required_sources_by_challenge_type") != REQUIRED_SOURCES_BY_CHALLENGE:
        raise ValueError("required-source challenge policy changed")
    return value


__all__ = [
    "CASES_PER_STRATUM",
    "CONFIRMATORY_CASE_COUNT",
    "CONFIRMATORY_CHALLENGE_TYPES",
    "CONFIRMATORY_DOMAINS",
    "EvaluableCohortStatus",
    "MINIMUM_EVALUABLE_CASE_COUNT",
    "MINIMUM_EVALUABLE_PER_STRATUM",
    "load_confirmatory_policy",
    "validate_confirmatory_manifest",
    "validate_evaluable_confirmatory_cases",
]
