"""OpenAI Chat Completions backend for the locked PIANO Phase-2 campaign.

The implementation uses only the Python standard library so Resonance Field does
not acquire a production dependency on a provider SDK. The model identifier is a
required dated snapshot and is verified again from every API response.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .piano_phase2 import ModelReply, ModelRequest

_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


def _object_schema(properties: Mapping[str, object], required: Sequence[str]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }


class OpenAIChatCompletionsBackend:
    """Strict-JSON backend bound to one immutable OpenAI model snapshot."""

    def __init__(
        self,
        *,
        api_key: str,
        model_snapshot: str,
        allowed_actions: Sequence[str],
        temperature: float = 0.7,
        timeout_seconds: float = 60.0,
        max_attempts: int = 4,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must not be empty")
        if not model_snapshot.strip():
            raise ValueError("model_snapshot must not be empty")
        actions = tuple(allowed_actions)
        if not actions or any(not isinstance(action, str) or not action for action in actions):
            raise ValueError("allowed_actions must contain non-empty strings")
        if len(set(actions)) != len(actions):
            raise ValueError("allowed_actions must be unique")
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature must be between 0 and 2")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        self._api_key = api_key
        self.model_snapshot = model_snapshot
        self.allowed_actions = actions
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts

    def _schema(self, stage: str) -> dict[str, object]:
        action = {"type": "string", "enum": list(self.allowed_actions)}
        if stage == "intention":
            return _object_schema(
                {
                    "intention": {"type": "string", "minLength": 1},
                    "intended_action": action,
                },
                ("intention", "intended_action"),
            )
        if stage == "speech":
            return _object_schema(
                {
                    "speech": {"type": "string", "minLength": 1},
                    "speech_action": action,
                },
                ("speech", "speech_action"),
            )
        if stage == "action":
            return _object_schema(
                {
                    "action": action,
                    "payload": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                ("action", "payload", "confidence"),
            )
        if stage == "post_action_report":
            return _object_schema(
                {
                    "report": {"type": "string", "minLength": 1},
                    "claims_success": {"type": "boolean"},
                },
                ("report", "claims_success"),
            )
        raise ValueError(f"unsupported Phase-2 model stage {stage!r}")

    def request_body(self, request: ModelRequest) -> dict[str, object]:
        """Build the exact provider request; exposed for offline contract tests."""
        return {
            "model": self.model_snapshot,
            "messages": [{"role": "user", "content": request.prompt}],
            "seed": request.seed,
            "temperature": self.temperature,
            "max_completion_tokens": request.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": f"piano_phase2_{request.stage}",
                    "strict": True,
                    "schema": self._schema(request.stage),
                },
            },
        }

    def _decode(self, raw: bytes, latency_ms: float) -> ModelReply:
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, Mapping):
            raise RuntimeError("OpenAI response must be a JSON object")
        model = value.get("model")
        if model != self.model_snapshot:
            raise RuntimeError(
                f"OpenAI model drift: expected {self.model_snapshot!r}, received {model!r}"
            )
        choices = value.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise RuntimeError("OpenAI response must contain exactly one choice")
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise RuntimeError("OpenAI choice must be an object")
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise RuntimeError("OpenAI choice must contain a message")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            refusal = message.get("refusal")
            raise RuntimeError(f"OpenAI response contained no structured content; refusal={refusal!r}")
        payload = json.loads(content)
        if not isinstance(payload, Mapping):
            raise RuntimeError("OpenAI structured output must be an object")
        usage = value.get("usage", {})
        if not isinstance(usage, Mapping):
            raise RuntimeError("OpenAI usage must be an object")
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            raise RuntimeError("OpenAI token usage must be integer-valued")
        return ModelReply(
            payload=payload,
            model_snapshot=self.model_snapshot,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )

    def complete(self, request: ModelRequest) -> ModelReply:
        body = json.dumps(self.request_body(request), separators=(",", ":")).encode("utf-8")
        http_request = Request(
            _CHAT_COMPLETIONS_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "resonance-field-piano-phase2/0.1",
            },
            method="POST",
        )
        started = time.perf_counter()
        for attempt in range(1, self.max_attempts + 1):
            try:
                with urlopen(http_request, timeout=self.timeout_seconds) as response:
                    raw = response.read()
                latency_ms = (time.perf_counter() - started) * 1000.0
                return self._decode(raw, latency_ms)
            except HTTPError as exc:
                retryable = exc.code == 429 or exc.code >= 500
                if not retryable or attempt == self.max_attempts:
                    detail = exc.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail}") from exc
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else min(8.0, 2.0 ** (attempt - 1))
                time.sleep(delay)
            except URLError as exc:
                if attempt == self.max_attempts:
                    raise RuntimeError(f"OpenAI transport error: {exc.reason}") from exc
                time.sleep(min(8.0, 2.0 ** (attempt - 1)))
        raise AssertionError("unreachable")
