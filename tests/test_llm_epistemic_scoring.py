from resonance.experiments.llm_epistemic_agents import EvaluatorAnswer
from resonance.experiments.llm_epistemic_corpus import ResearchCaseManifest
from resonance.experiments.llm_epistemic_events import EpistemicEvent, EpistemicEventLog
from resonance.experiments.llm_epistemic_scoring import normalize_answer, score_case


def _case() -> ResearchCaseManifest:
    return ResearchCaseManifest(
        case_id="case-1",
        cohort="instrumentation",
        source_ids=("source-1", "source-2", "source-3", "source-4"),
        producer_source_allocations=(
            ("producer-1", ("source-1",)),
            ("producer-2", ("source-2",)),
            ("producer-3", ("source-3",)),
            ("producer-4", ("source-4",)),
        ),
        held_out_question_id="question-1",
        question="What component is implied by the evidence?",
        accepted_answers=("Component Y", "component-y"),
        required_source_ids=("source-1", "source-2"),
    )


def _log() -> EpistemicEventLog:
    return EpistemicEventLog(
        schema_version="1.0",
        case_id="case-1",
        events=(
            EpistemicEvent(
                event_id="event-1",
                case_id="case-1",
                producer_id="producer-1",
                source_id="source-1",
                source_sha256="a" * 64,
                subject="a",
                predicate="links_to",
                object="b",
                confidence=0.9,
                observed_at="2026-08-12T00:00:00Z",
            ),
            EpistemicEvent(
                event_id="event-2",
                case_id="case-1",
                producer_id="producer-2",
                source_id="source-2",
                source_sha256="b" * 64,
                subject="b",
                predicate="links_to",
                object="component-y",
                confidence=0.9,
                observed_at="2026-08-12T00:00:00Z",
            ),
        ),
    )


def test_normalization_is_case_and_whitespace_stable() -> None:
    assert normalize_answer("  Component   Y ") == "component y"


def test_correct_answer_with_required_sources_scores_full_evidence() -> None:
    score = score_case(
        _case(),
        EvaluatorAnswer(
            answer="Component Y",
            confidence=0.9,
            cited_event_ids=("event-1", "event-2"),
        ),
        _log(),
    )

    assert score.correct == 1.0
    assert score.evidence_path_f1 == 1.0
    assert score.provenance_precision == 1.0
    assert score.provenance_recall == 1.0
    assert score.unsupported_synthesis == 0.0


def test_nonempty_answer_without_valid_evidence_is_unsupported() -> None:
    score = score_case(
        _case(),
        EvaluatorAnswer(
            answer="Component Y",
            confidence=0.9,
            cited_event_ids=("missing-event",),
        ),
        _log(),
    )

    assert score.correct == 1.0
    assert score.unsupported_synthesis == 1.0
    assert score.invalid_citation_count == 1
