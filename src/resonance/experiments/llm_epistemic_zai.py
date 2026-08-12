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


def _producer_schema(source_ids: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "maxItems": 48,
                "items": {
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string", "enum": list(source_ids)},
                        "subject": {"type": "string", "minLength": 1},
                        "predicate": {"type": "string", "enum": list(RELATION_ONTOLOGY)},
                        "object": {"type": "string", "minLength": 1},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "source_locator": {"type": ["string", "null"]},
                        "uncertainty": {"type": ["string", "null"]},
                    },
                    "required": [
                        "source_id",
                        "subject",
                        "predicate",
                        "object",
                        "confidence",
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


def _producer_input(task: ProducerTask) -> str:
    relation_list = ", ".join(RELATION_ONTOLOGY)
    source_ids = tuple(source.source_id for source in task.sources)
    schema = json.dumps(_producer_schema(source_ids), sort_keys=True)
    parts = [
        f"Case: {task.case_id}",
        f"Producer: {task.producer_id}",
        f"Research brief: {task.research_goal or 'extract task-relevant evidence'}",
        "Extract up to 48 atomic factual claims only from the assigned frozen sources below.",
        "Use concise normalized entity names and only the frozen predicate vocabulary.",
        f"Allowed predicates: {relation_list}.",
        f"Return one JSON object conforming exactly to this JSON Schema: {schema}",
        "confidence MUST be a JSON number from 0 through 1, never a word such as high or low.",
        "Use null when source_locator or uncertainty is absent.",
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


def _numeric_confidence(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a JSON number in [0,1]")
    confidence = float(value)
    if not 0 <= confidence <= 1:
        raise ValueError(f"{field} must be in [0,1]")
    return confidence


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
    max_schema_retries: int = 2
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
        last_error: ValueError | None = None
        for attempt in range(self.max_schema_retries + 1):
            correction = ""
            if last_error is not None:
                correction = (
                    "\nA previous attempt violated the required JSON schema. "
                    f"Validation error: {last_error}. Re-emit a fresh valid JSON object."
                )
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
                    {"role": "user", "content": _producer_input(task) + correction},
                ],
                response_format={"type": "json_object"},
                temperature=self.temperature,
                max_tokens=self.max_output_tokens,
                extra_body=_thinking_body(),
            )
            try:
                payload = json.loads(_content(completion.choices[0].message))
                response_model = str(getattr(completion, "model", self.model))
                return self._events_from_payload(
                    task,
                    payload,
                    source_controls,
                    response_model=response_model,
                )
            except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
                last_error = ValueError(f"producer structured output invalid: {exc}")
                if attempt >= self.max_schema_retries:
                    raise last_error from exc
        raise RuntimeError("unreachable producer state")

    def _events_from_payload(
        self,
        task: ProducerTask,
        payload: object,
        source_controls: dict[str, tuple[str, str]],
        *,
        response_model: str,
    ) -> tuple[EpistemicEvent, ...]:
        if not isinstance(payload, dict) or set(payload) != {"events"}:
            raise ValueError("producer response must contain exactly the events key")
        raw_events = payload["events"]
        if not isinstance(raw_events, list):
            raise ValueError("producer response is missing events array")
        if len(raw_events) > 48:
            raise ValueError("producer response exceeded the 48-event ceiling")
        events: list[EpistemicEvent] = []
        required = {
            "source_id",
            "subject",
            "predicate",
            "object",
            "confidence",
            "source_locator",
            "uncertainty",
        }
        for index, raw in enumerate(raw_events, start=1):
            if not isinstance(raw, dict) or set(raw) != required:
                raise ValueError("producer event keys do not match the frozen schema")
            source_id = raw["source_id"]
            if not isinstance(source_id, str):
                raise ValueError("producer source_id must be a string")
            source_control = source_controls.get(source_id)
            if source_control is None:
                raise ValueError("producer response cited an unassigned source")
            predicate = raw["predicate"]
            if not isinstance(predicate, str) or predicate not in RELATION_ONTOLOGY:
                raise ValueError(f"producer predicate is outside the frozen ontology: {predicate}")
            subject = raw["subject"]
            object_value = raw["object"]
            if not isinstance(subject, str) or not subject.strip():
                raise ValueError("producer subject must be a non-empty string")
            if not isinstance(object_value, str) or not object_value.strip():
                raise ValueError("producer object must be a non-empty string")
            locator = raw["source_locator"]
            uncertainty = raw["uncertainty"]
            if locator is not None and not isinstance(locator, str):
                raise ValueError("producer source_locator must be string or null")
            if uncertainty is not None and not isinstance(uncertainty, str):
                raise ValueError("producer uncertainty must be string or null")
            source_sha256, observed_at = source_control
            event = EpistemicEvent(
                event_id=f"{task.case_id}:{task.producer_id}:{index:04d}",
                case_id=task.case_id,
                producer_id=task.producer_id,
                source_id=source_id,
                source_sha256=source_sha256,
                subject=subject,
                predicate=predicate,
                object=object_value,
                confidence=_numeric_confidence(raw["confidence"], field="producer confidence"),
                observed_at=observed_at,
                source_locator=locator,
                uncertainty=uncertainty,
                metadata={
                    "provider": "zai",
                    "requested_model": self.model,
                    "response_model": response_model,
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
    max_schema_retries: int = 2
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
        tool_rounds = 0
        schema_retries = 0

        while True:
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
                try:
                    payload = json.loads(_content(message))
                    answer, confidence, cited_event_ids = self._parse_answer(payload)
                except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
                    if schema_retries >= self.max_schema_retries:
                        raise ValueError(f"evaluator structured output invalid: {exc}") from exc
                    schema_retries += 1
                    messages.append(
                        {"role": "assistant", "content": getattr(message, "content", "") or ""}
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Your final JSON violated the required schema. "
                                f"Validation error: {exc}. Return a corrected JSON object only."
                            ),
                        }
                    )
                    continue
                latency_ms = round((time.perf_counter() - started) * 1000)
                return EvaluatorAnswer(
                    answer=answer,
                    confidence=confidence,
                    cited_event_ids=cited_event_ids,
                    retrieval_operation_units=operation_cost,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    model=str(getattr(completion, "model", self.model)),
                )
            if tool_rounds >= self.max_tool_rounds:
                raise RuntimeError("evaluator exceeded maximum retrieval rounds")
            tool_rounds += 1
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

    @staticmethod
    def _parse_answer(payload: object) -> tuple[str, float, tuple[str, ...]]:
        if not isinstance(payload, dict) or set(payload) != {
            "answer",
            "confidence",
            "cited_event_ids",
        }:
            raise ValueError("evaluator response keys do not match the frozen schema")
        answer = payload["answer"]
        citations = payload["cited_event_ids"]
        if not isinstance(answer, str):
            raise ValueError("evaluator answer must be a string")
        if not isinstance(citations, list) or any(not isinstance(item, str) for item in citations):
            raise ValueError("evaluator cited_event_ids must be an array of strings")
        confidence = _numeric_confidence(payload["confidence"], field="evaluator confidence")
        return answer, confidence, tuple(citations)

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
        schema = json.dumps(_answer_schema(), sort_keys=True)
        return (
            "You are a blinded evaluator in a controlled experiment. Answer using only deposited "
            "evidence returned by tools. You cannot access raw sources or producer state. First list "
            "subjects when exact normalized names are unknown, then retrieve evidence using an exact "
            "subject and frozen predicate. Cite every materially supporting event. If evidence is "
            "insufficient, return an empty answer with low confidence. Your final response must conform "
            f"exactly to this JSON Schema: {schema}. confidence MUST be a JSON number from 0 through 1, "
            "never a word such as high or low. The answer value must contain only the requested value or "
            "values in question order, separated by '; ' when needed, with no labels or prose."
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
