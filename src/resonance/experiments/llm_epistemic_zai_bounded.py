"""Resource-finalizing Z.AI evaluator for Experiments 142–145 instrumentation."""

from __future__ import annotations

import json
import time
from typing import Any

from .llm_epistemic_agents import EvaluatorAnswer, EvaluatorTask, SubstrateRetrievalTool
from .llm_epistemic_zai import (
    ZAIEvaluatorClient,
    _assistant_tool_message,
    _content,
    _thinking_body,
    _usage,
)


class ZAIBudgetFinalizingEvaluatorClient(ZAIEvaluatorClient):
    """Force final JSON generation when frozen retrieval resources are exhausted."""

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
            tools_enabled = tool.remaining_budget > 0 and tool_rounds < self.max_tool_rounds
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto" if tools_enabled else "none",
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

            if not tools_enabled:
                raise RuntimeError("provider emitted tool calls when evaluator tools were disabled")
            tool_rounds += 1
            messages.append(_assistant_tool_message(message))
            for call in calls:
                output, cost = self._execute_tool(call, tool)
                operation_cost += cost
                output["retrieval_budget_remaining"] = tool.remaining_budget
                output["retrieval_budget_exhausted"] = tool.remaining_budget == 0
                output["retrieval_rounds_used"] = tool_rounds
                output["retrieval_round_limit_reached"] = tool_rounds >= self.max_tool_rounds
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(output, sort_keys=True),
                    }
                )

            if tool.remaining_budget == 0 or tool_rounds >= self.max_tool_rounds:
                reasons: list[str] = []
                if tool.remaining_budget == 0:
                    reasons.append("the frozen retrieval-operation budget is exhausted")
                if tool_rounds >= self.max_tool_rounds:
                    reasons.append("the frozen retrieval-round ceiling is reached")
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            " and ".join(reasons).capitalize()
                            + ". Do not call any more tools. Using only evidence already returned, "
                            "emit the required final JSON now; if evidence is insufficient, "
                            "return an empty answer with low confidence."
                        ),
                    }
                )


__all__ = ["ZAIBudgetFinalizingEvaluatorClient"]
