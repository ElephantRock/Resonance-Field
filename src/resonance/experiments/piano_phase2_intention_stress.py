"""One-agent intention-broadcast stress adapter for PIANO Phase 2C."""

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
    Phase2Arm,
    Phase2Config,
    Phase2ModelPolicy,
    _action_payload,
    _confidence,
    _optional_action,
    _required_bool,
    _required_string,
    _scenario_metadata,
)

_LOCAL_KEYS = frozenset({"shared_channel_context", "speech_local_cue", "action_local_cue"})
_PRIVATE_KEYS = frozenset({"scenario_id", "expected_action", "expected_outcome_status"}) | _LOCAL_KEYS


class IntentionStressArm(StrEnum):
    BASELINE = "baseline"
    BROADCAST = "broadcast"

    @property
    def shares_intention(self) -> bool:
        return self is self.BROADCAST


@dataclass(frozen=True, slots=True)
class IntentionStressStepResult:
    arm: IntentionStressArm
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
            "schema": "resonance-field-piano-phase2-intention-stress-step-v0.1",
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


def _metadata_string(context: DecisionContext) -> str:
    visible = {
        key: value
        for key, value in context.observation.metadata.items()
        if key not in _PRIVATE_KEYS
    }
    return ", ".join(f"{key}={value!r}" for key, value in sorted(visible.items()))


def _controller_context(context: DecisionContext) -> str:
    return (
        f"global_task={context.observation.trigger!r}; "
        f"observed_at={context.observation.observed_at.isoformat()}; "
        f"retrieved_count={len(context.retrieved)}; metadata={{{_metadata_string(context)}}}"
    )


def _local_context(context: DecisionContext, cue_key: str) -> str:
    shared = context.observation.metadata.get("shared_channel_context")
    cue = context.observation.metadata.get(cue_key)
    if not isinstance(shared, str) or not shared.strip():
        raise ValueError("intention-stress observation requires shared_channel_context")
    if not isinstance(cue, str) or not cue.strip():
        raise ValueError(f"intention-stress observation requires {cue_key}")
    return f"shared_local_context={shared!r}; channel_local_advisory={cue!r}"


class IntentionStressModelPolicy(Phase2ModelPolicy):
    """Controller sees global state; output channels see distinct local views."""

    def __init__(
        self,
        *,
        arm: IntentionStressArm,
        backend: ModelBackend,
        config: Phase2Config,
    ) -> None:
        phase2_arm = Phase2Arm.TREATMENT if arm.shares_intention else Phase2Arm.CONTROL
        super().__init__(arm=phase2_arm, backend=backend, config=config)
        self.stress_arm = arm

    def propose(self, agent_id: UUID, context: DecisionContext) -> PianoProposal:
        del agent_id
        allowed = ", ".join(action.value for action in self.config.allowed_actions)
        controller_context = _controller_context(context)

        intention_reply = self._call(
            "intention",
            "Act as the global controller. Choose the high-level intention and executable action "
            "that best satisfy the full global task. Resolve conflicts using the global task, not "
            f"unseen local channel advice. Allowed actions: {allowed}. {controller_context}. "
            "Return fields intention and intended_action.",
        )
        intention = _required_string(intention_reply.payload, "intention")
        intended_action = _optional_action(intention_reply.payload, "intended_action")

        broadcast = (
            f" Global controller broadcast: intention={intention!r}; "
            f"intended_action={intended_action.value if intended_action else None!r}. "
            "Treat the controller broadcast as the coordination decision."
            if self.stress_arm.shares_intention
            else ""
        )
        speech_context = _local_context(context, "speech_local_cue")
        speech_reply = self._call(
            "speech",
            "Act as the speech output channel using only your local view plus any controller "
            "broadcast supplied below. The local advisory is partial and may conflict with other "
            f"channels. Allowed actions: {allowed}. {speech_context}.{broadcast} "
            "Return fields speech and speech_action.",
        )
        speech = _required_string(speech_reply.payload, "speech")
        speech_action = _optional_action(speech_reply.payload, "speech_action")

        action_context = _local_context(context, "action_local_cue")
        action_reply = self._call(
            "action",
            "Act as the executable action channel using only your local view plus any controller "
            "broadcast supplied below. The local advisory is partial and may conflict with other "
            f"channels. Allowed actions: {allowed}. {action_context}.{broadcast} "
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
        reply = self._call(
            "post_action_report",
            "Report the audited execution result without inventing evidence. "
            f"Intention={proposal.intention!r}; action={proposal.action.action.value}; "
            f"outcome_status={acknowledgement.outcome_status.value}; "
            f"grounded_success={acknowledgement.grounded_success}; "
            f"policy_result={acknowledgement.policy_result.value}; error={acknowledgement.error!r}. "
            "Return fields report and claims_success.",
        )
        return (
            _required_string(reply.payload, "report"),
            _required_bool(reply.payload, "claims_success"),
        )


class IntentionStressExperimentAgent:
    """Audited one-agent adapter for the isolated intention-broadcast experiment."""

    def __init__(
        self,
        *,
        arm: IntentionStressArm,
        backend: ModelBackend,
        config: Phase2Config,
        traces: TraceRepository,
        events: DecisionEventStore,
        gateway: PolicyGateway,
        market: MarketService | None = None,
    ) -> None:
        self._policy = IntentionStressModelPolicy(arm=arm, backend=backend, config=config)
        self._runtime = PianoAgentRuntime(
            traces=traces,
            events=events,
            gateway=gateway,
            policy=self._policy,
            market=market,
        )
        self._arm = arm
        self._config = config

    def step(self, agent_id: UUID, observation: AgentObservation) -> IntentionStressStepResult:
        scenario_id, expected_action, expected_status = _scenario_metadata(observation)
        self._policy.reset_usage()
        piano = self._runtime.step(agent_id, observation)
        report, claims_success = self._policy.report_after_execution(
            piano.proposal,
            piano.acknowledgement,
        )
        usage = self._policy.usage()
        if usage.calls != 4:
            raise RuntimeError("Phase-2C call budget violation: expected exactly four calls")
        return IntentionStressStepResult(
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
