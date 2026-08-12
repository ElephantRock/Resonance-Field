"""Provider-neutral agent boundaries for Experiments 142–145 instrumentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .epistemic_substrate_campaign import Substrate
from .llm_epistemic_events import EpistemicEvent, EpistemicEventLog
from .llm_epistemic_replay import ReplayedEvidence

DEFAULT_TOTAL_RETRIEVAL_BUDGET = 24


@dataclass(frozen=True, slots=True)
class FrozenSource:
    source_id: str
    sha256: str
    text: str
    observed_at: str = "1970-01-01T00:00:00Z"


@dataclass(frozen=True, slots=True)
class ProducerTask:
    case_id: str
    producer_id: str
    sources: tuple[FrozenSource, ...]
    research_goal: str = ""


class ProducerClient(Protocol):
    def produce(self, task: ProducerTask) -> tuple[EpistemicEvent, ...]: ...


def run_producers(tasks: tuple[ProducerTask, ...], client: ProducerClient) -> EpistemicEventLog:
    if not tasks:
        raise ValueError("at least one producer task is required")
    case_ids = {task.case_id for task in tasks}
    if len(case_ids) != 1:
        raise ValueError("producer tasks must belong to one case")
    all_events: list[EpistemicEvent] = []
    for task in tasks:
        allowed = {
            source.source_id: (source.sha256.lower(), source.observed_at)
            for source in task.sources
        }
        events = client.produce(task)
        for event in events:
            event.validate()
            if event.case_id != task.case_id or event.producer_id != task.producer_id:
                raise ValueError("producer emitted an event outside its assigned identity")
            source_control = allowed.get(event.source_id)
            if source_control is None:
                raise ValueError("producer cited an unassigned source")
            expected_hash, expected_time = source_control
            if event.source_sha256.lower() != expected_hash:
                raise ValueError("producer cited a source with the wrong content hash")
            if event.observed_at != expected_time:
                raise ValueError("producer changed the source-controlled evidence timestamp")
        all_events.extend(events)
    ordered = tuple(sorted(all_events, key=lambda event: (event.observed_at, event.event_id)))
    log = EpistemicEventLog(schema_version="1.0", case_id=tasks[0].case_id, events=ordered)
    log.validate()
    return log


@dataclass(frozen=True, slots=True)
class RetrievedEvent:
    event_id: str
    subject: str
    predicate: str
    object: str
    confidence: float
    source_id: str
    source_sha256: str
    producer_id: str
    observed_at: str


@dataclass(frozen=True, slots=True)
class RetrievalToolResult:
    events: tuple[RetrievedEvent, ...]
    chosen_event_id: str | None
    operation_cost: int
    complete: bool


class SubstrateRetrievalTool:
    def __init__(
        self,
        event_log: EpistemicEventLog,
        evidence: ReplayedEvidence,
        substrate: Substrate,
        total_budget: int = DEFAULT_TOTAL_RETRIEVAL_BUDGET,
    ) -> None:
        event_log.validate()
        if event_log.sha256() != evidence.event_log_sha256:
            raise ValueError("retrieval tool event log does not match replayed evidence")
        if total_budget <= 0:
            raise ValueError("total retrieval budget must be positive")
        self._events = {event.event_id: event for event in event_log.events}
        self._subjects = tuple(sorted({event.subject for event in event_log.events}, key=str.casefold))
        self._evidence = evidence
        self._substrate = substrate
        self._total_budget = total_budget
        self._remaining_budget = total_budget

    def retrieve(self, subject: str, predicate: str, budget: int) -> RetrievalToolResult:
        if budget <= 0:
            raise ValueError("per-call retrieval budget must be positive")
        if self._remaining_budget <= 0:
            return RetrievalToolResult((), None, 0, False)
        subject_id = self._evidence.index.entity_to_id.get(subject)
        relation_id = self._evidence.index.relation_to_id.get(predicate)
        if subject_id is None or relation_id is None:
            return RetrievalToolResult((), None, 0, True)
        allowed_budget = min(budget, self._remaining_budget)
        retrieval = self._substrate.retrieve(subject_id, relation_id, allowed_budget)
        if retrieval.cost < 0 or retrieval.cost > allowed_budget:
            raise ValueError("substrate returned an invalid retrieval cost")
        self._remaining_budget -= retrieval.cost
        selected = self._substrate.choose(retrieval.claims) if retrieval.complete else None
        events = tuple(self._event_for_claim(claim.claim_id) for claim in retrieval.claims)
        chosen_event_id = None
        if selected is not None:
            chosen_event_id = self._evidence.index.claim_to_event_id[selected.claim_id]
        return RetrievalToolResult(events, chosen_event_id, retrieval.cost, retrieval.complete)

    def subjects(self) -> tuple[str, ...]:
        """Expose the shared subject vocabulary without revealing factual objects."""
        return self._subjects

    @property
    def remaining_budget(self) -> int:
        return self._remaining_budget

    @property
    def total_budget(self) -> int:
        return self._total_budget

    def _event_for_claim(self, claim_id: int) -> RetrievedEvent:
        event_id = self._evidence.index.claim_to_event_id[claim_id]
        event = self._events[event_id]
        return RetrievedEvent(
            event_id=event.event_id,
            subject=event.subject,
            predicate=event.predicate,
            object=event.object,
            confidence=event.confidence,
            source_id=event.source_id,
            source_sha256=event.source_sha256,
            producer_id=event.producer_id,
            observed_at=event.observed_at,
        )


@dataclass(frozen=True, slots=True)
class EvaluatorTask:
    case_id: str
    question_id: str
    question: str
    draw_id: int


@dataclass(frozen=True, slots=True)
class EvaluatorAnswer:
    answer: str
    confidence: float
    cited_event_ids: tuple[str, ...]
    retrieval_operation_units: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    model: str = "unknown"


class EvaluatorClient(Protocol):
    def evaluate(self, task: EvaluatorTask, tool: SubstrateRetrievalTool) -> EvaluatorAnswer: ...


__all__ = [
    "DEFAULT_TOTAL_RETRIEVAL_BUDGET",
    "EvaluatorAnswer",
    "EvaluatorClient",
    "EvaluatorTask",
    "FrozenSource",
    "ProducerClient",
    "ProducerTask",
    "RetrievedEvent",
    "RetrievalToolResult",
    "SubstrateRetrievalTool",
    "run_producers",
]
