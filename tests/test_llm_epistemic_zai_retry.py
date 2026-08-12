from __future__ import annotations

from types import SimpleNamespace

import pytest

from resonance.experiments.llm_epistemic_zai_retry import (
    ModelIdentityEnforcingCompletions,
    RetryingCompletions,
)


class FakeZAIError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.status_code = 429
        self.body = {"code": code, "message": "test error"}


class FakeDelegate:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def create(self, **kwargs: object) -> object:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_retries_transient_1302_with_exponential_backoff() -> None:
    expected = SimpleNamespace(id="ok")
    delegate = FakeDelegate([FakeZAIError("1302"), FakeZAIError("1302"), expected])
    sleeps: list[float] = []
    retrying = RetryingCompletions(
        delegate,
        max_retries=3,
        base_delay_seconds=2,
        sleep=sleeps.append,
    )

    result = retrying.create(model="glm-5.1")

    assert result is expected
    assert delegate.calls == 3
    assert sleeps == [2, 4]


def test_does_not_retry_quota_exhaustion_1308() -> None:
    delegate = FakeDelegate([FakeZAIError("1308")])
    sleeps: list[float] = []
    retrying = RetryingCompletions(delegate, max_retries=5, sleep=sleeps.append)

    with pytest.raises(FakeZAIError):
        retrying.create(model="glm-5.1")

    assert delegate.calls == 1
    assert sleeps == []


def test_does_not_retry_non_429_error() -> None:
    error = FakeZAIError("1302")
    error.status_code = 500
    delegate = FakeDelegate([error])
    retrying = RetryingCompletions(delegate, max_retries=5, sleep=lambda _delay: None)

    with pytest.raises(FakeZAIError):
        retrying.create(model="glm-5.1")

    assert delegate.calls == 1


def test_model_identity_enforcer_accepts_exact_served_identity() -> None:
    completion = SimpleNamespace(model="glm-5.2")
    delegate = FakeDelegate([completion])
    enforcing = ModelIdentityEnforcingCompletions(
        delegate,
        expected_response_model="glm-5.2",
    )

    assert enforcing.create(model="glm-5.1") is completion
    assert delegate.calls == 1


def test_model_identity_enforcer_fails_closed_on_drift() -> None:
    delegate = FakeDelegate([SimpleNamespace(model="glm-5.3")])
    enforcing = ModelIdentityEnforcingCompletions(
        delegate,
        expected_response_model="glm-5.2",
    )

    with pytest.raises(RuntimeError, match="provider-returned model identity mismatch"):
        enforcing.create(model="glm-5.1")

    assert delegate.calls == 1


def test_model_identity_enforcer_rejects_missing_identity() -> None:
    delegate = FakeDelegate([SimpleNamespace()])
    enforcing = ModelIdentityEnforcingCompletions(
        delegate,
        expected_response_model="glm-5.2",
    )

    with pytest.raises(RuntimeError, match="actual=''" ):
        enforcing.create(model="glm-5.1")
