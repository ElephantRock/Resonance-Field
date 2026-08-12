"""Probe the Z.AI request surface and provider-returned model identity.

This is a mechanical pre-confirmatory compatibility probe. It contains no
scientific corpus material and produces no P/S/G/R treatment outcome.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from resonance.experiments.llm_epistemic_zai import (
    DEFAULT_ZAI_BASE_URL,
    DEFAULT_ZAI_MODEL,
    _assistant_tool_message,
    _thinking_body,
)
from resonance.experiments.llm_epistemic_zai_retry import RetryingZAIClient

PROBE_VERSION = "zai-identity-probe-v1"


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _message_json(completion: Any) -> dict[str, Any]:
    content = getattr(completion.choices[0].message, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("probe completion did not return JSON content")
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("probe completion JSON must be an object")
    return value


def run_probe(*, requested_model: str, base_url: str) -> dict[str, Any]:
    client = RetryingZAIClient(base_url=base_url)
    thinking = _thinking_body()
    structured_messages = [
        {
            "role": "system",
            "content": "You are a protocol compatibility probe. Follow the JSON instruction exactly.",
        },
        {
            "role": "user",
            "content": 'Return exactly one JSON object with "probe":"structured" and "ok":true.',
        },
    ]
    structured = client.chat.completions.create(
        model=requested_model,
        messages=structured_messages,
        response_format={"type": "json_object"},
        temperature=1.0,
        max_tokens=256,
        extra_body=thinking,
    )
    structured_payload = _message_json(structured)
    if structured_payload.get("probe") != "structured" or structured_payload.get("ok") is not True:
        raise ValueError("structured-output probe returned unexpected JSON")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "probe_value",
                "description": "Return the fixed synthetic compatibility value.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            },
        }
    ]
    tool_messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": "You are a protocol compatibility probe. Use the required tool when instructed.",
        },
        {"role": "user", "content": "Call probe_value exactly once."},
    ]
    tool_completion = client.chat.completions.create(
        model=requested_model,
        messages=tool_messages,
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "probe_value"}},
        temperature=1.0,
        max_tokens=256,
        extra_body=thinking,
    )
    message = tool_completion.choices[0].message
    calls = getattr(message, "tool_calls", None) or []
    if len(calls) != 1 or calls[0].function.name != "probe_value":
        raise ValueError("tool-call probe did not emit exactly one probe_value call")
    tool_messages.append(_assistant_tool_message(message))
    tool_messages.append(
        {
            "role": "tool",
            "tool_call_id": calls[0].id,
            "content": json.dumps({"value": "synthetic-ok"}, sort_keys=True),
        }
    )
    tool_messages.append(
        {
            "role": "user",
            "content": (
                'Return exactly one JSON object with "probe":"tool-final", '
                '"value":"synthetic-ok", and "ok":true. Do not call tools again.'
            ),
        }
    )
    final_completion = client.chat.completions.create(
        model=requested_model,
        messages=tool_messages,
        tools=tools,
        tool_choice="none",
        response_format={"type": "json_object"},
        temperature=1.0,
        max_tokens=256,
        extra_body=thinking,
    )
    final_payload = _message_json(final_completion)
    expected_final = {"probe": "tool-final", "value": "synthetic-ok", "ok": True}
    if any(final_payload.get(key) != value for key, value in expected_final.items()):
        raise ValueError("tool-finalization probe returned unexpected JSON")

    response_models = [
        str(getattr(structured, "model", "") or "").strip(),
        str(getattr(tool_completion, "model", "") or "").strip(),
        str(getattr(final_completion, "model", "") or "").strip(),
    ]
    if any(not model for model in response_models):
        raise RuntimeError("provider omitted response model identity during probe")
    if len(set(response_models)) != 1:
        raise RuntimeError(
            "provider response identity was inconsistent across probe calls: "
            f"{response_models}"
        )

    request_contract = {
        "probe_version": PROBE_VERSION,
        "provider": "zai",
        "base_url": base_url.rstrip("/"),
        "requested_model": requested_model,
        "protocol": "openai_compatible_chat_completions",
        "temperature": 1.0,
        "thinking": thinking,
        "structured_output": {"type": "json_object"},
        "tool_choice_probe": "forced_probe_value_then_none",
        "sdk_internal_retries": 0,
        "explicit_transient_retry_codes": ["1302", "1305"],
    }
    return {
        "probe_version": PROBE_VERSION,
        "scientific_content_access": False,
        "confirmatory_access": False,
        "treatment_execution": False,
        "requested_model": requested_model,
        "provider_base_url": base_url.rstrip("/"),
        "response_models": response_models,
        "consistent_response_model": response_models[0],
        "structured_output_ok": True,
        "forced_tool_call_ok": True,
        "tool_finalization_ok": True,
        "request_contract_sha256": _canonical_sha256(request_contract),
        "request_contract": request_contract,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_ZAI_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_ZAI_BASE_URL)
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_probe(requested_model=args.model, base_url=args.base_url)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    output.write_text(payload)
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
