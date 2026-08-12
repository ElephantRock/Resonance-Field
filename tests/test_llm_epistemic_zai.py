from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from resonance.experiments.epistemic_substrate_config import load_epistemic_substrate_config
from resonance.experiments.llm_epistemic_agents import (
    EvaluatorTask,
    FrozenSource,
    ProducerTask,
    SubstrateRetrievalTool,
)
from resonance.experiments.llm_epistemic_events import EpistemicEvent, EpistemicEventLog
from resonance.experiments.llm_epistemic_replay import make_replayed_substrate, replay_event_log
from resonance.experiments.llm_epistemic_zai import ZAIEvaluatorClient, ZAIProducerClient

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


def _completion(
    content: str | None,
    *,
    tool_calls: list[object] | None = None,
    reasoning_content: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> SimpleNamespace:
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls or [],
        reasoning_content=reasoning_content,
    )
    return SimpleNamespace(
        model="glm-5.1",
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


def _producer_task() -> ProducerTask:
    return ProducerTask(
        case_id="case-1",
        producer_id="producer-a",
        research_goal="Find the relevant packaging behavior.",
        sources=(
            FrozenSource(
                "source-a",
                "a" * 64,
                "pip supports the option.",
                "2026-08-04T00:00:00Z",
            ),
        ),
    )


def _producer_payload(confidence: object) -> dict[str, object]:
    return {
        "events": [
            {
                "source_id": "source-a",
                "subject": "pip",
                "predicate": "supports",
                "object": "break-system-packages",
                "confidence": confidence,
                "source_locator": "NEWS",
                "uncertainty": None,
            }
        ]
    }


def _retrieval_tool() -> SubstrateRetrievalTool:
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
                observed_at="2026-08-04T00:00:00Z",
            ),
        ),
    )
    evidence = replay_event_log(log, config)
    substrate = make_replayed_substrate("provenance_graph", evidence, config)
    return SubstrateRetrievalTool(log, evidence, substrate)


def test_zai_producer_uses_source_controlled_timestamp_and_json_mode() -> None:
    fake = FakeClient([_completion(json.dumps(_producer_payload(0.9)))])
    client = ZAIProducerClient(client=fake)

    events = client.produce(_producer_task())

    assert events[0].observed_at == "2026-08-04T00:00:00Z"
    assert events[0].metadata["provider"] == "zai"
    call = fake.chat.completions.calls[0]
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == {
        "thinking": {"type": "enabled", "clear_thinking": False}
    }


def test_zai_producer_retries_non_numeric_confidence_without_coercion() -> None:
    fake = FakeClient(
        [
            _completion(json.dumps(_producer_payload("high"))),
            _completion(json.dumps(_producer_payload(0.84))),
        ]
    )
    client = ZAIProducerClient(client=fake, max_schema_retries=1)

    events = client.produce(_producer_task())

    assert events[0].confidence == 0.84
    assert len(fake.chat.completions.calls) == 2
    retry_prompt = fake.chat.completions.calls[1]["messages"][1]["content"]
    assert "must be a JSON number" in retry_prompt
    assert "previous attempt violated" in retry_prompt.lower()


def test_zai_evaluator_preserves_reasoning_across_tool_round() -> None:
    tool = _retrieval_tool()
    call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="retrieve_epistemic_events",
            arguments=json.dumps({"subject": "pip", "predicate": "supports"}),
        ),
    )
    final = {
        "answer": "break-system-packages",
        "confidence": 0.95,
        "cited_event_ids": ["event-1"],
    }
    fake = FakeClient(
        [
            _completion(
                "",
                tool_calls=[call],
                reasoning_content="reasoning-block-1",
                prompt_tokens=10,
                completion_tokens=3,
            ),
            _completion(
                json.dumps(final),
                reasoning_content="reasoning-block-2",
                prompt_tokens=8,
                completion_tokens=4,
            ),
        ]
    )
    client = ZAIEvaluatorClient(client=fake)

    answer = client.evaluate(
        EvaluatorTask(
            case_id="case-1",
            question_id="question-1",
            question="Which option does pip support?",
            draw_id=1,
        ),
        tool,
    )

    assert answer.answer == "break-system-packages"
    assert answer.cited_event_ids == ("event-1",)
    assert answer.retrieval_operation_units == 1
    assert (answer.input_tokens, answer.output_tokens) == (18, 7)
    second_messages = fake.chat.completions.calls[1]["messages"]
    assert second_messages[2]["reasoning_content"] == "reasoning-block-1"
    assert second_messages[3]["role"] == "tool"


def test_zai_evaluator_retries_non_numeric_final_confidence() -> None:
    tool = _retrieval_tool()
    invalid = {
        "answer": "break-system-packages",
        "confidence": "high",
        "cited_event_ids": ["event-1"],
    }
    valid = {
        "answer": "break-system-packages",
        "confidence": 0.91,
        "cited_event_ids": ["event-1"],
    }
    fake = FakeClient(
        [
            _completion(json.dumps(invalid), prompt_tokens=5, completion_tokens=2),
            _completion(json.dumps(valid), prompt_tokens=6, completion_tokens=3),
        ]
    )
    client = ZAIEvaluatorClient(client=fake, max_schema_retries=1)

    answer = client.evaluate(
        EvaluatorTask(
            case_id="case-1",
            question_id="question-1",
            question="Which option does pip support?",
            draw_id=1,
        ),
        tool,
    )

    assert answer.confidence == 0.91
    assert (answer.input_tokens, answer.output_tokens) == (11, 5)
    retry_messages = fake.chat.completions.calls[1]["messages"]
    assert retry_messages[-1]["role"] == "user"
    assert "must be a JSON number" in retry_messages[-1]["content"]
