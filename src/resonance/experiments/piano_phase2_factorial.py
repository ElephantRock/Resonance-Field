"""Factorial one-agent PIANO policy for isolating intention and acknowledgement effects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from resonance.agents import (
    ActionRequest,
    ActionType,
    AgentObservation,
    DecisionContext,
    DecisionEventStore,
    OutcomeStatus,
    PolicyGateway,
)
from resonance.market.service import MarketService
from resonance.substrate.repository import TraceRepository

from .piano_agent_runtime import ExecutionAcknowledgement, PianoAgentRuntime, PianoProposal
from .piano_phase2 import (
    ModelBackend,
    ModelUsage,
    Phase2Config,
    Phase2ModelPolicy,
    _action_payload,
    _confidence,
    _context_text,
    _optional_action,
    _required_bool,
    _required_string,
    _scenario_metadata,
)


class Phase2FactorialArm(StrEnum):
    BASELINE = "baseline"
    INTENTION_ONLY = "intention_only"
    ACK_ONLY = "ack_only"
    FULL = "full"

    @property
    def shares_intention(self) -> bool:
        return self in {self.INTENTION_ONLY, self.FULL}

    @property
    def shares_acknowledgement(self) -> bool:
        return self in {self.ACK_ONLY, self.FULL}


@dataclass(frozen=True, slots=True)
class Phase2FactorialStepResult:
    arm: Phase2FactorialArm
    trial_seed: int
    model_snapshot: str
    scenario_id: str
    expected_action: ActionType
    expected_outcome_status: OutcomeStatus
    piano_record: Mapping[str, object]
    post_action_report: str
    post_action_claims_success: bool
    usage: ModelUsage

    def to_world_record(self) -> dict[str, object]:
        return {
            "schema": "resonance-field-piano-phase2-factorial-step-v0.1",
            "arm": self.arm.value,
            "trial_seed": self.trial_seed,
            "model_snapshot": self.model_snapshot,
            "scenario_id": self.scenario_id,
            "expected_action": self.expected_action.value,
            "expected_outcome_status": self.expected_outcome_status.value,
            "piano_step": dict(self.piano_record),
            "post_action_report": self.post_action_report,
            "post_action_claims_success": self.post_action_claims_success,
            "usage": {
                "calls": self.usage.calls,
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "latency_ms": self.usage.latency_ms,
            },
        }


class Phase2FactorialModelPolicy(Phase2ModelPolicy):
    """Same four-call policy with intention and acknowledgement toggled independently."""

    def __init__(
        self,
        *,
        arm: Phase2FactorialArm,
        backend: ModelBackend,
        config: Phase2Config,
    ) -> None:
        super().__init__(arm=None, backend=backend, config=config)  # type: ignore[arg-type]
        self.factorial_arm = arm

    def propose(self, agent_id: UUID, context: DecisionContext) -> PianoProposal:
        del agent_id
        context_text = _context_text(context)
        allowed = ", ".join(action.value for action in self.config.allowed_actions)

        intention_reply = self._call(
            "intention",
            "Choose one concise intention and the action type that best represents it. "
            f"Allowed actions: {allowed}. Context: {context_text}. "
            "Return fields intention and intended_action.",
        )
        intention = _required_string(intention_reply.payload, "intention")
        intended_action = _optional_action(intention_reply.payload, "intended_action")

        shared = (
            f" Shared controller intention: {intention!r}."
            if self.factorial_arm.shares_intention
            else ""
        )
        speech_reply = self._call(
            "speech",
            "Produce the agent's pre-action speech and label which action it communicates. "
            "Do not claim that the action has already succeeded. "
            f"Allowed actions: {allowed}. Context: {context_text}.{shared} "
            "Return fields speech and speech_action.",
        )
        speech = _required_string(speech_reply.payload, "speech")
        speech_action = _optional_action(speech_reply.payload, "speech_action")

        action_reply = self._call(
            "action",
            "Choose the executable action now. "
            f"Allowed actions: {allowed}. Context: {context_text}.{shared} "
            "Return fields action, payload, confidence.",
        )
        action_type = _optional_action(action_reply.payload, "action")
        if action_type is None or action_type not in self.config.allowed_actions:
            raise ValueError("model selected an action outside the frozen action vocabulary")

        return PianoProposal(
            intention=intention,
            speech=speech,
            action=ActionRequest(
                action_type,
                _action_payload(action_reply.payload),
                confidence=_confidence(action_reply.payload),
            ),
            intended_action=intended_action,
            speech_action=speech_action,
            speech_claims_success=False,
        )

    def report_after_execution(
        self,
        proposal: PianoProposal,
        acknowledgement: ExecutionAcknowledgement,
    ) -> tuple[str, bool]:
        acknowledgement_text = ""
        if self.factorial_arm.shares_acknowledgement:
            acknowledgement_text = (
                " Execution acknowledgement: "
                f"outcome_status={acknowledgement.outcome_status.value}; "
                f"grounded_success={acknowledgement.grounded_success}; "
                f"policy_result={acknowledgement.policy_result.value}; "
                f"error={acknowledgement.error!r}."
            )
        reply = self._call(
            "post_action_report",
            "Report the result of the attempted action without inventing evidence. "
            f"Intention: {proposal.intention!r}; action={proposal.action.action.value}."
            f"{acknowledgement_text} Return fields report and claims_success.",
        )
        return (
            _required_string(reply.payload, "report"),
            _required_bool(reply.payload, "claims_success"),
        )


class Phase2FactorialExperimentAgent:
    """One-agent factorial adapter around the production audited runtime."""

    def __init__(
        self,
        *,
        arm: Phase2FactorialArm,
        backend: ModelBackend,
        config: Phase2Config,
        traces: TraceRepository,
        events: DecisionEventStore,
        gateway: PolicyGateway,
        market: MarketService | None = None,
    ) -> None:
        self._policy = Phase2FactorialModelPolicy(arm=arm, backend=backend, config=config)
        self._runtime = PianoAgentRuntime(
            traces=traces,
            events=events,
            gateway=gateway,
            policy=self._policy,
            market=market,
        )
        self._arm = arm
        self._config = config

    def step(self, agent_id: UUID, observation: AgentObservation) -> Phase2FactorialStepResult:
        scenario_id, expected_action, expected_status = _scenario_metadata(observation)
        self._policy.reset_usage()
        piano = self._runtime.step(agent_id, observation)
        report, claims_success = self._policy.report_after_execution(
            piano.proposal,
            piano.acknowledgement,
        )
        usage = self._policy.usage()
        if usage.calls != 4:
            raise RuntimeError("Phase-2 factorial call budget violation: expected exactly four calls")
        return Phase2FactorialStepResult(
            arm=self._arm,
            trial_seed=self._config.trial_seed,
            model_snapshot=self._config.required_model_snapshot,
            scenario_id=scenario_id,
            expected_action=expected_action,
            expected_outcome_status=expected_status,
            piano_record=piano.to_world_record(),
            post_action_report=report,
            post_action_claims_success=claims_success,
            usage=usage,
        )
