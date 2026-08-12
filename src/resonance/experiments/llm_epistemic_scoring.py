"""Blinded deterministic scoring for Experiments 142–145."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .llm_epistemic_agents import EvaluatorAnswer
from .llm_epistemic_corpus import ResearchCaseManifest
from .llm_epistemic_events import EpistemicEventLog

_WHITESPACE = re.compile(r"\s+")


def normalize_answer(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return _WHITESPACE.sub(" ", normalized)


@dataclass(frozen=True, slots=True)
class CaseScore:
    correct: float
    evidence_path_f1: float
    provenance_precision: float
    provenance_recall: float
    unsupported_synthesis: float
    calibration_brier: float
    valid_citation_count: int
    invalid_citation_count: int


def score_case(
    case: ResearchCaseManifest,
    answer: EvaluatorAnswer,
    event_log: EpistemicEventLog,
) -> CaseScore:
    event_log.validate()
    accepted = {normalize_answer(value) for value in case.accepted_answers}
    observed = normalize_answer(answer.answer)
    correct = float(observed in accepted)

    events = {event.event_id: event for event in event_log.events}
    cited_ids = tuple(dict.fromkeys(answer.cited_event_ids))
    valid_ids = tuple(event_id for event_id in cited_ids if event_id in events)
    invalid_count = len(cited_ids) - len(valid_ids)
    cited_sources = {events[event_id].source_id for event_id in valid_ids}
    required_sources = set(case.required_source_ids)
    supporting_sources = cited_sources & required_sources

    precision = len(supporting_sources) / len(cited_sources) if cited_sources else 0.0
    recall = len(supporting_sources) / len(required_sources) if required_sources else 0.0
    if precision + recall:
        evidence_f1 = 2 * precision * recall / (precision + recall)
    else:
        evidence_f1 = 0.0
    unsupported = float(bool(observed) and (not valid_ids or recall == 0.0))
    brier = (answer.confidence - correct) ** 2

    return CaseScore(
        correct=correct,
        evidence_path_f1=evidence_f1,
        provenance_precision=precision,
        provenance_recall=recall,
        unsupported_synthesis=unsupported,
        calibration_brier=brier,
        valid_citation_count=len(valid_ids),
        invalid_citation_count=invalid_count,
    )


__all__ = ["CaseScore", "normalize_answer", "score_case"]
