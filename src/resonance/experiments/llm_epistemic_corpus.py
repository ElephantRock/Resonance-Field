"""Frozen corpus manifests and cohort-access guards for Experiments 142–145."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

Cohort = Literal["instrumentation", "confirmatory"]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
        raise ValueError(f"{label} must be a SHA-256 hex digest")


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be an array of strings")
    return tuple(value)


def _string_groups(value: object, label: str) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array of string arrays")
    return tuple(_string_tuple(group, f"{label} group") for group in value)


def _optional_positive_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class SemanticAnswerRequirements:
    """Prospectively frozen deterministic semantic correctness contract."""

    required_groups: tuple[tuple[str, ...], ...]
    forbidden_terms: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.required_groups:
            raise ValueError("semantic answer requirements need at least one required group")
        for group in self.required_groups:
            if not group or any(not term.strip() for term in group):
                raise ValueError("semantic answer requirement groups need non-empty alternatives")
        if any(not term.strip() for term in self.forbidden_terms):
            raise ValueError("semantic forbidden terms must be non-empty")

    def canonical_mapping(self) -> dict[str, object]:
        self.validate()
        return {
            "required_groups": [list(group) for group in self.required_groups],
            "forbidden_terms": list(self.forbidden_terms),
        }


@dataclass(frozen=True, slots=True)
class SourceManifestEntry:
    source_id: str
    sha256: str
    media_type: str
    title: str
    acquired_at: str
    local_path: str | None = None
    canonical_url: str | None = None

    def validate(self) -> None:
        if not self.source_id or not self.title or not self.media_type or not self.acquired_at:
            raise ValueError("source manifest fields must be non-empty")
        _validate_sha256(self.sha256, "source sha256")
        if not self.local_path and not self.canonical_url:
            raise ValueError("source must have a local_path or canonical_url")


@dataclass(frozen=True, slots=True)
class ResearchCaseManifest:
    case_id: str
    cohort: Cohort
    source_ids: tuple[str, ...]
    producer_source_allocations: tuple[tuple[str, tuple[str, ...]], ...]
    held_out_question_id: str
    question: str
    accepted_answers: tuple[str, ...]
    required_source_ids: tuple[str, ...]
    semantic_answer_requirements: SemanticAnswerRequirements | None = None
    minimum_events_per_producer: int | None = None

    def validate(self, known_sources: set[str]) -> None:
        if self.cohort not in ("instrumentation", "confirmatory"):
            raise ValueError("invalid cohort")
        if len(self.source_ids) < 4:
            raise ValueError("each case requires at least four sources")
        if len(self.producer_source_allocations) < 4:
            raise ValueError("each case requires at least four producers")
        source_set = set(self.source_ids)
        if not source_set <= known_sources:
            raise ValueError("case references unknown sources")
        allocated = {source for _, sources in self.producer_source_allocations for source in sources}
        if not allocated <= source_set:
            raise ValueError("producer allocation references sources outside the case")
        if not source_set <= allocated:
            raise ValueError("every case source must be allocated to at least one producer")
        if not self.held_out_question_id or not self.question.strip():
            raise ValueError("held-out question id and text must be non-empty")
        if not self.accepted_answers or any(not answer.strip() for answer in self.accepted_answers):
            raise ValueError("accepted_answers must contain non-empty answers")
        if self.semantic_answer_requirements is not None:
            self.semantic_answer_requirements.validate()
        if self.minimum_events_per_producer is not None:
            if self.minimum_events_per_producer < 1:
                raise ValueError("minimum_events_per_producer must be a positive integer")
            if any(not producer_sources for _, producer_sources in self.producer_source_allocations):
                raise ValueError(
                    "minimum_events_per_producer requires every producer to have assigned sources"
                )
        required = set(self.required_source_ids)
        if len(required) < 2 or not required <= source_set:
            raise ValueError("collective evidence must require at least two case sources")
        for _producer_id, producer_sources in self.producer_source_allocations:
            if required <= set(producer_sources):
                raise ValueError("one producer cannot receive every required evidence source")
        covering_producers = {
            producer_id
            for producer_id, producer_sources in self.producer_source_allocations
            if required & set(producer_sources)
        }
        if len(covering_producers) < 2:
            raise ValueError("required evidence must span at least two producers")

    def canonical_mapping(self) -> dict[str, object]:
        value: dict[str, object] = {
            "case_id": self.case_id,
            "cohort": self.cohort,
            "source_ids": list(self.source_ids),
            "producer_source_allocations": [
                [producer_id, list(source_ids)]
                for producer_id, source_ids in self.producer_source_allocations
            ],
            "held_out_question_id": self.held_out_question_id,
            "question": self.question,
            "accepted_answers": list(self.accepted_answers),
            "required_source_ids": list(self.required_source_ids),
        }
        if self.semantic_answer_requirements is not None:
            value["semantic_answer_requirements"] = (
                self.semantic_answer_requirements.canonical_mapping()
            )
        if self.minimum_events_per_producer is not None:
            value["minimum_events_per_producer"] = self.minimum_events_per_producer
        return value


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    manifest_version: str
    sources: tuple[SourceManifestEntry, ...]
    cases: tuple[ResearchCaseManifest, ...]

    def validate(self) -> None:
        if self.manifest_version != "1.0":
            raise ValueError("unsupported corpus manifest version")
        source_ids: set[str] = set()
        for source in self.sources:
            source.validate()
            if source.source_id in source_ids:
                raise ValueError("source_id values must be unique")
            source_ids.add(source.source_id)
        case_ids: set[str] = set()
        question_ids: set[str] = set()
        for case in self.cases:
            case.validate(source_ids)
            if case.case_id in case_ids:
                raise ValueError("case_id values must be unique")
            if case.held_out_question_id in question_ids:
                raise ValueError("held_out_question_id values must be unique")
            case_ids.add(case.case_id)
            question_ids.add(case.held_out_question_id)

    def canonical_bytes(self) -> bytes:
        self.validate()
        payload = {
            "manifest_version": self.manifest_version,
            "sources": [
                {
                    "source_id": source.source_id,
                    "sha256": source.sha256.lower(),
                    "media_type": source.media_type,
                    "title": source.title,
                    "acquired_at": source.acquired_at,
                    "local_path": source.local_path,
                    "canonical_url": source.canonical_url,
                }
                for source in self.sources
            ],
            "cases": [case.canonical_mapping() for case in self.cases],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_bytes())

    def cases_for_instrumentation(self) -> tuple[ResearchCaseManifest, ...]:
        self.validate()
        selected = tuple(case for case in self.cases if case.cohort == "instrumentation")
        if len(selected) != len(self.cases):
            raise PermissionError("instrumentation manifest contains confirmatory cases")
        return selected


def _parse_semantic_answer_requirements(value: object) -> SemanticAnswerRequirements | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("semantic_answer_requirements must be an object")
    requirements = SemanticAnswerRequirements(
        required_groups=_string_groups(value.get("required_groups"), "semantic required groups"),
        forbidden_terms=_string_tuple(
            value.get("forbidden_terms", []),
            "semantic forbidden terms",
        ),
    )
    requirements.validate()
    return requirements


def load_corpus_manifest(path: str | Path) -> CorpusManifest:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("corpus manifest must be a JSON object")
    raw_sources = value.get("sources")
    raw_cases = value.get("cases")
    if not isinstance(raw_sources, list) or not isinstance(raw_cases, list):
        raise ValueError("corpus manifest sources and cases must be arrays")

    sources: list[SourceManifestEntry] = []
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            raise ValueError("each source manifest entry must be an object")
        sources.append(
            SourceManifestEntry(
                source_id=str(raw_source["source_id"]),
                sha256=str(raw_source["sha256"]),
                media_type=str(raw_source["media_type"]),
                title=str(raw_source["title"]),
                acquired_at=str(raw_source["acquired_at"]),
                local_path=(
                    str(raw_source["local_path"])
                    if raw_source.get("local_path") is not None
                    else None
                ),
                canonical_url=(
                    str(raw_source["canonical_url"])
                    if raw_source.get("canonical_url") is not None
                    else None
                ),
            )
        )

    cases: list[ResearchCaseManifest] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise ValueError("each research case manifest must be an object")
        raw_allocations = raw_case.get("producer_source_allocations")
        if not isinstance(raw_allocations, list):
            raise ValueError("producer_source_allocations must be an array")
        allocations: list[tuple[str, tuple[str, ...]]] = []
        for allocation in raw_allocations:
            if not isinstance(allocation, list) or len(allocation) != 2:
                raise ValueError("each producer allocation must contain producer id and source ids")
            producer_id, source_ids = allocation
            if not isinstance(producer_id, str):
                raise ValueError("producer allocation id must be a string")
            allocations.append(
                (producer_id, _string_tuple(source_ids, "producer allocation source ids"))
            )
        cohort = str(raw_case["cohort"])
        if cohort not in ("instrumentation", "confirmatory"):
            raise ValueError("invalid cohort")
        cases.append(
            ResearchCaseManifest(
                case_id=str(raw_case["case_id"]),
                cohort=cast(Cohort, cohort),
                source_ids=_string_tuple(raw_case["source_ids"], "case source ids"),
                producer_source_allocations=tuple(allocations),
                held_out_question_id=str(raw_case["held_out_question_id"]),
                question=str(raw_case["question"]),
                accepted_answers=_string_tuple(raw_case["accepted_answers"], "accepted answers"),
                required_source_ids=_string_tuple(
                    raw_case["required_source_ids"], "required source ids"
                ),
                semantic_answer_requirements=_parse_semantic_answer_requirements(
                    raw_case.get("semantic_answer_requirements")
                ),
                minimum_events_per_producer=_optional_positive_int(
                    raw_case.get("minimum_events_per_producer"),
                    "minimum_events_per_producer",
                ),
            )
        )

    manifest = CorpusManifest(
        manifest_version=str(value["manifest_version"]),
        sources=tuple(sources),
        cases=tuple(cases),
    )
    manifest.validate()
    return manifest


def verify_source_file(source: SourceManifestEntry, root: str | Path = ".") -> None:
    source.validate()
    if source.local_path is None:
        raise ValueError("source has no local file to verify")
    path = Path(root) / source.local_path
    observed = _sha256_bytes(path.read_bytes())
    if observed != source.sha256.lower():
        raise ValueError(f"source hash mismatch for {source.source_id}")


__all__ = [
    "CorpusManifest",
    "ResearchCaseManifest",
    "SemanticAnswerRequirements",
    "SourceManifestEntry",
    "load_corpus_manifest",
    "verify_source_file",
]
