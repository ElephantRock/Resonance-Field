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
from resonance.experiments.llm_epistemic_openai import (
    OpenAIEvaluatorClient,
    OpenAIProducerClient,
)
from resonance.experiments.llm_epistemic_replay import make_replayed_substrate, replay_event_log

PARENT_CONFIG = Path("configs/experiments/epistemic-substrate-138-141.json")
OBSERVED_AT = "2026-08-12T00:00:00Z"


class FakeResponses:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.responses = FakeResponses(responses)


def _response(
    response_id: str,
    output_text: str,
    output: list[object] | None = None,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=response_id,
        model="gpt-5.6-terra",
        output_text=output_text,
        output=output or [],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def test_openai_producer_canonicalizes_source_hash_event_id_and_time() -> None:
    payload = {
        "events": [
            {
                "source_id": "source-a",
                "subject": "supplier-x",
                "predicate": "produces",
                "object": "component-y",
                "confidence": 0.9,
                "source_locator": "section 2",
                "uncertainty": None,
            }
        ]
    }
    fake = FakeClient([_response("response-1", json.dumps(payload))])
    client = OpenAIProducerClient(client=fake)
    task = ProducerTask(
        case_id="case-1",
        producer_id="producer-a",
        sources=(
            FrozenSource(
                "source-a",
                "a" * 64,
                "Supplier X produces component Y.",
                OBSERVED_AT,
            ),
        ),
    )

    events = client.produce(task)

    assert events[0].event_id == "case-1:producer-a:0001"
    assert events[0].source_sha256 == "a" * 64
    assert events[0].observed_at == OBSERVED_AT
    assert fake.responses.calls[0]["store"] is False


def test_openai_evaluator_runs_bounded_retrieval_loop_and_accounts_usage() -> None:
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
                subject="supplier-x",
                predicate="produces",
                object="component-y",
                confidence=0.9,
                observed_at=OBSERVED_AT,
            ),
        ),
    )
    evidence = replay_event_log(log, config)
    substrate = make_replayed_substrate("provenance_graph", evidence, config)
    tool = SubstrateRetrievalTool(log, evidence, substrate)
    function_call = SimpleNamespace(
        type="function_call",
        name="retrieve_epistemic_events",
        call_id="call-1",
        arguments=json.dumps({"subject": "supplier-x", "predicate": "produces"}),
    )
    final_payload = {
        "answer": "component-y",
        "confidence": 0.95,
        "cited_event_ids": ["event-1"],
    }
    fake = FakeClient(
        [
            _response("response-1", "", [function_call], input_tokens=10, output_tokens=3),
            _response(
                "response-2",
                json.dumps(final_payload),
                input_tokens=8,
                output_tokens=4,
            ),
        ]
    )
    client = OpenAIEvaluatorClient(client=fake)

    answer = client.evaluate(
        EvaluatorTask(
            case_id="case-1",
            question_id="question-1",
            question="What does supplier-x produce?",
            draw_id=1,
        ),
        tool,
    )

    assert answer.answer == "component-y"
    assert answer.cited_event_ids == ("event-1",)
    assert answer.retrieval_operation_units == 1
    assert (answer.input_tokens, answer.output_tokens) == (18, 7)
    assert fake.responses.calls[1]["previous_response_id"] == "response-1"
