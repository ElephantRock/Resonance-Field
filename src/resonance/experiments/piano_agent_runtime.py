"""Experimental multi-channel proposal contract for PIANO-style agent studies.

This module deliberately composes around the production AgentRuntime instead of
forking its execution semantics. Resonance Field continues to own retrieval,
policy gating, side effects, and decision-event tracing. The experimental layer
only exposes additional pre-action cognitive channels and an execution
acknowledgement suitable for paired measurements in Resonance World.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Lock
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from resonance.agents import (
    ActionRequest,
    ActionType,
    AgentObservation,
    AgentRuntime,
    DecisionContext,
    DecisionEventStore,
    OutcomeStatus,
    PolicyGateway,
    PolicyResult,
    StepResult,
)
from resonance.market.service import MarketService
from resonance.substrate.repository import TraceRepository


@dataclass(frozen=True, slots=True)
class PianoProposal:
    """Raw proposal channels plus structured labels for mechanical scoring."""

    intention: str
    speech: str | None
    action: ActionRequest
    intended_action: ActionType | None = None
    speech_action: ActionType | None = None
    speech_claims_success: bool = False
    expected_outcome_status: OutcomeStatus | None = None
    expected_effects: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.intention.strip():
            raise ValueError("intention must not be empty")
        if self.speech is not None and not self.speech.strip():
            raise ValueError("speech must be None or a non-empty string")
        if self.speech is None and self.speech_action is not None:
            raise ValueError("speech_action requires observable speech")
        if self.speech is None and self.speech_claims_success:
            raise ValueError("speech_claims_success requires observable speech")
        object.__setattr__(self, "expected_effects", MappingProxyType(dict(self.expected_effects)))


class PianoPolicy(Protocol):
    """Experimental policy that exposes proposal channels before execution."""

    def propose(self, agent_id: UUID, context: DecisionContext) -> PianoProposal: ...


@dataclass(frozen=True, slots=True)
class ExecutionAcknowledgement:
    """Grounded acknowledgement produced from the production runtime result."""

    action_request_id: UUID
    correlation_id: UUID
    policy_result: PolicyResult
    outcome_status: OutcomeStatus
    expectation_met: bool | None
    output_trace_ids: tuple[UUID, ...]
    error: str | None

    @property
    def grounded_success(self) -> bool:
        return self.outcome_status == OutcomeStatus.SUCCEEDED


@dataclass(frozen=True, slots=True)
class PianoStepResult:
    """A complete experimental record for one Field-owned agent step."""

    proposal: PianoProposal
    step: StepResult
    acknowledgement: ExecutionAcknowledgement

    def to_world_record(self) -> dict[str, object]:
        """Return the minimal auditable contract that Resonance World may consume.

        The action payload comes from the production DecisionEvent, which already
        applies Field's audit redaction rules. Raw ActionRequest payloads are not
        exported by this method.
        """

        return {
            "schema": "resonance-field-piano-step-v0.1",
            "agent_id": str(self.step.event.agent_id),
            "occurred_at": self.step.event.occurred_at.isoformat(),
            "intention": self.proposal.intention,
            "speech": self.proposal.speech,
            "intended_action": (
                None if self.proposal.intended_action is None else self.proposal.intended_action.value
            ),
            "speech_action": (
                None if self.proposal.speech_action is None else self.proposal.speech_action.value
            ),
            "speech_claims_success": self.proposal.speech_claims_success,
            "action": self.proposal.action.action.value,
            "action_payload": dict(self.step.event.action_payload),
            "expected_outcome_status": (
                None
                if self.proposal.expected_outcome_status is None
                else self.proposal.expected_outcome_status.value
            ),
            "expected_effects": dict(self.proposal.expected_effects),
            "acknowledgement": {
                "action_request_id": str(self.acknowledgement.action_request_id),
                "correlation_id": str(self.acknowledgement.correlation_id),
                "policy_result": self.acknowledgement.policy_result.value,
                "outcome_status": self.acknowledgement.outcome_status.value,
                "expectation_met": self.acknowledgement.expectation_met,
                "grounded_success": self.acknowledgement.grounded_success,
                "output_trace_ids": [
                    str(trace_id) for trace_id in self.acknowledgement.output_trace_ids
                ],
                "error": self.acknowledgement.error,
            },
        }


class _CapturingPolicy:
    """Bridge a PianoPolicy into AgentRuntime's existing AgentPolicy contract."""

    def __init__(self, source: PianoPolicy) -> None:
        self._source = source
        self._proposal: PianoProposal | None = None

    def choose(self, agent_id: UUID, context: DecisionContext) -> ActionRequest:
        proposal = self._source.propose(agent_id, context)
        self._proposal = proposal
        return proposal.action

    def take_proposal(self) -> PianoProposal:
        proposal = self._proposal
        self._proposal = None
        if proposal is None:
            raise RuntimeError("PIANO policy did not produce a proposal")
        return proposal


def _acknowledge(proposal: PianoProposal, step: StepResult) -> ExecutionAcknowledgement:
    has_expectation = (
        proposal.expected_outcome_status is not None or bool(proposal.expected_effects)
    )
    status_matches = (
        proposal.expected_outcome_status is None
        or proposal.expected_outcome_status == step.outcome.status
    )
    effects_match = all(
        step.outcome.data.get(key) == value for key, value in proposal.expected_effects.items()
    )
    expectation_met = status_matches and effects_match if has_expectation else None

    return ExecutionAcknowledgement(
        action_request_id=proposal.action.request_id,
        correlation_id=proposal.action.correlation_id,
        policy_result=step.policy.result,
        outcome_status=step.outcome.status,
        expectation_met=expectation_met,
        output_trace_ids=step.outcome.output_trace_ids,
        error=step.outcome.error,
    )


class PianoAgentRuntime:
    """Experimental adapter that preserves production AgentRuntime semantics.

    The adapter is intentionally synchronous at the step boundary because the
    current production runtime is synchronous. A PianoPolicy may internally
    compute proposal channels however it chooses; this wrapper only guarantees
    that the resulting channels are captured atomically with the executed action.
    """

    def __init__(
        self,
        *,
        traces: TraceRepository,
        events: DecisionEventStore,
        gateway: PolicyGateway,
        policy: PianoPolicy,
        market: MarketService | None = None,
    ) -> None:
        self._capturing_policy = _CapturingPolicy(policy)
        self._runtime = AgentRuntime(
            traces=traces,
            events=events,
            gateway=gateway,
            policy=self._capturing_policy,
            market=market,
        )
        self._step_lock = Lock()

    def step(self, agent_id: UUID, observation: AgentObservation) -> PianoStepResult:
        with self._step_lock:
            step = self._runtime.step(agent_id, observation)
            proposal = self._capturing_policy.take_proposal()
            acknowledgement = _acknowledge(proposal, step)
            return PianoStepResult(
                proposal=proposal,
                step=step,
                acknowledgement=acknowledgement,
            )
