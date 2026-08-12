import hashlib
import json
from dataclasses import replace
from pathlib import Path

from resonance.experiments.llm_epistemic_corpus import (
    CorpusManifest,
    ResearchCaseManifest,
    SourceManifestEntry,
    load_corpus_manifest,
    verify_source_file,
)


def _source(index: int) -> SourceManifestEntry:
    return SourceManifestEntry(
        source_id=f"source-{index}",
        sha256=(f"{index:x}" * 64)[:64],
        media_type="text/plain",
        title=f"Source {index}",
        acquired_at="2026-08-12T12:00:00Z",
        canonical_url=f"https://example.invalid/source-{index}",
    )


def _case(cohort: str) -> ResearchCaseManifest:
    return ResearchCaseManifest(
        case_id=f"case-{cohort}",
        cohort=cohort,
        source_ids=("source-1", "source-2", "source-3", "source-4"),
        producer_source_allocations=(
            ("producer-1", ("source-1",)),
            ("producer-2", ("source-2",)),
            ("producer-3", ("source-3",)),
            ("producer-4", ("source-4",)),
        ),
        held_out_question_id="question-1",
        question="Which component follows from the distributed evidence?",
        accepted_answers=("component-y",),
        required_source_ids=("source-1", "source-2"),
    )


def test_instrumentation_manifest_is_hashable() -> None:
    manifest = CorpusManifest(
        manifest_version="1.0",
        sources=tuple(_source(index) for index in range(1, 5)),
        cases=(_case("instrumentation"),),
    )
    assert len(manifest.sha256()) == 64
    assert len(manifest.cases_for_instrumentation()) == 1


def test_instrumentation_guard_rejects_confirmatory_case() -> None:
    manifest = CorpusManifest(
        manifest_version="1.0",
        sources=tuple(_source(index) for index in range(1, 5)),
        cases=(_case("confirmatory"),),
    )
    try:
        manifest.cases_for_instrumentation()
    except PermissionError as exc:
        assert "confirmatory" in str(exc)
    else:
        raise AssertionError("confirmatory case passed instrumentation guard")


def test_case_rejects_single_producer_with_all_required_evidence() -> None:
    case = ResearchCaseManifest(
        case_id="case-invalid",
        cohort="instrumentation",
        source_ids=("source-1", "source-2", "source-3", "source-4"),
        producer_source_allocations=(
            ("producer-1", ("source-1", "source-2")),
            ("producer-2", ("source-3",)),
            ("producer-3", ("source-4",)),
            ("producer-4", ()),
        ),
        held_out_question_id="question-invalid",
        question="What is the answer?",
        accepted_answers=("answer",),
        required_source_ids=("source-1", "source-2"),
    )
    try:
        case.validate({"source-1", "source-2", "source-3", "source-4"})
    except ValueError as exc:
        assert "one producer" in str(exc)
    else:
        raise AssertionError("single-producer complete evidence was accepted")


def test_manifest_round_trip_loader_preserves_canonical_hash(tmp_path: Path) -> None:
    manifest = CorpusManifest(
        manifest_version="1.0",
        sources=tuple(_source(index) for index in range(1, 5)),
        cases=(_case("instrumentation"),),
    )
    path = tmp_path / "manifest.json"
    path.write_text(manifest.canonical_bytes().decode())

    loaded = load_corpus_manifest(path)

    assert loaded.sha256() == manifest.sha256()
    assert loaded.cases_for_instrumentation() == manifest.cases_for_instrumentation()


def test_producer_deposit_floor_is_prospective_and_round_trips(tmp_path: Path) -> None:
    legacy = _case("instrumentation")
    assert "minimum_events_per_producer" not in legacy.canonical_mapping()

    guarded = replace(legacy, minimum_events_per_producer=1)
    manifest = CorpusManifest(
        manifest_version="1.0",
        sources=tuple(_source(index) for index in range(1, 5)),
        cases=(guarded,),
    )
    path = tmp_path / "guarded.json"
    path.write_text(manifest.canonical_bytes().decode())

    loaded = load_corpus_manifest(path)

    assert loaded.cases[0].minimum_events_per_producer == 1
    assert loaded.sha256() == manifest.sha256()


def test_verify_source_file_checks_content_hash(tmp_path: Path) -> None:
    content = b"frozen source content\n"
    source_path = tmp_path / "source.txt"
    source_path.write_bytes(content)
    source = SourceManifestEntry(
        source_id="source-local",
        sha256=hashlib.sha256(content).hexdigest(),
        media_type="text/plain",
        title="Local source",
        acquired_at="2026-08-12T12:00:00Z",
        local_path="source.txt",
    )

    verify_source_file(source, tmp_path)


def test_loader_rejects_invalid_cohort(tmp_path: Path) -> None:
    value = {
        "manifest_version": "1.0",
        "sources": [
            {
                "source_id": f"source-{index}",
                "sha256": (f"{index:x}" * 64)[:64],
                "media_type": "text/plain",
                "title": f"Source {index}",
                "acquired_at": "2026-08-12T12:00:00Z",
                "canonical_url": f"https://example.invalid/source-{index}",
                "local_path": None,
            }
            for index in range(1, 5)
        ],
        "cases": [
            {
                "case_id": "case-invalid",
                "cohort": "unknown",
                "source_ids": ["source-1", "source-2", "source-3", "source-4"],
                "producer_source_allocations": [
                    ["producer-1", ["source-1"]],
                    ["producer-2", ["source-2"]],
                    ["producer-3", ["source-3"]],
                    ["producer-4", ["source-4"]],
                ],
                "held_out_question_id": "question-1",
                "question": "What is the answer?",
                "accepted_answers": ["answer"],
                "required_source_ids": ["source-1", "source-2"],
            }
        ],
    }
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(value))

    try:
        load_corpus_manifest(path)
    except ValueError as exc:
        assert "invalid cohort" in str(exc)
    else:
        raise AssertionError("invalid cohort was accepted")
