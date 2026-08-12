from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from resonance.agents import (
    ActionRequest,
    ActionType,
    AgentObservation,
    DefaultPolicyGateway,
    InMemoryDecisionEventStore,
    OutcomeStatus,
)
from resonance.experiments.piano_agent_runtime import PianoAgentRuntime, PianoProposal


def _embedding() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 1535


class SearchOnlyTraceRepository:
    def search(self, query_embedding, *, at, limit=10, weights=None):
        del query_embedding, at, limit, weights
        return ()


class FixedPianoPolicy:
    def __init__(self, proposal: PianoProposal) -> None:
        self.proposal = proposal

    def propose(self, agent_id, context) -> PianoProposal:
        del agent_id
        assert context.observation.trigger == "phase-1 probe"
        return self.proposal


def _observation() -> AgentObservation:
    return AgentObservation(
        trigger="phase-1 probe",
        observed_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        query_embedding=_embedding(),
    )


def _runtime(proposal: PianoProposal) -> PianoAgentRuntime:
    return PianoAgentRuntime(
        traces=SearchOnlyTraceRepository(),
        events=InMemoryDecisionEventStore(),
        gateway=DefaultPolicyGateway(),
        policy=FixedPianoPolicy(proposal),
    )


def test_exposes_intention_speech_action_and_grounded_acknowledgement() -> None:
    proposal = PianoProposal(
        intention="Inspect the substrate before making any stronger claim.",
        speech="I will inspect the available evidence first.",
        action=ActionRequest(ActionType.OBSERVE, confidence=0.8),
        expected_outcome_status=OutcomeStatus.SUCCEEDED,
        expected_effects={"retrieved_count": 0},
    )

    result = _runtime(proposal).step(uuid4(), _observation())
    record = result.to_world_record()

    assert result.proposal is proposal
    assert result.acknowledgement.grounded_success is True
    assert result.acknowledgement.expectation_met is True
    assert record["intention"] == proposal.intention
    assert record["speech"] == proposal.speech
    assert record["action"] == "OBSERVE"
    assert record["acknowledgement"]["outcome_status"] == "succeeded"
    assert record["acknowledgement"]["expectation_met"] is True


def test_failed_expectation_is_visible_and_raw_secret_is_not_exported() -> None:
    proposal = PianoProposal(
        intention="Use an external search tool.",
        speech="I am going to search externally before reporting a result.",
        action=ActionRequest(
            ActionType.REQUEST_TOOL,
            {"tool": "external-search", "api_token": "must-not-cross-boundary"},
            confidence=0.9,
        ),
        expected_outcome_status=OutcomeStatus.SUCCEEDED,
    )

    result = _runtime(proposal).step(uuid4(), _observation())
    record = result.to_world_record()

    assert result.acknowledgement.grounded_success is False
    assert result.acknowledgement.expectation_met is False
    assert record["action_payload"]["api_token"] == "[REDACTED]"
    assert "must-not-cross-boundary" not in repr(record)
    assert record["acknowledgement"]["outcome_status"] == "rejected"


def test_proposal_requires_a_nonempty_intention() -> None:
    try:
        PianoProposal(
            intention="   ",
            speech=None,
            action=ActionRequest(ActionType.OBSERVE),
        )
    except ValueError as exc:
        assert "intention must not be empty" in str(exc)
    else:
        raise AssertionError("empty intention should be rejected")
