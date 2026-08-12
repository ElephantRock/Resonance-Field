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

    def validate(self, known_sources: set[str]) -> None:
        if self.cohort not in ("instrumentation", "confirmatory"):
            raise ValueError("invalid cohort")
        if len(self.source_ids) < 4:
            raise ValueError("each case requires at least four sources")
        if len(self.producer_source_allocations) < 4:
            raise ValueError("each case requires at least four producers")
        if not set(self.source_ids) <= known_sources:
            raise ValueError("case references unknown sources")
        allocated = {source for _, sources in self.producer_source_allocations for source in sources}
        if not allocated <= set(self.source_ids):
            raise ValueError("producer allocation references sources outside the case")
        if not self.held_out_question_id:
            raise ValueError("held_out_question_id must be non-empty")


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
        for case in self.cases:
            case.validate(source_ids)
            if case.case_id in case_ids:
                raise ValueError("case_id values must be unique")
            case_ids.add(case.case_id)

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
            "cases": [
                {
                    "case_id": case.case_id,
                    "cohort": case.cohort,
                    "source_ids": list(case.source_ids),
                    "producer_source_allocations": [
                        [producer_id, list(source_ids)]
                        for producer_id, source_ids in case.producer_source_allocations
                    ],
                    "held_out_question_id": case.held_out_question_id,
                }
                for case in self.cases
            ],
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
    "SourceManifestEntry",
    "load_corpus_manifest",
    "verify_source_file",
]
