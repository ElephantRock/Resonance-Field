from resonance.experiments.llm_epistemic_corpus import (
    CorpusManifest,
    ResearchCaseManifest,
    SourceManifestEntry,
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
