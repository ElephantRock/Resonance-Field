"""Frozen corpus manifests and cohort-access guards for Experiments 142–145."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Cohort = Literal["instrumentation", "confirmatory"]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
        raise ValueError(f"{label} must be a SHA-256 hex digest")


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
    "verify_source_file",
]
