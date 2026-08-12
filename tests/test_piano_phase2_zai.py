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
