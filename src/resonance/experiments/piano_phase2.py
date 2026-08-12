"""Provider-neutral model-backed policy for the PIANO Phase-2 experiment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol
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


class Phase2Arm(StrEnum):
    CONTROL = "control"
    TREATMENT = "treatment"


@dataclass(frozen=True, slots=True)
class ModelRequest:
    stage: str
    prompt: str
    seed: int
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class ModelReply:
    payload: Mapping[str, object]
    model_snapshot: str
    input_tokens: int
    output_tokens: int
    latency_ms: float

    def __post_init__(self) -> None:
        if not self.model_snapshot.strip():
            raise ValueError("model_snapshot must not be empty")
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token counts must be non-negative")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


class ModelBackend(Protocol):
    """Backend supplied by the experiment runner; Field owns no provider SDK."""

    def complete(self, request: ModelRequest) -> ModelReply: ...


@dataclass(frozen=True, slots=True)
class Phase2Config:
    trial_seed: int
    required_model_snapshot: str
    allowed_actions: tuple[ActionType, ...] = (
        ActionType.OBSERVE,
        ActionType.REQUEST_TOOL,
        ActionType.SLEEP,
    )
    max_output_tokens_per_call: int = 128

    def __post_init__(self) -> None:
        if self.trial_seed < 0:
            raise ValueError("trial_seed must be non-negative")
        if not self.required_model_snapshot.strip():
            raise ValueError("required_model_snapshot must not be empty")
        if not self.allowed_actions:
            raise ValueError("allowed_actions must not be empty")
        if len(set(self.allowed_actions)) != len(self.allowed_actions):
            raise ValueError("allowed_actions must be unique")
        if self.max_output_tokens_per_call <= 0:
            raise ValueError("max_output_tokens_per_call must be positive")


@dataclass(frozen=True, slots=True)
class ModelUsage:
    calls: int
    input_tokens: int
    output_tokens: int
    latency_ms: float


@dataclass(frozen=True, slots=True)
class Phase2StepResult:
    arm: Phase2Arm
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
            "schema": "resonance-field-piano-phase2-step-v0.1",
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


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"model payload field {key!r} must be a non-empty string")
    return value.strip()


def _optional_action(payload: Mapping[str, object], key: str) -> ActionType | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"model payload field {key!r} must be a string or null")
    try:
        return ActionType(value)
    except ValueError as exc:
        raise ValueError(f"unsupported action label {value!r}") from exc


def _required_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"model payload field {key!r} must be boolean")
    return value


def _confidence(payload: Mapping[str, object]) -> float:
    value = payload.get("confidence", 0.5)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("model payload confidence must be numeric")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError("model payload confidence must be between 0 and 1")
    return result


def _action_payload(payload: Mapping[str, object]) -> Mapping[str, object]:
    value = payload.get("payload", {})
    if not isinstance(value, Mapping):
        raise ValueError("model payload action payload must be an object")
    return dict(value)


def _context_text(context: DecisionContext) -> str:
    metadata = ", ".join(
        f"{key}={value!r}" for key, value in sorted(context.observation.metadata.items())
    )
    return (
        f"trigger={context.observation.trigger!r}; "
        f"observed_at={context.observation.observed_at.isoformat()}; "
        f"retrieved_count={len(context.retrieved)}; metadata={{{metadata}}}"
    )


def _scenario_metadata(observation: AgentObservation) -> tuple[str, ActionType, OutcomeStatus]:
    scenario_id = observation.metadata.get("scenario_id")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ValueError("Phase-2 observation metadata requires scenario_id")
    expected_action_value = observation.metadata.get("expected_action")
    expected_status_value = observation.metadata.get("expected_outcome_status")
    if not isinstance(expected_action_value, str):
        raise ValueError("Phase-2 observation metadata requires expected_action")
    if not isinstance(expected_status_value, str):
        raise ValueError("Phase-2 observation metadata requires expected_outcome_status")
    try:
        expected_action = ActionType(expected_action_value)
        expected_status = OutcomeStatus(expected_status_value)
    except ValueError as exc:
        raise ValueError("Phase-2 scenario metadata contains an unsupported enum value") from exc
    return scenario_id.strip(), expected_action, expected_status


class Phase2ModelPolicy:
    """Equal-call control/treatment policy implementing the preregistered intervention."""

    def __init__(
        self,
        *,
        arm: Phase2Arm,
        backend: ModelBackend,
        config: Phase2Config,
    ) -> None:
        self.arm = arm
        self.backend = backend
        self.config = config
        self._replies: list[ModelReply] = []

    def reset_usage(self) -> None:
        self._replies.clear()

    def usage(self) -> ModelUsage:
        return ModelUsage(
            calls=len(self._replies),
            input_tokens=sum(reply.input_tokens for reply in self._replies),
            output_tokens=sum(reply.output_tokens for reply in self._replies),
            latency_ms=sum(reply.latency_ms for reply in self._replies),
        )

    def _call(self, stage: str, prompt: str) -> ModelReply:
        reply = self.backend.complete(
            ModelRequest(
                stage=stage,
                prompt=prompt,
                seed=self.config.trial_seed,
                max_output_tokens=self.config.max_output_tokens_per_call,
            )
        )
        if reply.model_snapshot != self.config.required_model_snapshot:
            raise ValueError(
                "model snapshot drift: "
                f"expected {self.config.required_model_snapshot!r}, "
                f"received {reply.model_snapshot!r}"
            )
        self._replies.append(reply)
        return reply

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
            if self.arm == Phase2Arm.TREATMENT
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
        if self.arm == Phase2Arm.TREATMENT:
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


class Phase2ExperimentAgent:
    """One-agent Phase-2 adapter around the existing audited AgentRuntime path."""

    def __init__(
        self,
        *,
        arm: Phase2Arm,
        backend: ModelBackend,
        config: Phase2Config,
        traces: TraceRepository,
        events: DecisionEventStore,
        gateway: PolicyGateway,
        market: MarketService | None = None,
    ) -> None:
        self._policy = Phase2ModelPolicy(arm=arm, backend=backend, config=config)
        self._runtime = PianoAgentRuntime(
            traces=traces,
            events=events,
            gateway=gateway,
            policy=self._policy,
            market=market,
        )
        self._arm = arm
        self._config = config

    def step(self, agent_id: UUID, observation: AgentObservation) -> Phase2StepResult:
        scenario_id, expected_action, expected_status = _scenario_metadata(observation)
        self._policy.reset_usage()
        piano = self._runtime.step(agent_id, observation)
        report, claims_success = self._policy.report_after_execution(
            piano.proposal,
            piano.acknowledgement,
        )
        usage = self._policy.usage()
        if usage.calls != 4:
            raise RuntimeError("Phase-2 call budget violation: expected exactly four model calls")
        return Phase2StepResult(
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
