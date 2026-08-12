from __future__ import annotations

import json

import pytest

from resonance.experiments.piano_phase2 import ModelRequest
from resonance.experiments.piano_phase2_zai import ZAIChatCompletionsBackend


def _backend() -> ZAIChatCompletionsBackend:
    return ZAIChatCompletionsBackend(
        api_key="test-key",
        model_snapshot="glm-4-32b-0414-128k",
        allowed_actions=("OBSERVE", "REQUEST_TOOL", "SLEEP"),
        temperature=0.0,
    )


def test_zai_request_is_dated_zero_temperature_json_mode_without_provider_seed() -> None:
    body = _backend().request_body(
        ModelRequest(
            stage="action",
            prompt="Choose one action.",
            seed=1001,
            max_output_tokens=128,
        )
    )

    assert body["model"] == "glm-4-32b-0414-128k"
    assert "seed" not in body
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 128
    assert body["stream"] is False
    assert body["response_format"] == {"type": "json_object"}
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "system"
    assert "OBSERVE" in body["messages"][0]["content"]


def _response(content: dict[str, object], *, model: str = "glm-4-32b-0414-128k") -> bytes:
    return json.dumps(
        {
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": json.dumps(content)}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 7},
        }
    ).encode()


def test_zai_local_stage_validation_accepts_exact_action_contract() -> None:
    reply = _backend()._decode(
        _response({"action": "OBSERVE", "payload": {}, "confidence": 0.75}),
        10.0,
        "action",
    )

    assert reply.model_snapshot == "glm-4-32b-0414-128k"
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
