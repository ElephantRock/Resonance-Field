from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from resonance.experiments.epistemic_substrate_config import load_epistemic_substrate_config
from resonance.experiments.llm_epistemic_agents import (
    EvaluatorTask,
    SubstrateRetrievalTool,
)
from resonance.experiments.llm_epistemic_events import EpistemicEvent, EpistemicEventLog
from resonance.experiments.llm_epistemic_replay import make_replayed_substrate, replay_event_log
from resonance.experiments.llm_epistemic_zai_bounded import ZAIBudgetFinalizingEvaluatorClient

PARENT_CONFIG = Path("configs/experiments/epistemic-substrate-138-141.json")


class FakeCompletions:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def _completion(content: str, *, tool_calls: list[object] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        model="glm-5.2",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    tool_calls=tool_calls or [],
                    reasoning_content=None,
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2),
    )


def _tool(*, total_budget: int = 1) -> SubstrateRetrievalTool:
    config, _ = load_epistemic_substrate_config(PARENT_CONFIG)
    log = EpistemicEventLog(
        schema_version="1.0",
        case_id="case-1",
        events=(
            EpistemicEvent(
                event_id="event-1",
                case_id="case-1",
                producer_id="producer-a",
                source_id="source-a",
                source_sha256="a" * 64,
                subject="pip",
                predicate="supports",
                object="break-system-packages",
                confidence=0.9,
                observed_at="2026-08-12T16:05:00Z",
            ),
        ),
    )
    evidence = replay_event_log(log, config)
    substrate = make_replayed_substrate("provenance_graph", evidence, config)
    return SubstrateRetrievalTool(log, evidence, substrate, total_budget=total_budget)


def _retrieval_call() -> SimpleNamespace:
    return SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="retrieve_epistemic_events",
            arguments=json.dumps({"subject": "pip", "predicate": "supports"}),
        ),
    )


def _final_payload() -> dict[str, object]:
    return {
        "answer": "break-system-packages",
        "confidence": 0.9,
        "cited_event_ids": ["event-1"],
    }


def _task() -> EvaluatorTask:
    return EvaluatorTask(
        case_id="case-1",
        question_id="question-1",
        question="Which option does pip support?",
        draw_id=1,
    )


def test_budget_exhaustion_forces_no_more_tools_and_final_json() -> None:
    fake = FakeClient(
        [
            _completion("", tool_calls=[_retrieval_call()]),
            _completion(json.dumps(_final_payload())),
        ]
    )
    client = ZAIBudgetFinalizingEvaluatorClient(client=fake)
    tool = _tool(total_budget=1)

    answer = client.evaluate(_task(), tool)

    assert answer.answer == "break-system-packages"
    assert answer.retrieval_operation_units == 1
    assert tool.remaining_budget == 0
    calls = fake.chat.completions.calls
    assert calls[0]["tool_choice"] == "auto"
    assert calls[1]["tool_choice"] == "none"
    assert "retrieval-operation budget is exhausted" in calls[1]["messages"][-1]["content"]


def test_round_ceiling_forces_final_json_without_spending_remaining_budget() -> None:
    fake = FakeClient(
        [
            _completion("", tool_calls=[_retrieval_call()]),
            _completion(json.dumps(_final_payload())),
        ]
    )
    client = ZAIBudgetFinalizingEvaluatorClient(client=fake, max_tool_rounds=1)
    tool = _tool(total_budget=10)

    answer = client.evaluate(_task(), tool)

    assert answer.answer == "break-system-packages"
    assert answer.retrieval_operation_units == 1
    assert tool.remaining_budget == 9
    calls = fake.chat.completions.calls
    assert calls[0]["tool_choice"] == "auto"
    assert calls[1]["tool_choice"] == "none"
    assert "retrieval-round ceiling is reached" in calls[1]["messages"][-1]["content"]
