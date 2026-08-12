"""Frozen confirmatory construction policy for Experiments 142–145."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .llm_epistemic_corpus import CorpusManifest, ResearchCaseManifest

EXPECTED_DOMAINS = (
    "programming_languages_and_runtimes",
    "build_package_and_dependency_tooling",
    "databases_and_data_systems",
    "distributed_cloud_and_container_systems",
    "networking_protocols_and_internet_standards",
    "operating_systems_and_system_utilities",
    "scientific_computing_and_data_formats",
    "hardware_compilers_and_accelerator_toolchains",
)
EXPECTED_CHALLENGE_TYPES = (
    "distributed_synthesis",
    "non_stale_exact_conflict",
    "temporal_update_conflict",
    "high_load_distractor_synthesis",
)
EXPECTED_CASE_COUNT = 512
EXPECTED_CASES_PER_DOMAIN = 64
EXPECTED_CASES_PER_CHALLENGE = 128
EXPECTED_CASES_PER_CELL = 16
EXPECTED_MINIMUM_EVALUABLE_CASES = 496
EXPECTED_MINIMUM_EVALUABLE_PER_CELL = 15


@dataclass(frozen=True, slots=True)
class ChallengeRule:
    name: str
    cases_per_domain: int
    minimum_sources: int
    maximum_sources: int
    minimum_producers: int
    maximum_producers: int
    minimum_required_sources: int
    maximum_required_sources: int | None
    minimum_required_evidence_producers: int
    minimum_events_per_producer: int
    minimum_conflict_keys: int
    minimum_temporal_conflict_keys: int
    minimum_answer_slots: int
    maximum_answer_slots: int
    maximum_required_evidence_time_span_days: int | None = None
    minimum_conflicting_evidence_time_gap_days: int | None = None
    minimum_nonrequired_sources: int | None = None
    sources_per_producer: int | None = None


@dataclass(frozen=True, slots=True)
class ConfirmatoryDesign:
    domains: tuple[str, ...]
    challenge_rules: tuple[ChallengeRule, ...]
    confirmatory_case_count: int
    cases_per_domain: int
    cases_per_challenge_type: int
    cases_per_cell: int
    minimum_evaluable_cases: int
    minimum_evaluable_per_cell: int
    maximum_cases_per_upstream_project: int
    maximum_cases_per_upstream_organization: int
    maximum_cases_per_exact_source_sha256: int
    minimum_distinct_upstream_projects: int
    minimum_distinct_upstream_organizations: int

    @property
    def challenges(self) -> tuple[str, ...]:
        return tuple(rule.name for rule in self.challenge_rules)

    def rule(self, challenge_type: str) -> ChallengeRule:
        for rule in self.challenge_rules:
            if rule.name == challenge_type:
                return rule
        raise ValueError(f"unknown challenge type {challenge_type!r}")

    def validate(self) -> None:
        if self.domains != EXPECTED_DOMAINS:
            raise ValueError("confirmatory domain grid changed")
        if self.challenges != EXPECTED_CHALLENGE_TYPES:
            raise ValueError("confirmatory challenge grid changed")
        expected_counts = (
            EXPECTED_CASE_COUNT,
            EXPECTED_CASES_PER_DOMAIN,
            EXPECTED_CASES_PER_CHALLENGE,
            EXPECTED_CASES_PER_CELL,
            EXPECTED_MINIMUM_EVALUABLE_CASES,
            EXPECTED_MINIMUM_EVALUABLE_PER_CELL,
        )
        observed_counts = (
            self.confirmatory_case_count,
            self.cases_per_domain,
            self.cases_per_challenge_type,
            self.cases_per_cell,
            self.minimum_evaluable_cases,
            self.minimum_evaluable_per_cell,
        )
        if observed_counts != expected_counts:
            raise ValueError("confirmatory design counts changed")
        if (
            len(self.domains) * len(self.challenge_rules) * self.cases_per_cell
            != self.confirmatory_case_count
        ):
            raise ValueError("domain/challenge grid does not multiply to confirmatory case count")
        if len(self.challenge_rules) * self.cases_per_cell != self.cases_per_domain:
            raise ValueError("cases_per_domain is inconsistent with challenge grid")
        if len(self.domains) * self.cases_per_cell != self.cases_per_challenge_type:
            raise ValueError("cases_per_challenge_type is inconsistent with domain grid")
        if self.minimum_evaluable_cases > self.confirmatory_case_count:
            raise ValueError("minimum evaluable cases exceed sealed cases")
        if self.minimum_evaluable_per_cell > self.cases_per_cell:
            raise ValueError("minimum evaluable cell count exceeds sealed cell count")
        if (
            self.maximum_cases_per_upstream_project,
            self.maximum_cases_per_upstream_organization,
            self.maximum_cases_per_exact_source_sha256,
            self.minimum_distinct_upstream_projects,
            self.minimum_distinct_upstream_organizations,
        ) != (16, 32, 1, 32, 16):
            raise ValueError("source diversity controls changed")
        for rule in self.challenge_rules:
            if rule.cases_per_domain != self.cases_per_cell:
                raise ValueError(f"challenge {rule.name} cell count changed")
            if rule.minimum_producers != 4 or rule.maximum_producers != 4:
                raise ValueError(f"challenge {rule.name} must use exactly four producers")
            if rule.minimum_required_evidence_producers < 3:
                raise ValueError(f"challenge {rule.name} must span at least three evidence producers")
            if rule.minimum_events_per_producer != 1:
                raise ValueError(f"challenge {rule.name} producer-deposit floor changed")


def _positive_int(mapping: dict[str, Any], key: str) -> int:
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value


def _nonnegative_int(mapping: dict[str, Any], key: str) -> int:
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _optional_int(mapping: dict[str, Any], key: str) -> int | None:
    value = mapping.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer when provided")
    return value


def load_confirmatory_design(path: str | Path) -> ConfirmatoryDesign:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("confirmatory design must be a JSON object")
    if value.get("design_version") != "1.0":
        raise ValueError("unsupported confirmatory design version")
    if value.get("campaign") != "llm-epistemic-substrate-142-145-v0.1":
        raise ValueError("confirmatory design campaign changed")
    if value.get("status") != "pre_confirmatory_design_only":
        raise ValueError("confirmatory design status changed before seal")
    if value.get("post_seal_case_replacement_allowed") is not False:
        raise ValueError("post-seal case replacement must remain disabled")
    raw_domains = value.get("domains")
    raw_challenges = value.get("challenge_types")
    source_policy = value.get("source_policy")
    if not isinstance(raw_domains, list) or not all(isinstance(item, str) for item in raw_domains):
        raise ValueError("domains must be a string array")
    if not isinstance(raw_challenges, dict) or not isinstance(source_policy, dict):
        raise ValueError("challenge_types and source_policy must be objects")

    rules: list[ChallengeRule] = []
    for name, raw in raw_challenges.items():
        if not isinstance(raw, dict):
            raise ValueError(f"challenge rule {name} must be an object")
        rules.append(
            ChallengeRule(
                name=str(name),
                cases_per_domain=_positive_int(raw, "cases_per_domain"),
                minimum_sources=_positive_int(raw, "minimum_sources"),
                maximum_sources=_positive_int(raw, "maximum_sources"),
                minimum_producers=_positive_int(raw, "minimum_producers"),
                maximum_producers=_positive_int(raw, "maximum_producers"),
                minimum_required_sources=_positive_int(raw, "minimum_required_sources"),
                maximum_required_sources=_optional_int(raw, "maximum_required_sources"),
                minimum_required_evidence_producers=_positive_int(
                    raw, "minimum_required_evidence_producers"
                ),
                minimum_events_per_producer=_positive_int(raw, "minimum_events_per_producer"),
                minimum_conflict_keys=_nonnegative_int(raw, "minimum_conflict_keys"),
                minimum_temporal_conflict_keys=_nonnegative_int(
                    raw, "minimum_temporal_conflict_keys"
                ),
                minimum_answer_slots=_positive_int(raw, "minimum_answer_slots"),
                maximum_answer_slots=_positive_int(raw, "maximum_answer_slots"),
                maximum_required_evidence_time_span_days=_optional_int(
                    raw, "maximum_required_evidence_time_span_days"
                ),
                minimum_conflicting_evidence_time_gap_days=_optional_int(
                    raw, "minimum_conflicting_evidence_time_gap_days"
                ),
                minimum_nonrequired_sources=_optional_int(raw, "minimum_nonrequired_sources"),
                sources_per_producer=_optional_int(raw, "sources_per_producer"),
            )
        )

    design = ConfirmatoryDesign(
        domains=tuple(raw_domains),
        challenge_rules=tuple(rules),
        confirmatory_case_count=_positive_int(value, "confirmatory_case_count"),
        cases_per_domain=_positive_int(value, "cases_per_domain"),
        cases_per_challenge_type=_positive_int(value, "cases_per_challenge_type"),
        cases_per_cell=_positive_int(value, "cases_per_domain_challenge_cell"),
        minimum_evaluable_cases=_positive_int(value, "minimum_evaluable_confirmatory_cases"),
        minimum_evaluable_per_cell=_positive_int(
            value, "minimum_evaluable_cases_per_domain_challenge_cell"
        ),
        maximum_cases_per_upstream_project=_positive_int(
            source_policy, "maximum_cases_per_upstream_project"
        ),
        maximum_cases_per_upstream_organization=_positive_int(
            source_policy, "maximum_cases_per_upstream_organization"
        ),
        maximum_cases_per_exact_source_sha256=_positive_int(
            source_policy, "maximum_cases_per_exact_source_sha256"
        ),
        minimum_distinct_upstream_projects=_positive_int(
            source_policy, "minimum_distinct_upstream_projects"
        ),
        minimum_distinct_upstream_organizations=_positive_int(
            source_policy, "minimum_distinct_upstream_organizations"
        ),
    )
    design.validate()
    return design


def _parse_time(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("evidence timestamps must be timezone-aware")
    return parsed


def _required_evidence_producer_count(case: ResearchCaseManifest) -> int:
    required = set(case.required_source_ids)
    return sum(
        1
        for _producer_id, source_ids in case.producer_source_allocations
        if required.intersection(source_ids)
    )


def _validate_case_against_rule(
    case: ResearchCaseManifest,
    rule: ChallengeRule,
    source_by_id: dict[str, Any],
) -> None:
    source_count = len(case.source_ids)
    producer_count = len(case.producer_source_allocations)
    required_count = len(case.required_source_ids)
    if not rule.minimum_sources <= source_count <= rule.maximum_sources:
        raise ValueError(f"case {case.case_id} source count violates {rule.name}")
    if not rule.minimum_producers <= producer_count <= rule.maximum_producers:
        raise ValueError(f"case {case.case_id} producer count violates {rule.name}")
    if required_count < rule.minimum_required_sources:
        raise ValueError(f"case {case.case_id} has too few required sources")
    if rule.maximum_required_sources is not None and required_count > rule.maximum_required_sources:
        raise ValueError(f"case {case.case_id} has too many required sources")
    if _required_evidence_producer_count(case) < rule.minimum_required_evidence_producers:
        raise ValueError(f"case {case.case_id} required evidence spans too few producers")
    if case.minimum_events_per_producer != rule.minimum_events_per_producer:
        raise ValueError(f"case {case.case_id} producer-deposit floor differs from design")

    expected_conflict = None if rule.minimum_conflict_keys == 0 else rule.minimum_conflict_keys
    expected_temporal = (
        None if rule.minimum_temporal_conflict_keys == 0 else rule.minimum_temporal_conflict_keys
    )
    if case.minimum_conflict_keys != expected_conflict:
        raise ValueError(f"case {case.case_id} conflict floor differs from design")
    if case.minimum_temporal_conflict_keys != expected_temporal:
        raise ValueError(f"case {case.case_id} temporal conflict floor differs from design")

    requirements = case.semantic_answer_requirements
    if requirements is None or not requirements.required_slots:
        raise ValueError(f"case {case.case_id} must use ordered required_slots")
    slot_count = len(requirements.required_slots)
    if not rule.minimum_answer_slots <= slot_count <= rule.maximum_answer_slots:
        raise ValueError(f"case {case.case_id} answer-slot count violates design")

    if rule.minimum_nonrequired_sources is not None:
        nonrequired = source_count - required_count
        if nonrequired < rule.minimum_nonrequired_sources:
            raise ValueError(f"case {case.case_id} has too few nonrequired sources")
    if rule.sources_per_producer is not None:
        if any(
            len(source_ids) != rule.sources_per_producer
            for _producer_id, source_ids in case.producer_source_allocations
        ):
            raise ValueError(f"case {case.case_id} source allocation violates fixed load")

    required_times = [
        _parse_time(source_by_id[source_id].controlled_evidence_time)
        for source_id in case.required_source_ids
    ]
    required_span_days = (max(required_times) - min(required_times)).total_seconds() / 86400.0
    if (
        rule.maximum_required_evidence_time_span_days is not None
        and required_span_days > rule.maximum_required_evidence_time_span_days
    ):
        raise ValueError(f"case {case.case_id} required evidence is too temporally dispersed")
    if (
        rule.minimum_conflicting_evidence_time_gap_days is not None
        and required_span_days < rule.minimum_conflicting_evidence_time_gap_days
    ):
        raise ValueError(f"case {case.case_id} lacks the required stale/current time gap")


def validate_confirmatory_manifest_against_design(
    manifest: CorpusManifest,
    design: ConfirmatoryDesign,
) -> None:
    """Reject a confirmatory manifest that violates the frozen 512-case design."""

    design.validate()
    manifest.validate()
    if len(manifest.cases) != design.confirmatory_case_count:
        raise ValueError("confirmatory manifest case count does not match frozen design")
    if any(case.cohort != "confirmatory" for case in manifest.cases):
        raise ValueError("confirmatory design validator accepts confirmatory cases only")

    source_by_id = {source.source_id: source for source in manifest.sources}
    cell_counts: Counter[tuple[str, str]] = Counter()
    project_cases: Counter[str] = Counter()
    organization_cases: Counter[str] = Counter()
    sha_cases: Counter[str] = Counter()

    for case in manifest.cases:
        if case.domain_id not in design.domains:
            raise ValueError(f"case {case.case_id} has invalid or missing domain_id")
        if case.challenge_type not in design.challenges:
            raise ValueError(f"case {case.case_id} has invalid or missing challenge_type")
        domain_id = str(case.domain_id)
        challenge_type = str(case.challenge_type)
        cell_counts[(domain_id, challenge_type)] += 1
        _validate_case_against_rule(
            case,
            design.rule(challenge_type),
            source_by_id,
        )

        case_projects: set[str] = set()
        case_organizations: set[str] = set()
        for source_id in case.source_ids:
            source = source_by_id[source_id]
            if source.evidence_observed_at is None:
                raise ValueError(f"source {source_id} lacks explicit evidence_observed_at")
            if source.upstream_project_id is None or source.upstream_organization_id is None:
                raise ValueError(f"source {source_id} lacks upstream diversity metadata")
            case_projects.add(source.upstream_project_id)
            case_organizations.add(source.upstream_organization_id)
            sha_cases[source.sha256.lower()] += 1
        for project_id in case_projects:
            project_cases[project_id] += 1
        for organization_id in case_organizations:
            organization_cases[organization_id] += 1

    expected_cells = {
        (domain, challenge): design.cases_per_cell
        for domain in design.domains
        for challenge in design.challenges
    }
    if dict(cell_counts) != expected_cells:
        raise ValueError("confirmatory manifest is not exactly balanced across all 32 cells")
    if max(project_cases.values(), default=0) > design.maximum_cases_per_upstream_project:
        raise ValueError("upstream project case cap exceeded")
    if max(organization_cases.values(), default=0) > design.maximum_cases_per_upstream_organization:
        raise ValueError("upstream organization case cap exceeded")
    if max(sha_cases.values(), default=0) > design.maximum_cases_per_exact_source_sha256:
        raise ValueError("exact frozen source bytes are reused across confirmatory cases")
    if len(project_cases) < design.minimum_distinct_upstream_projects:
        raise ValueError("too few distinct upstream projects")
    if len(organization_cases) < design.minimum_distinct_upstream_organizations:
        raise ValueError("too few distinct upstream organizations")


__all__ = [
    "EXPECTED_CHALLENGE_TYPES",
    "EXPECTED_DOMAINS",
    "ChallengeRule",
    "ConfirmatoryDesign",
    "load_confirmatory_design",
    "validate_confirmatory_manifest_against_design",
]
