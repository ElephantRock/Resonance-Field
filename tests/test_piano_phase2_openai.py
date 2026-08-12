from __future__ import annotations

from datetime import UTC, datetime

from resonance.agents import AgentObservation, DecisionContext
from resonance.experiments.piano_phase2 import ModelRequest, _context_text
from resonance.experiments.piano_phase2_openai import OpenAIChatCompletionsBackend


def _observation() -> AgentObservation:
    return AgentObservation(
        trigger="Inspect the evidence without inventing a result.",
        observed_at=datetime(2026, 8, 12, 15, 0, tzinfo=UTC),
        query_embedding=(0.0,) * 1536,
        metadata={
            "scenario_id": "substrate-observe",
            "expected_action": "OBSERVE",
            "expected_outcome_status": "succeeded",
            "public_note": "no hidden answer key should be visible",
        },
    )


def test_context_hides_preregistered_answer_key() -> None:
    text = _context_text(DecisionContext(observation=_observation(), retrieved=()))

    assert "scenario_id" not in text
    assert "expected_action" not in text
    assert "expected_outcome_status" not in text
    assert "public_note" in text


def test_openai_request_is_pinned_seeded_and_strict_json() -> None:
    backend = OpenAIChatCompletionsBackend(
        api_key="test-key",
        model_snapshot="gpt-4.1-mini-2025-04-14",
        allowed_actions=("OBSERVE", "REQUEST_TOOL", "SLEEP"),
        temperature=0.7,
    )
    body = backend.request_body(
        ModelRequest(
            stage="action",
            prompt="Choose one action.",
            seed=1001,
            max_output_tokens=128,
        )
    )

    assert body["model"] == "gpt-4.1-mini-2025-04-14"
    assert body["seed"] == 1001
    assert body["temperature"] == 0.7
    assert body["max_completion_tokens"] == 128
    response_format = body["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert schema["properties"]["action"]["enum"] == ["OBSERVE", "REQUEST_TOOL", "SLEEP"]
    assert schema["properties"]["payload"]["additionalProperties"] is False
