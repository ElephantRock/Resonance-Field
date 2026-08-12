import json

import pytest

import resonance.experiments.piano_phase2_zai as zai_module
from resonance.experiments.piano_phase2 import ModelRequest
from resonance.experiments.piano_phase2_zai import ZAIChatCompletionsBackend

MODEL = "glm-5.2"


def _backend() -> ZAIChatCompletionsBackend:
    return ZAIChatCompletionsBackend(
        api_key="test-key",
        model_snapshot=MODEL,
        allowed_actions=("OBSERVE", "REQUEST_TOOL", "SLEEP"),
        temperature=0.0,
    )


def test_zai_request_is_zero_temperature_json_mode_without_provider_seed() -> None:
    body = _backend().request_body(
        ModelRequest(
            stage="action",
            prompt="Choose one action.",
            seed=1001,
            max_output_tokens=128,
        )
    )

    assert body["model"] == MODEL
    assert "seed" not in body
    assert "request_id" not in body
    assert body["thinking"] == {"type": "disabled"}
    assert body["do_sample"] is False
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 128
    assert body["stream"] is False
    assert body["response_format"] == {"type": "json_object"}
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "system"
    assert "OBSERVE" in body["messages"][0]["content"]


def _response(content: dict[str, object], *, model: str = MODEL) -> bytes:
    return json.dumps(
        {
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": json.dumps(content)}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 7},
        }
    ).encode()


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        del exc_type, exc, traceback
        return False

    def read(self) -> bytes:
        return self._body


def test_zai_retries_socket_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_urlopen(request, *, timeout):
        del request, timeout
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("simulated read timeout")
        return _FakeResponse(
            _response({"report": "The action completed.", "claims_success": True})
        )

    monkeypatch.setattr(zai_module, "urlopen", fake_urlopen)
    monkeypatch.setattr(zai_module.time, "sleep", lambda delay: None)
    backend = ZAIChatCompletionsBackend(
        api_key="test-key",
        model_snapshot=MODEL,
        allowed_actions=("OBSERVE", "REQUEST_TOOL", "SLEEP"),
        temperature=0.0,
        max_attempts=2,
    )

    reply = backend.complete(
        ModelRequest(
            stage="post_action_report",
            prompt="Report the observed outcome.",
            seed=1001,
            max_output_tokens=128,
        )
    )

    assert calls == 2
    assert reply.payload["claims_success"] is True


def test_zai_retries_invalid_structured_output_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_urlopen(request, *, timeout):
        del request, timeout
        nonlocal calls
        calls += 1
        if calls == 1:
            return _FakeResponse(_response({"intention": "Inspect the role."}))
        return _FakeResponse(
            _response(
                {
                    "intention": "Inspect the role.",
                    "intended_action": "OBSERVE",
                }
            )
        )

    monkeypatch.setattr(zai_module, "urlopen", fake_urlopen)
    monkeypatch.setattr(zai_module.time, "sleep", lambda delay: None)
    backend = ZAIChatCompletionsBackend(
        api_key="test-key",
        model_snapshot=MODEL,
        allowed_actions=("OBSERVE", "REQUEST_TOOL", "SLEEP"),
        max_attempts=2,
        retry_contract_errors=True,
    )

    reply = backend.complete(
        ModelRequest(
            stage="intention",
            prompt="Choose the role action.",
            seed=1001,
            max_output_tokens=128,
        )
    )

    assert calls == 2
    assert reply.payload["intended_action"] == "OBSERVE"


def test_zai_v2_format_recovery_changes_only_transport_instruction() -> None:
    request = ModelRequest(
        stage="post_action_report",
        prompt="Frozen scientific post-action prompt.",
        seed=8001,
        max_output_tokens=128,
    )
    backend = ZAIChatCompletionsBackend(
        api_key="test-key",
        model_snapshot=MODEL,
        allowed_actions=("OBSERVE", "REQUEST_TOOL", "SLEEP"),
        retry_contract_errors=True,
        contract_retry_prompt_hardening=True,
        unique_request_id_per_attempt=True,
    )

    first = backend.request_body(request, contract_attempt=1, physical_attempt=1)
    repaired = backend.request_body(request, contract_attempt=2, physical_attempt=2)

    assert first["messages"][1] == repaired["messages"][1] == {
        "role": "user",
        "content": request.prompt,
    }
    assert "FORMAT-RECOVERY" not in first["messages"][0]["content"]
    assert "FORMAT-RECOVERY-2" in repaired["messages"][0]["content"]
    assert '"claims_success":true' in first["messages"][0]["content"]
    assert first["request_id"] != repaired["request_id"]
    for key in (
        "model",
        "thinking",
        "do_sample",
        "temperature",
        "max_tokens",
        "stream",
        "response_format",
    ):
        assert first[key] == repaired[key]


