"""Z.AI OpenAI-compatible Chat Completions clients for Experiments 142–145."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

from .llm_epistemic_agents import (
    EvaluatorAnswer,
    EvaluatorTask,
    ProducerTask,
    RetrievedEvent,
    SubstrateRetrievalTool,
)
from .llm_epistemic_events import EpistemicEvent
from .llm_epistemic_ontology import RELATION_ONTOLOGY

DEFAULT_ZAI_MODEL = "glm-5.1"
DEFAULT_ZAI_BASE_URL = "https://api.z.ai/api/coding/paas/v4"


def build_zai_client(*, api_key: str | None = None, base_url: str = DEFAULT_ZAI_BASE_URL) -> Any:
    """Build the Z.AI client through the OpenAI-compatible Chat Completions protocol."""
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError("install the project with the 'llm' extra to use Z.AI clients") from exc
    key = api_key or os.getenv("ZAI_API_KEY")
    if not key:
        raise RuntimeError("ZAI_API_KEY is required to use the Z.AI instrumentation provider")
    return OpenAI(api_key=key, base_url=base_url.rstrip("/") + "/")


def _producer_input(task: ProducerTask) -> str:
    relation_list = ", ".join(RELATION_ONTOLOGY)
    parts = [
        f"Case: {task.case_id}",
        f"Producer: {task.producer_id}",
        f"Research brief: {task.research_goal or 'extract task-relevant evidence'}",
        "Extract up to 48 atomic factual claims only from the assigned frozen sources below.",
        "Use concise normalized entity names and only the frozen predicate vocabulary.",
        f"Allowed predicates: {relation_list}.",
        "Return one JSON object with exactly one key, events. events must be an array.",
        "Each event must contain source_id, subject, predicate, object, confidence, "
        "source_locator, and uncertainty. Use null when locator or uncertainty is absent.",
        "The experiment assigns evidence timestamps separately; do not infer or output timestamps.",
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


def _retrieved_event_mapping(event: RetrievedEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "subject": event.subject,
        "predicate": event.predicate,
        "object": event.object,
        "confidence": event.confidence,
        "source_id": event.source_id,
        "source_sha256": event.source_sha256,
        "producer_id": event.producer_id,
        "observed_at": event.observed_at,
    }


def _usage(completion: Any) -> tuple[int, int]:
    usage = getattr(completion, "usage", None)
    return (
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
    )


def _content(message: Any) -> str:
    content = getattr(message, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Z.AI completion did not contain final JSON content")
    return content


def _assistant_tool_message(message: Any) -> dict[str, Any]:
    tool_calls = getattr(message, "tool_calls", None) or []
    value: dict[str, Any] = {
        "role": "assistant",
        "content": getattr(message, "content", None) or "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in tool_calls
        ],
    }
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning is not None:
        value["reasoning_content"] = reasoning
    return value


def _thinking_body() -> dict[str, object]:
    return {"thinking": {"type": "enabled", "clear_thinking": False}}


@dataclass(slots=True)
class ZAIProducerClient:
    model: str = DEFAULT_ZAI_MODEL
    base_url: str = DEFAULT_ZAI_BASE_URL
    max_output_tokens: int = 12000
    temperature: float = 1.0
    client: Any = None

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = build_zai_client(base_url=self.base_url)

    def produce(self, task: ProducerTask) -> tuple[EpistemicEvent, ...]:
        source_ids = tuple(source.source_id for source in task.sources)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("producer task contains duplicate source ids")
        source_controls = {
            source.source_id: (source.sha256.lower(), source.observed_at)
            for source in task.sources
        }
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an evidence extraction agent in a controlled experiment. "
                        "Return only source-grounded atomic observations as valid JSON."
                    ),
                },
                {"role": "user", "content": _producer_input(task)},
            ],
            response_format={"type": "json_object"},
            temperature=self.temperature,
            max_tokens=self.max_output_tokens,
            extra_body=_thinking_body(),
        )
        payload = json.loads(_content(completion.choices[0].message))
        raw_events = payload.get("events")
        if not isinstance(raw_events, list):
            raise ValueError("producer response is missing events array")
        if len(raw_events) > 48:
            raise ValueError("producer response exceeded the 48-event ceiling")
        events: list[EpistemicEvent] = []
        for index, raw in enumerate(raw_events, start=1):
            if not isinstance(raw, dict):
                raise ValueError("producer event must be an object")
            source_id = str(raw["source_id"])
            source_control = source_controls.get(source_id)
            if source_control is None:
                raise ValueError("producer response cited an unassigned source")
            predicate = str(raw["predicate"])
            if predicate not in RELATION_ONTOLOGY:
                raise ValueError(f"producer predicate is outside the frozen ontology: {predicate}")
            source_sha256, observed_at = source_control
            event = EpistemicEvent(
                event_id=f"{task.case_id}:{task.producer_id}:{index:04d}",
                case_id=task.case_id,
                producer_id=task.producer_id,
                source_id=source_id,
                source_sha256=source_sha256,
                subject=str(raw["subject"]),
                predicate=predicate,
                object=str(raw["object"]),
                confidence=float(raw["confidence"]),
                observed_at=observed_at,
                source_locator=(
                    str(raw["source_locator"]) if raw.get("source_locator") is not None else None
                ),
                uncertainty=(str(raw["uncertainty"]) if raw.get("uncertainty") is not None else None),
                metadata={
                    "provider": "zai",
                    "requested_model": self.model,
                    "base_url": self.base_url,
                },
            )
            event.validate()
            events.append(event)
        return tuple(events)


@dataclass(slots=True)
class ZAIEvaluatorClient:
    model: str = DEFAULT_ZAI_MODEL
    base_url: str = DEFAULT_ZAI_BASE_URL
    max_output_tokens: int = 6000
    max_tool_rounds: int = 8
    per_call_retrieval_budget: int = 12
    temperature: float = 1.0
    client: Any = None

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = build_zai_client(base_url=self.base_url)

    def evaluate(self, task: EvaluatorTask, tool: SubstrateRetrievalTool) -> EvaluatorAnswer:
        tools = self._tools()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._instructions()},
            {
                "role": "user",
                "content": f"Case {task.case_id}; question {task.question_id}: {task.question}",
            },
        ]
        started = time.perf_counter()
        input_tokens = 0
        output_tokens = 0
        operation_cost = 0

        for _round in range(self.max_tool_rounds + 1):
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                response_format={"type": "json_object"},
                temperature=self.temperature,
                max_tokens=self.max_output_tokens,
                extra_body=_thinking_body(),
            )
            current_input, current_output = _usage(completion)
            input_tokens += current_input
            output_tokens += current_output
            message = completion.choices[0].message
            calls = getattr(message, "tool_calls", None) or []
            if not calls:
                payload = json.loads(_content(message))
                latency_ms = round((time.perf_counter() - started) * 1000)
                return EvaluatorAnswer(
                    answer=str(payload["answer"]),
                    confidence=float(payload["confidence"]),
                    cited_event_ids=tuple(str(item) for item in payload["cited_event_ids"]),
                    retrieval_operation_units=operation_cost,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    model=str(getattr(completion, "model", self.model)),
                )
            if _round >= self.max_tool_rounds:
                raise RuntimeError("evaluator exceeded maximum retrieval rounds")
            messages.append(_assistant_tool_message(message))
            for call in calls:
                output, cost = self._execute_tool(call, tool)
                operation_cost += cost
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(output, sort_keys=True),
                    }
                )
        raise RuntimeError("unreachable evaluator state")

    def _execute_tool(self, call: Any, tool: SubstrateRetrievalTool) -> tuple[dict[str, Any], int]:
        if call.function.name == "list_epistemic_subjects":
            return {"subjects": list(tool.subjects())}, 0
        if call.function.name != "retrieve_epistemic_events":
            raise ValueError(f"unexpected evaluator tool call: {call.function.name}")
        arguments = json.loads(call.function.arguments)
        retrieval = tool.retrieve(
            str(arguments["subject"]),
            str(arguments["predicate"]),
            self.per_call_retrieval_budget,
        )
        output = {
            "events": [_retrieved_event_mapping(event) for event in retrieval.events],
            "chosen_event_id": retrieval.chosen_event_id,
            "operation_cost": retrieval.operation_cost,
            "complete": retrieval.complete,
        }
        return output, retrieval.operation_cost

    @staticmethod
    def _instructions() -> str:
        return (
            "You are a blinded evaluator in a controlled experiment. Answer using only deposited "
            "evidence returned by tools. You cannot access raw sources or producer state. First list "
            "subjects when exact normalized names are unknown, then retrieve evidence using an exact "
            "subject and frozen predicate. Cite every materially supporting event. If evidence is "
            "insufficient, return an empty answer with low confidence. Your final response must be one "
            "JSON object containing answer, confidence, and cited_event_ids. The answer value must contain "
            "only the requested value or values in question order, separated by '; ' when needed, with no "
            "labels or prose."
        )

    @staticmethod
    def _tools() -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "retrieve_epistemic_events",
                    "description": "Retrieve deposited evidence matching an exact subject and predicate.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {"type": "string"},
                            "predicate": {"type": "string", "enum": list(RELATION_ONTOLOGY)},
                        },
                        "required": ["subject", "predicate"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_epistemic_subjects",
                    "description": "List subject names present in the event log; reveals no objects.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                },
            },
        ]


__all__ = [
    "DEFAULT_ZAI_BASE_URL",
    "DEFAULT_ZAI_MODEL",
    "ZAIEvaluatorClient",
    "ZAIProducerClient",
    "build_zai_client",
]
