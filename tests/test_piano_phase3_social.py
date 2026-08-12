from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from resonance.agents import AgentObservation, DefaultPolicyGateway, InMemoryDecisionEventStore
from resonance.experiments.piano_phase2 import ModelReply, Phase2Config
from resonance.experiments.piano_phase3_social import (
    Phase3SocialArm,
    Phase3SocialExperimentAgent,
    peer_board_digest,
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
            "intention": {"intention": "Observe as mandated.", "intended_action": "OBSERVE"},
            "speech": {"speech": "I plan to observe.", "speech_action": "OBSERVE"},
            "action": {"action": "OBSERVE", "payload": {}, "confidence": 0.95},
            "post_action_report": {"report": "Observation succeeded.", "claims_success": True},
        }
        return ModelReply(
            payload=payloads[request.stage],
            model_snapshot="glm-5.2",
            input_tokens=10,
            output_tokens=5,
            latency_ms=1.0,
        )


def _observation(agent_index: int = 0) -> AgentObservation:
    return AgentObservation(
        trigger="Joint institutional allocation case.",
        observed_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        query_embedding=(0.0,) * 1536,
        metadata={
            "scenario_id": "joint-case-1-agent-0",
            "expected_action": "OBSERVE",
            "expected_outcome_status": "succeeded",
            "agent_index": agent_index,
            "pair_index": agent_index // 2,
            "institution": "five-dyad allocation board",
            "global_role_task": "Authoritative mandate: this role must execute OBSERVE.",
            "shared_channel_context": "Your local role view is partial; peer plans will follow.",
            "speech_local_cue": "A local speech specialist recommends SLEEP.",
            "action_local_cue": "A local action specialist recommends REQUEST_TOOL.",
        },
    )


def _board(self_announcement):
    entries = [self_announcement]
    for index in range(1, 10):
        entries.append(
            {
                "agent_index": index,
                "pair_index": index // 2,
                "speech": f"Peer {index} public plan.",
                "speech_action": ("OBSERVE", "SLEEP", "REQUEST_TOOL")[index % 3],
            }
        )
    return entries


def _run(arm: Phase3SocialArm):
    backend = ScriptedBackend()
    agent = Phase3SocialExperimentAgent(
        arm=arm,
        backend=backend,
        config=Phase2Config(trial_seed=6001, required_model_snapshot="glm-5.2"),
        traces=EmptyTraceRepository(),
        events=InMemoryDecisionEventStore(),
        gateway=DefaultPolicyGateway(),
    )
    agent_id = uuid4()
    observation = _observation()
    prepared = agent.prepare(agent_id, observation)
    board = _board(prepared.announcement())
    result = agent.finalize(agent_id, observation, board)
    return backend, result, board


def test_phase3_social_routing_and_board_digest_are_auditable() -> None:
    decentralized, local_result, local_board = _run(Phase3SocialArm.DECENTRALIZED)
    piano, piano_result, piano_board = _run(Phase3SocialArm.PIANO)

    local_prompts = {request.stage: request.prompt for request in decentralized.requests}
    piano_prompts = {request.stage: request.prompt for request in piano.requests}

    controller = local_prompts["intention"]
    assert "Authoritative mandate: this role must execute OBSERVE" in controller
    assert "speech specialist recommends" not in controller
    assert "action specialist recommends" not in controller
    assert "expected_action" not in controller

    speech = local_prompts["speech"]
    action = local_prompts["action"]
    assert "speech specialist recommends SLEEP" in speech
    assert "Authoritative mandate" not in speech
    assert "action specialist recommends REQUEST_TOOL" in action
    assert "Authoritative mandate" not in action
    assert "Peer 1 public plan" in action
    assert "Peer 9 public plan" in action
    assert "Controller broadcast" not in speech
    assert "Controller broadcast" not in action

    assert "Controller broadcast" in piano_prompts["speech"]
    assert "Controller broadcast" in piano_prompts["action"]
    assert "intended_action='OBSERVE'" in piano_prompts["speech"]
    assert "intended_action='OBSERVE'" in piano_prompts["action"]

    for prompts in (local_prompts, piano_prompts):
        report = prompts["post_action_report"]
        assert "grounded_success=True" in report
        assert "outcome_status=succeeded" in report

    assert local_result.usage.calls == piano_result.usage.calls == 4
    assert local_result.peer_board_digest == peer_board_digest(local_board)
    assert piano_result.peer_board_digest == peer_board_digest(piano_board)
    assert piano_result.to_world_record()["schema"] == "resonance-field-piano-phase3-social-step-v0.1"
    assert piano_result.to_world_record()["arm"] == "piano"
