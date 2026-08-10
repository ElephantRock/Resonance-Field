"""Generic substrate-backed execution loop for initially general-purpose agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence
from uuid import UUID

from resonance.substrate.models import RetrievedTrace, Trace
from resonance.substrate.repository import TraceRepository

from .actions import ActionOutcome, ActionRequest, ActionType, OutcomeStatus
from .events import DecisionEvent, DecisionEventStore
from .gateway import PolicyEvaluation, PolicyGateway, PolicyResult

_REDACTED_KEYS = ("secret", "token", "password", "api_key", "authorization")


@dataclass(frozen=True, slots=True)
class AgentObservation:
    """Externally supplied trigger plus the embedding used to inspect the substrate."""

    trigger: str
    observed_at: datetime
    query_embedding: tuple[float, ...]
    retrieval_limit: int = 8
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.trigger.strip():
            raise ValueError("trigger must not be empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if len(self.query_embedding) != 1536:
            raise ValueError("query_embedding must contain exactly 1536 dimensions")
        if self.retrieval_limit <= 0:
            raise ValueError("retrieval_limit must be positive")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class DecisionContext:
    observation: AgentObservation
    retrieved: tuple[RetrievedTrace, ...]


class AgentPolicy(Protocol):
    """Decision policy; may later be backed by an LLM, rules, or learned controller."""

    def choose(self, agent_id: UUID, context: DecisionContext) -> ActionRequest: ...


@dataclass(frozen=True, slots=True)
class StepResult:
    context: DecisionContext
    request: ActionRequest
    policy: PolicyEvaluation
    outcome: ActionOutcome
    event: DecisionEvent


def _uuid(value: object, name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be a UUID") from exc
    raise ValueError(f"{name} must be a UUID")


def _number(payload: Mapping[str, object], name: str, default: float) -> float:
    value = payload.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    return float(value)


def _safe_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Return audit-safe action metadata rather than blindly persisting inputs."""
    safe: dict[str, object] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(fragment in lowered for fragment in _REDACTED_KEYS):
            safe[key] = "[REDACTED]"
        elif key == "embedding" and isinstance(value, Sequence):
            safe["embedding_dimensions"] = len(value)
        elif isinstance(value, UUID):
            safe[key] = str(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        else:
            safe[key] = f"<{type(value).__name__}>"
    return safe


class AgentRuntime:
    """OBSERVE -> QUERY -> CHOOSE -> GATE -> ACT -> TRACE."""

    def __init__(
        self,
        *,
        traces: TraceRepository,
        events: DecisionEventStore,
        gateway: PolicyGateway,
        policy: AgentPolicy,
    ) -> None:
        self._traces = traces
        self._events = events
        self._gateway = gateway
        self._policy = policy

    def step(self, agent_id: UUID, observation: AgentObservation) -> StepResult:
        retrieved = tuple(
            self._traces.search(
                observation.query_embedding,
                at=observation.observed_at,
                limit=observation.retrieval_limit,
            )
        )
        context = DecisionContext(observation=observation, retrieved=retrieved)
        request = self._policy.choose(agent_id, context)
        evaluation = self._gateway.evaluate(agent_id, request)

        if evaluation.result == PolicyResult.REJECT:
            outcome = ActionOutcome(status=OutcomeStatus.REJECTED)
        elif evaluation.result == PolicyResult.REQUIRE_HUMAN_APPROVAL:
            outcome = ActionOutcome(status=OutcomeStatus.APPROVAL_REQUIRED)
        else:
            try:
                outcome = self._execute(agent_id, context, request)
            except Exception as exc:
                outcome = ActionOutcome(
                    status=OutcomeStatus.FAILED,
                    error=f"{type(exc).__name__}: {exc}",
                )

        event = DecisionEvent(
            agent_id=agent_id,
            occurred_at=observation.observed_at,
            trigger=observation.trigger,
            proposed_action=request.action,
            policy_result=evaluation.result,
            policy_reason=evaluation.reason,
            outcome_status=outcome.status,
            confidence=request.confidence,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            retrieved_trace_ids=tuple(item.trace.trace_id for item in retrieved),
            output_trace_ids=outcome.output_trace_ids,
            action_payload=_safe_payload(request.payload),
            outcome_data=outcome.data,
            error=outcome.error,
        )
        self._events.append(event)
        return StepResult(context, request, evaluation, outcome, event)

    def _execute(
        self,
        agent_id: UUID,
        context: DecisionContext,
        request: ActionRequest,
    ) -> ActionOutcome:
        action = request.action
        payload = request.payload
        now = context.observation.observed_at

        if action in {ActionType.OBSERVE, ActionType.QUERY_SUBSTRATE}:
            return ActionOutcome(
                status=OutcomeStatus.SUCCEEDED,
                data={"retrieved_count": len(context.retrieved)},
            )

        if action == ActionType.READ_TRACE:
            trace_id = _uuid(payload.get("trace_id"), "trace_id")
            trace = self._traces.get(trace_id)
            return ActionOutcome(
                status=OutcomeStatus.SUCCEEDED,
                data={
                    "trace_id": str(trace_id),
                    "found": trace is not None,
                    "kind": None if trace is None else trace.kind,
                },
            )

        if action == ActionType.WRITE_TRACE:
            content = payload.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("content must be a non-empty string")
            kind = payload.get("kind", "HYPOTHESIS")
            if not isinstance(kind, str) or not kind.strip():
                raise ValueError("kind must be a non-empty string")

            embedding_value = payload.get("embedding", context.observation.query_embedding)
            if not isinstance(embedding_value, Sequence):
                raise ValueError("embedding must be a sequence")
            embedding = tuple(float(value) for value in embedding_value)

            trace = Trace(
                author_agent_id=agent_id,
                kind=kind,
                content=content,
                embedding=embedding,
                created_at=now,
                updated_at=now,
                initial_energy=_number(payload, "initial_energy", 0.5),
                half_life_seconds=_number(payload, "half_life_seconds", 86400.0),
                confidence=request.confidence,
                quality_score=_number(payload, "quality_score", 0.0),
                context_score=_number(payload, "context_score", 0.0),
                exploration_bonus=_number(payload, "exploration_bonus", 0.0),
            )
            self._traces.add(trace)
            return ActionOutcome(
                status=OutcomeStatus.SUCCEEDED,
                output_trace_ids=(trace.trace_id,),
                data={"trace_id": str(trace.trace_id), "kind": trace.kind},
            )

        if action == ActionType.REINFORCE_TRACE:
            trace_id = _uuid(payload.get("trace_id"), "trace_id")
            trace = self._traces.reinforce(
                trace_id,
                at=now,
                actor_agent_id=agent_id,
                reinforcement=_number(payload, "reinforcement", 0.0),
                adoption=_number(payload, "adoption", 0.0),
                verified_utility=_number(payload, "verified_utility", 0.0),
            )
            return ActionOutcome(
                status=OutcomeStatus.SUCCEEDED,
                output_trace_ids=(trace.trace_id,),
                data={"trace_id": str(trace.trace_id), "reinforced": True},
            )

        if action in {ActionType.ABSTAIN, ActionType.SLEEP}:
            return ActionOutcome(status=OutcomeStatus.SUCCEEDED)

        raise RuntimeError(f"no executor enabled for {action}")