def test_zai_v2_contract_recovery_advances_only_after_contract_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodies = []

    def fake_urlopen(request, *, timeout):
        del timeout
        body = json.loads(request.data.decode())
        bodies.append(body)
        if len(bodies) == 1:
            return _FakeResponse(_response({"report": "Observed success."}))
        return _FakeResponse(
            _response({"report": "Observed success.", "claims_success": True})
        )

    monkeypatch.setattr(zai_module, "urlopen", fake_urlopen)
    monkeypatch.setattr(zai_module.time, "sleep", lambda delay: None)
    backend = ZAIChatCompletionsBackend(
        api_key="test-key",
        model_snapshot=MODEL,
        allowed_actions=("OBSERVE", "REQUEST_TOOL", "SLEEP"),
        max_attempts=3,
        retry_contract_errors=True,
        contract_retry_prompt_hardening=True,
        unique_request_id_per_attempt=True,
    )
    request = ModelRequest(
        stage="post_action_report",
        prompt="Frozen scientific post-action prompt.",
        seed=8001,
        max_output_tokens=128,
    )

    reply = backend.complete(request)

    assert reply.payload["claims_success"] is True
    assert len(bodies) == 2
    assert bodies[0]["messages"][1] == bodies[1]["messages"][1]
    assert "FORMAT-RECOVERY" not in bodies[0]["messages"][0]["content"]
    assert "FORMAT-RECOVERY-2" in bodies[1]["messages"][0]["content"]


def test_zai_model_drift_is_not_retried_as_contract_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_urlopen(request, *, timeout):
        del request, timeout
        nonlocal calls
        calls += 1
        return _FakeResponse(
            _response(
                {"report": "Observation succeeded.", "claims_success": True},
                model="glm-moving-alias",
            )
        )

    monkeypatch.setattr(zai_module, "urlopen", fake_urlopen)
    monkeypatch.setattr(zai_module.time, "sleep", lambda delay: None)
    backend = ZAIChatCompletionsBackend(
        api_key="test-key",
        model_snapshot=MODEL,
        allowed_actions=("OBSERVE", "REQUEST_TOOL", "SLEEP"),
        max_attempts=3,
        retry_contract_errors=True,
        contract_retry_prompt_hardening=True,
        unique_request_id_per_attempt=True,
    )

    with pytest.raises(RuntimeError, match="model drift"):
        backend.complete(
            ModelRequest(
                stage="post_action_report",
                prompt="Report the observed outcome.",
                seed=1001,
                max_output_tokens=128,
            )
        )

    assert calls == 1


def test_zai_local_stage_validation_accepts_exact_action_contract() -> None:
    reply = _backend()._decode(
        _response({"action": "OBSERVE", "payload": {}, "confidence": 0.75}),
        10.0,
        "action",
    )

    assert reply.model_snapshot == MODEL
    assert reply.payload["action"] == "OBSERVE"
    assert reply.input_tokens == 12
    assert reply.output_tokens == 7


def test_zai_local_stage_validation_rejects_extra_fields() -> None:
    with pytest.raises(RuntimeError, match="keys differ"):
        _backend()._decode(
            _response(
                {
                    "action": "OBSERVE",
                    "payload": {},
                    "confidence": 0.75,
                    "unexpected": True,
                }
            ),
            10.0,
            "action",
        )


def test_zai_model_drift_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="model drift"):
        _backend()._decode(
            _response(
                {"report": "Observation succeeded.", "claims_success": True},
                model="glm-moving-alias",
            ),
            10.0,
            "post_action_report",
        )
