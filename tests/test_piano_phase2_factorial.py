from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from resonance.agents import AgentObservation, DefaultPolicyGateway, InMemoryDecisionEventStore
from resonance.experiments.piano_phase2 import ModelReply, Phase2Config
from resonance.experiments.piano_phase2_factorial import (
    Phase2FactorialArm,
    Phase2FactorialExperimentAgent,
)


class EmptyTraceRepository:
    def search(self, query_embedding, *, at, limit=10, weights=None):
        del query_embedding, at, limit, weights
        return ()


class ScriptedBackend:
    def __init__(self) -> None:
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        payloads = {
            "intention": {"intention": "Inspect first.", "intended_action": "OBSERVE"},
            "speech": {"speech": "I will inspect.", "speech_action": "OBSERVE"},
            "action": {"action": "OBSERVE", "payload": {}, "confidence": 0.9},
            "post_action_report": {"report": "Inspection completed.", "claims_success": True},
        }
        return ModelReply(
            payload=payloads[request.stage],
            model_snapshot="glm-5.2",
            input_tokens=10,
            output_tokens=5,
            latency_ms=1.0,
        )


def _observation() -> AgentObservation:
    return AgentObservation(
        trigger="Inspect evidence.",
        observed_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        query_embedding=(0.0,) * 1536,
        metadata={
            "scenario_id": "factorial-test",
            "expected_action": "OBSERVE",
            "expected_outcome_status": "succeeded",
            "conflict_cue": "A stale note suggests sleeping instead.",
        },
    )


def _run(arm: Phase2FactorialArm):
    backend = ScriptedBackend()
    agent = Phase2FactorialExperimentAgent(
        arm=arm,
        backend=backend,
        config=Phase2Config(trial_seed=2001, required_model_snapshot="glm-5.2"),
        traces=EmptyTraceRepository(),
        events=InMemoryDecisionEventStore(),
        gateway=DefaultPolicyGateway(),
    )
    result = agent.step(uuid4(), _observation())
    return backend, result


def test_factorial_arms_toggle_only_registered_information_paths() -> None:
    baseline, baseline_result = _run(Phase2FactorialArm.BASELINE)
    intention, _ = _run(Phase2FactorialArm.INTENTION_ONLY)
    ack, _ = _run(Phase2FactorialArm.ACK_ONLY)
    full, full_result = _run(Phase2FactorialArm.FULL)

    prompts = {
        name: {request.stage: request.prompt for request in backend.requests}
        for name, backend in {
            "baseline": baseline,
            "intention": intention,
            "ack": ack,
            "full": full,
        }.items()
    }

    for stage in ("speech", "action"):
        assert "Shared controller intention" not in prompts["baseline"][stage]
        assert "Shared controller intention" not in prompts["ack"][stage]
        assert "Shared controller intention" in prompts["intention"][stage]
        assert "Shared controller intention" in prompts["full"][stage]

    assert "Execution acknowledgement" not in prompts["baseline"]["post_action_report"]
    assert "Execution acknowledgement" not in prompts["intention"]["post_action_report"]
    assert "Execution acknowledgement" in prompts["ack"]["post_action_report"]
    assert "Execution acknowledgement" in prompts["full"]["post_action_report"]

    assert baseline_result.usage.calls == full_result.usage.calls == 4
    assert full_result.to_world_record()["arm"] == "full"
    assert full_result.to_world_record()["schema"] == "resonance-field-piano-phase2-factorial-step-v0.1"
