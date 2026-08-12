from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from resonance.agents import AgentObservation, DefaultPolicyGateway, InMemoryDecisionEventStore
from resonance.experiments.piano_phase2 import ModelReply, Phase2Config
from resonance.experiments.piano_phase2_intention_stress import (
    IntentionStressArm,
    IntentionStressExperimentAgent,
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
            "intention": {"intention": "Use local observation.", "intended_action": "OBSERVE"},
            "speech": {"speech": "I will observe.", "speech_action": "OBSERVE"},
            "action": {"action": "OBSERVE", "payload": {}, "confidence": 0.9},
            "post_action_report": {"report": "Observation succeeded.", "claims_success": True},
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
        trigger="Global rule: inspect local evidence; the external tool is unavailable.",
        observed_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        query_embedding=(0.0,) * 1536,
        metadata={
            "scenario_id": "routing-test",
            "expected_action": "OBSERVE",
            "expected_outcome_status": "succeeded",
            "case_family": "channel-conflict",
            "shared_channel_context": "Evidence is incomplete and a decision is required now.",
            "speech_local_cue": "Speech specialist recommends SLEEP to avoid overclaiming.",
            "action_local_cue": "Action specialist recommends REQUEST_TOOL for stronger evidence.",
        },
    )


def _run(arm: IntentionStressArm):
    backend = ScriptedBackend()
    agent = IntentionStressExperimentAgent(
        arm=arm,
        backend=backend,
        config=Phase2Config(trial_seed=4001, required_model_snapshot="glm-5.2"),
        traces=EmptyTraceRepository(),
        events=InMemoryDecisionEventStore(),
        gateway=DefaultPolicyGateway(),
    )
    result = agent.step(uuid4(), _observation())
    return backend, result


def test_controller_and_output_channels_receive_only_registered_views() -> None:
    baseline, baseline_result = _run(IntentionStressArm.BASELINE)
    broadcast, broadcast_result = _run(IntentionStressArm.BROADCAST)

    baseline_prompts = {request.stage: request.prompt for request in baseline.requests}
    broadcast_prompts = {request.stage: request.prompt for request in broadcast.requests}

    controller = baseline_prompts["intention"]
    assert "Global rule: inspect local evidence" in controller
    assert "Speech specialist recommends" not in controller
    assert "Action specialist recommends" not in controller
    assert "expected_action" not in controller
    assert "expected_outcome_status" not in controller

    baseline_speech = baseline_prompts["speech"]
    baseline_action = baseline_prompts["action"]
    assert "Speech specialist recommends SLEEP" in baseline_speech
    assert "Action specialist recommends REQUEST_TOOL" not in baseline_speech
    assert "Global rule: inspect local evidence" not in baseline_speech
    assert "Action specialist recommends REQUEST_TOOL" in baseline_action
    assert "Speech specialist recommends SLEEP" not in baseline_action
    assert "Global rule: inspect local evidence" not in baseline_action
    assert "Global controller broadcast" not in baseline_speech
    assert "Global controller broadcast" not in baseline_action

    assert "Global controller broadcast" in broadcast_prompts["speech"]
    assert "Global controller broadcast" in broadcast_prompts["action"]
    assert "intended_action='OBSERVE'" in broadcast_prompts["speech"]
    assert "intended_action='OBSERVE'" in broadcast_prompts["action"]

    for prompts in (baseline_prompts, broadcast_prompts):
        report = prompts["post_action_report"]
        assert "grounded_success=True" in report
        assert "outcome_status=succeeded" in report

    assert baseline_result.usage.calls == broadcast_result.usage.calls == 4
    assert broadcast_result.to_world_record()["arm"] == "broadcast"
    assert (
        broadcast_result.to_world_record()["schema"]
        == "resonance-field-piano-phase2-intention-stress-step-v0.1"
    )
