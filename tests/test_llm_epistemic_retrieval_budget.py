from __future__ import annotations

from pathlib import Path

from resonance.experiments.epistemic_substrate_config import load_epistemic_substrate_config
from resonance.experiments.llm_epistemic_agents import (
    DEFAULT_TOTAL_RETRIEVAL_BUDGET,
    SubstrateRetrievalTool,
)
from resonance.experiments.llm_epistemic_events import EpistemicEvent, EpistemicEventLog
from resonance.experiments.llm_epistemic_replay import make_replayed_substrate, replay_event_log

PARENT_CONFIG = Path("configs/experiments/epistemic-substrate-138-141.json")


def _event(index: int, subject: str) -> EpistemicEvent:
    return EpistemicEvent(
        event_id=f"event-{index:03d}",
        case_id="budget-case",
        producer_id=f"producer-{index % 4}",
        source_id=f"source-{index:03d}",
        source_sha256=f"{index:064x}"[-64:],
        subject=subject,
        predicate="supports",
        object=f"object-{index:03d}",
        confidence=0.9,
        observed_at="2026-08-12T16:05:00Z",
    )


def test_total_retrieval_budget_is_shared_across_calls() -> None:
    config, _ = load_epistemic_substrate_config(PARENT_CONFIG)
    events = tuple(
        _event(index, subject)
        for index, subject in enumerate(
            ["subject-a"] * 10 + ["subject-b"] * 10 + ["subject-c"] * 10,
            start=1,
        )
    )
    log = EpistemicEventLog(schema_version="1.0", case_id="budget-case", events=events)
    evidence = replay_event_log(log, config)
    substrate = make_replayed_substrate("provenance_graph", evidence, config)
    tool = SubstrateRetrievalTool(log, evidence, substrate)

    first = tool.retrieve("subject-a", "supports", 12)
    second = tool.retrieve("subject-b", "supports", 12)
    third = tool.retrieve("subject-c", "supports", 12)
    exhausted = tool.retrieve("subject-c", "supports", 12)

    assert DEFAULT_TOTAL_RETRIEVAL_BUDGET == 24
    assert (first.operation_cost, second.operation_cost, third.operation_cost) == (10, 10, 4)
    assert first.complete is True
    assert second.complete is True
    assert third.complete is False
    assert tool.remaining_budget == 0
    assert exhausted.operation_cost == 0
    assert exhausted.complete is False
