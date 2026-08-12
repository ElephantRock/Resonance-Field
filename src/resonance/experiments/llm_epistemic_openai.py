"""Optional OpenAI Responses API clients for Experiments 142–145 instrumentation."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from .llm_epistemic_agents import (
    EvaluatorAnswer,
    EvaluatorTask,
    ProducerTask,
    SubstrateRetrievalTool,
)
from .llm_epistemic_events import EpistemicEvent

DEFAULT_INSTRUMENTATION_MODEL = "gpt-5.6-terra"


def build_openai_client() -> Any:
    """Build the optional SDK client without making OpenAI a core dependency."""
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError("install the project with the 'llm' extra to use OpenAI clients") from exc
    return OpenAI()


def _producer_schema(source_ids: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string", "enum": list(source_ids)},
                        "subject": {"type": "string", "minLength": 1},
                        "predicate": {"type": "string", "minLength": 1},
                        "object": {"type": "string", "minLength": 1},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "observed_at": {"type": "string", "minLength": 1},
                        "source_locator": {"type": ["string", "null"]},
                        "uncertainty": {"type": ["string", "null"]},
                    },
                    "required": [
                        "source_id",
                        "subject",
                        "predicate",
                        "object",
                        "confidence",
                        "observed_at",
                        "source_locator",
                        "uncertainty",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["events"],
        "additionalProperties": False,
    }


def _answer_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "cited_event_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["answer", "confidence", "cited_event_ids"],
        "additionalProperties": False,
    }


def _text_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": {
            "type": "json_schema",
            "name": name,
            "strict": True,
            "schema": schema,
        }
    }


def _producer_input(task: ProducerTask) -> str:
    parts = [
        f"Case: {task.case_id}",
        f"Producer: {task.producer_id}",
        "Extract atomic factual claims only from the assigned frozen sources below.",
        "Use concise normalized subject/predicate/object strings.",
        "observed_at must be a timezone-aware ISO-8601 time supported by the source; "
        "if a source gives only a date, use 00:00:00Z for that date.",
        "Do not infer cross-source conclusions. Do not cite a source not assigned to you.",
    ]
    for source in task.sources:
        parts.extend(
            [
                f"\n--- SOURCE {source.source_id} SHA256={source.sha256} ---",
                source.text,
                f"--- END SOURCE {source.source_id} ---",
            ]
        )
    return "\n".join(parts)


@dataclass(slots=True)
class OpenAIProducerClient:
    model: str = DEFAULT_INSTRUMENTATION_MODEL
    reasoning_effort: str = "medium"
    temperature: float = 0.7
    max_output_tokens: int = 12000
    client: Any = None

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = build_openai_client()

    def produce(self, task: ProducerTask) -> tuple[EpistemicEvent, ...]:
        source_ids = tuple(source.source_id for source in task.sources)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("producer task contains duplicate source ids")
        source_hashes = {source.source_id: source.sha256.lower() for source in task.sources}
        response = self.client.responses.create(
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            instructions=(
                "You are an evidence extraction agent in a controlled experiment. "
                "Return only source-grounded atomic observations."
            ),
            input=_producer_input(task),
            text=_text_format("epistemic_events", _producer_schema(source_ids)),
            store=False,
        )
        payload = json.loads(response.output_text)
        raw_events = payload.get("events")
        if not isinstance(raw_events, list):
            raise ValueError("producer response is missing events array")
        events: list[EpistemicEvent] = []
        for index, raw in enumerate(raw_events, start=1):
            if not isinstance(raw, dict):
                raise ValueError("producer event must be an object")
            source_id = str(raw["source_id"])
            source_sha256 = source_hashes.get(source_id)
            if source_sha256 is None:
                raise ValueError("producer response cited an unassigned source")
            event = EpistemicEvent(
                event_id=f"{task.case_id}:{task.producer_id}:{index:04d}",
                case_id=task.case_id,
                producer_id=task.producer_id,
                source_id=source_id,
                source_sha256=source_sha256,
                subject=str(raw["subject"]),
                predicate=str(raw["predicate"]),
                object=str(raw["object"]),
                confidence=float(raw["confidence"]),
                observed_at=str(raw["observed_at"]),
                source_locator=(
                    str(raw["source_locator"]) if raw.get("source_locator") is not None else None
                ),
                uncertainty=(str(raw["uncertainty"]) if raw.get("uncertainty") is not None else None),
                metadata={"provider": "openai", "requested_model": self.model},
            )
            event.validate()
            events.append(event)
        return tuple(events)


@dataclass(slots=True)
class OpenAIEvaluatorClient:
    model: str = DEFAULT_INSTRUMENTATION_MODEL
    reasoning_effort: str = "medium"
    temperature: float = 0.7
    max_output_tokens: int = 6000
    max_tool_rounds: int = 8
    per_call_retrieval_budget: int = 12
    client: Any = None

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = build_openai_client()

    def evaluate(self, task: EvaluatorTask, tool: SubstrateRetrievalTool) -> EvaluatorAnswer:
        function_tool = {
            "type": "function",
            "name": "retrieve_epistemic_events",
            "description": "Retrieve deposited evidence matching an exact subject and predicate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                },
                "required": ["subject", "predicate"],
                "additionalProperties": False,
            },
            "strict": True,
        }
        instructions = (
            "You are a blinded evaluator in a controlled experiment. Answer the held-out question "
            "using only evidence returned by retrieve_epistemic_events. You cannot access the raw "
            "source corpus or producer state. Cite every event materially supporting the answer. "
            "If the deposited evidence is insufficient, return an empty answer with low confidence."
        )
        started = time.perf_counter()
        response = self.client.responses.create(
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            instructions=instructions,
            input=f"Case {task.case_id}; question {task.question_id}: {task.question}",
            tools=[function_tool],
            text=_text_format("evaluator_answer", _answer_schema()),
            store=False,
        )
        operation_cost = 0
        for _round in range(self.max_tool_rounds):
            calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
            if not calls:
                break
            outputs: list[dict[str, str]] = []
            for call in calls:
                if call.name != "retrieve_epistemic_events":
                    raise ValueError(f"unexpected evaluator tool call: {call.name}")
                arguments = json.loads(call.arguments)
                retrieval = tool.retrieve(
                    str(arguments["subject"]),
                    str(arguments["predicate"]),
                    self.per_call_retrieval_budget,
                )
                operation_cost += retrieval.operation_cost
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(
                            {
                                "events": [event.__dict__ for event in retrieval.events],
                                "chosen_event_id": retrieval.chosen_event_id,
                                "operation_cost": retrieval.operation_cost,
                                "complete": retrieval.complete,
                            },
                            sort_keys=True,
                        ),
                    }
                )
            response = self.client.responses.create(
                model=self.model,
                reasoning={"effort": self.reasoning_effort},
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
                instructions=instructions,
                previous_response_id=response.id,
                input=outputs,
                tools=[function_tool],
                text=_text_format("evaluator_answer", _answer_schema()),
                store=False,
            )
        else:
            raise RuntimeError("evaluator exceeded maximum retrieval rounds")

        payload = json.loads(response.output_text)
        latency_ms = round((time.perf_counter() - started) * 1000)
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        return EvaluatorAnswer(
            answer=str(payload["answer"]),
            confidence=float(payload["confidence"]),
            cited_event_ids=tuple(str(item) for item in payload["cited_event_ids"]),
            retrieval_operation_units=operation_cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            model=str(getattr(response, "model", self.model)),
        )


__all__ = [
    "DEFAULT_INSTRUMENTATION_MODEL",
    "OpenAIEvaluatorClient",
    "OpenAIProducerClient",
    "build_openai_client",
]
