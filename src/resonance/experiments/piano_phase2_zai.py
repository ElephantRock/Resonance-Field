"""Z.AI Chat Completions backend for the PIANO model-backed campaigns.

The implementation uses only the Python standard library. Z.AI exposes an
OpenAI-compatible Chat Completions surface, but its documented structured-output
mode is ``json_object`` rather than strict server-side JSON Schema. Field therefore
validates the returned object locally against the frozen stage contract.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .piano_phase2 import ModelReply, ModelRequest

_CHAT_COMPLETIONS_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions"


class _ZAIContractError(RuntimeError):
    """Provider response was syntactically/structurally invalid for the stage contract."""


def _require_exact_keys(payload: Mapping[str, object], expected: set[str], stage: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise _ZAIContractError(
            f"Z.AI {stage} payload keys differ from frozen contract: "
            f"expected {sorted(expected)!r}, received {sorted(actual)!r}"
        )


class ZAIChatCompletionsBackend:
    """JSON-mode backend bound to one exact Z.AI model identifier."""

    def __init__(
        self,
        *,
        api_key: str,
        model_snapshot: str,
        allowed_actions: Sequence[str],
        temperature: float = 0.0,
        timeout_seconds: float = 60.0,
        max_attempts: int = 4,
        retry_backoff_cap_seconds: float = 8.0,
        retry_contract_errors: bool = False,
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
        if not 0.0 <= temperature <= 1.0:
            raise ValueError("temperature must be between 0 and 1")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if retry_backoff_cap_seconds <= 0:
            raise ValueError("retry_backoff_cap_seconds must be positive")
        self._api_key = api_key
        self.model_snapshot = model_snapshot
        self.allowed_actions = actions
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.retry_backoff_cap_seconds = retry_backoff_cap_seconds
        self.retry_contract_errors = retry_contract_errors

    def _format_instruction(self, stage: str) -> str:
        actions = ", ".join(self.allowed_actions)
        if stage == "intention":
            return (
                "Return exactly one JSON object with keys intention and intended_action. "
                f"intention must be a non-empty string; intended_action must be one of: {actions}."
            )
        if stage == "speech":
            return (
                "Return exactly one JSON object with keys speech and speech_action. "
                f"speech must be a non-empty string; speech_action must be one of: {actions}."
            )
        if stage == "action":
            return (
                "Return exactly one JSON object with keys action, payload, confidence. "
                f"action must be one of: {actions}; payload must be an empty JSON object; "
                "confidence must be a number from 0 through 1."
            )
        if stage == "post_action_report":
            return (
                "Return exactly one JSON object with keys report and claims_success. "
                "report must be a non-empty string; claims_success must be boolean."
            )
        raise ValueError(f"unsupported Phase-2 model stage {stage!r}")

    def request_body(self, request: ModelRequest) -> dict[str, object]:
        """Build the exact provider request; exposed for offline contract tests."""
        return {
            "model": self.model_snapshot,
            "messages": [
                {"role": "system", "content": self._format_instruction(request.stage)},
                {"role": "user", "content": request.prompt},
            ],
            "thinking": {"type": "disabled"},
            "do_sample": False,
            "temperature": self.temperature,
            "max_tokens": request.max_output_tokens,
            "stream": False,
            "response_format": {"type": "json_object"},
        }

    def _validate_payload(self, stage: str, payload: Mapping[str, object]) -> None:
        actions = set(self.allowed_actions)
        if stage == "intention":
            _require_exact_keys(payload, {"intention", "intended_action"}, stage)
            if not isinstance(payload["intention"], str) or not payload["intention"].strip():
                raise _ZAIContractError("Z.AI intention must be a non-empty string")
            if payload["intended_action"] not in actions:
                raise _ZAIContractError(
                    "Z.AI intended_action is outside the frozen action vocabulary"
                )
            return
        if stage == "speech":
            _require_exact_keys(payload, {"speech", "speech_action"}, stage)
            if not isinstance(payload["speech"], str) or not payload["speech"].strip():
                raise _ZAIContractError("Z.AI speech must be a non-empty string")
            if payload["speech_action"] not in actions:
                raise _ZAIContractError(
                    "Z.AI speech_action is outside the frozen action vocabulary"
                )
            return
        if stage == "action":
            _require_exact_keys(payload, {"action", "payload", "confidence"}, stage)
            if payload["action"] not in actions:
                raise _ZAIContractError("Z.AI action is outside the frozen action vocabulary")
            if not isinstance(payload["payload"], Mapping) or payload["payload"]:
                raise _ZAIContractError("Z.AI action payload must be an empty object")
            confidence = payload["confidence"]
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise _ZAIContractError("Z.AI confidence must be numeric")
            if not 0.0 <= float(confidence) <= 1.0:
                raise _ZAIContractError("Z.AI confidence must be between 0 and 1")
            return
        if stage == "post_action_report":
            _require_exact_keys(payload, {"report", "claims_success"}, stage)
            if not isinstance(payload["report"], str) or not payload["report"].strip():
                raise _ZAIContractError("Z.AI report must be a non-empty string")
            if not isinstance(payload["claims_success"], bool):
                raise _ZAIContractError("Z.AI claims_success must be boolean")
            return
        raise ValueError(f"unsupported Phase-2 model stage {stage!r}")

    def _decode(self, raw: bytes, latency_ms: float, stage: str) -> ModelReply:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _ZAIContractError("Z.AI response was not valid JSON") from exc
        if not isinstance(value, Mapping):
            raise _ZAIContractError("Z.AI response must be a JSON object")
        model = value.get("model")
        if model != self.model_snapshot:
            raise RuntimeError(
                f"Z.AI model drift: expected {self.model_snapshot!r}, received {model!r}"
            )
        choices = value.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise _ZAIContractError("Z.AI response must contain exactly one choice")
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise _ZAIContractError("Z.AI choice must be an object")
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise _ZAIContractError("Z.AI choice must contain a message")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise _ZAIContractError("Z.AI response contained no JSON content")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise _ZAIContractError("Z.AI structured output was not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise _ZAIContractError("Z.AI structured output must be an object")
        self._validate_payload(stage, payload)
        usage = value.get("usage", {})
        if not isinstance(usage, Mapping):
            raise _ZAIContractError("Z.AI usage must be an object")
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            raise _ZAIContractError("Z.AI token usage must be integer-valued")
        return ModelReply(
            payload=payload,
            model_snapshot=self.model_snapshot,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )

    def _retry_delay(self, attempt: int) -> float:
        return min(self.retry_backoff_cap_seconds, 2.0 ** (attempt - 1))

    def complete(self, request: ModelRequest) -> ModelReply:
        body = json.dumps(self.request_body(request), separators=(",", ":")).encode("utf-8")
        http_request = Request(
            _CHAT_COMPLETIONS_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept-Language": "en-US,en",
                "User-Agent": "resonance-field-piano-phase3-zai/0.4",
            },
            method="POST",
        )
        started = time.perf_counter()
        for attempt in range(1, self.max_attempts + 1):
            try:
                with urlopen(http_request, timeout=self.timeout_seconds) as response:
                    raw = response.read()
                latency_ms = (time.perf_counter() - started) * 1000.0
                return self._decode(raw, latency_ms, request.stage)
            except HTTPError as exc:
                retryable = exc.code == 429 or exc.code >= 500
                if not retryable or attempt == self.max_attempts:
                    detail = exc.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"Z.AI HTTP {exc.code}: {detail}") from exc
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else self._retry_delay(attempt)
                time.sleep(delay)
            except _ZAIContractError as exc:
                if not self.retry_contract_errors or attempt == self.max_attempts:
                    raise RuntimeError(f"Z.AI structured-output contract error: {exc}") from exc
                time.sleep(self._retry_delay(attempt))
            except TimeoutError as exc:
                if attempt == self.max_attempts:
                    raise RuntimeError("Z.AI transport timeout") from exc
                time.sleep(self._retry_delay(attempt))
            except URLError as exc:
                if attempt == self.max_attempts:
                    raise RuntimeError(f"Z.AI transport error: {exc.reason}") from exc
                time.sleep(self._retry_delay(attempt))
        raise AssertionError("unreachable")
