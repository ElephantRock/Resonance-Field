"""Bounded retry transport for transient Z.AI request-rate limits."""

from __future__ import annotations

import os
import time
from types import SimpleNamespace
from typing import Any, Callable

TRANSIENT_ZAI_RATE_CODES = frozenset({"1302", "1305"})


def _error_body(exc: BaseException) -> dict[str, Any] | None:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        nested = body.get("error")
        return nested if isinstance(nested, dict) else body
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            payload = response.json()
        except Exception:  # pragma: no cover - depends on HTTP client internals
            return None
        if isinstance(payload, dict):
            nested = payload.get("error")
            return nested if isinstance(nested, dict) else payload
    return None


def _status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def zai_business_error_code(exc: BaseException) -> str | None:
    body = _error_body(exc)
    if body is None:
        return None
    code = body.get("code")
    return str(code) if code is not None else None


def is_transient_zai_rate_limit(exc: BaseException) -> bool:
    return _status_code(exc) == 429 and zai_business_error_code(exc) in TRANSIENT_ZAI_RATE_CODES


class RetryingCompletions:
    """Retry only transient Z.AI 1302/1305 failures with exponential backoff."""

    def __init__(
        self,
        delegate: Any,
        *,
        max_retries: int = 5,
        base_delay_seconds: float = 2.0,
        max_delay_seconds: float = 32.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if base_delay_seconds <= 0 or max_delay_seconds <= 0:
            raise ValueError("retry delays must be positive")
        self._delegate = delegate
        self._max_retries = max_retries
        self._base_delay_seconds = base_delay_seconds
        self._max_delay_seconds = max_delay_seconds
        self._sleep = sleep

    def create(self, **kwargs: Any) -> Any:
        retries = 0
        while True:
            try:
                return self._delegate.create(**kwargs)
            except Exception as exc:
                if not is_transient_zai_rate_limit(exc) or retries >= self._max_retries:
                    raise
                delay = min(
                    self._base_delay_seconds * (2**retries),
                    self._max_delay_seconds,
                )
                self._sleep(delay)
                retries += 1


class RetryingZAIClient:
    """Minimal OpenAI-compatible client surface with explicit Z.AI retry policy."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str,
        max_retries: int = 5,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise RuntimeError("install the project with the 'llm' extra to use Z.AI clients") from exc
        key = api_key or os.getenv("ZAI_API_KEY")
        if not key:
            raise RuntimeError("ZAI_API_KEY is required to use the Z.AI instrumentation provider")
        raw = OpenAI(api_key=key, base_url=base_url.rstrip("/") + "/", max_retries=0)
        self.chat = SimpleNamespace(
            completions=RetryingCompletions(raw.chat.completions, max_retries=max_retries)
        )


__all__ = [
    "RetryingCompletions",
    "RetryingZAIClient",
    "TRANSIENT_ZAI_RATE_CODES",
    "is_transient_zai_rate_limit",
    "zai_business_error_code",
]
