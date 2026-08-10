"""Generic substrate-backed execution loop for initially general-purpose agents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from resonance.market.service import MarketService
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


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _datetime(value: object, name: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO-8601 datetime") from exc
    else:
        raise ValueError(f"{name} must be a datetime")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return result


def _string_sequence(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise ValueError(f"{name} must be a sequence of strings")
    result = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise ValueError(f"{name} must contain non-empty strings")
    return result


def _safe_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Return audit-safe action metadata rather than blindly persisting inputs."""
    safe: dict[str, object] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(fragment in lowered for fragment in _REDACTED_KEYS):
            safe[key] = "[REDACTED]"
        elif key == "embedding" and isinstance(value, Sequence) and not isinstance(value, str):
            safe["embedding_dimensions"] = len(value)
        elif isinstance(value, UUID):
            safe[key] = str(value)
        elif isinstance(value, datetime):
            safe[key] = value.isoformat()
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
        market: MarketService | None = None,
    ) -> None:
        self._traces = traces
        self._events = events
        self._gateway = gateway
        self._policy = policy
        self._market = market

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

    def _require_market(self) -> MarketService:
        if self._market is None:
            raise RuntimeError("market executor is not configured")
        return self._market

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
            if not isinstance(embedding_value, Sequence) or isinstance(embedding_value, str):
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

        if action == ActionType.POST_TASK:
            market = self._require_market()
            description = payload.get("description")
            if not isinstance(description, str) or not description.strip():
                raise ValueError("description must be a non-empty string")
            required = _string_sequence(payload.get("required_capabilities", ()), "required_capabilities")
            success_condition = payload.get("success_condition", {})
            if not isinstance(success_condition, Mapping):
                raise ValueError("success_condition must be a mapping")
            task = market.post_task(
                agent_id,
                description=description,
                budget=_integer(payload, "budget"),
                deadline=_datetime(payload.get("deadline"), "deadline"),
                at=now,
                required_capabilities=required,
                success_condition=success_condition,
            )
            return ActionOutcome(
                status=OutcomeStatus.SUCCEEDED,
                data={
                    "task_id": str(task.task_id),
                    "budget": task.budget,
                    "deadline": task.deadline.isoformat(),
                    "status": task.status,
                },
            )

        if action == ActionType.BID_TASK:
            market = self._require_market()
            strategy = payload.get("strategy_summary")
            if not isinstance(strategy, str) or not strategy.strip():
                raise ValueError("strategy_summary must be a non-empty string")
            bid = market.submit_bid(
                agent_id,
                task_id=_uuid(payload.get("task_id"), "task_id"),
                price=_integer(payload, "price"),
                confidence=request.confidence,
                estimated_completion_seconds=_integer(payload, "estimated_completion_seconds"),
                strategy_summary=strategy,
                at=now,
            )
            return ActionOutcome(
                status=OutcomeStatus.SUCCEEDED,
                data={
                    "bid_id": str(bid.bid_id),
                    "task_id": str(bid.task_id),
                    "price": bid.price,
                    "status": bid.status,
                },
            )

        if action in {ActionType.ABSTAIN, ActionType.SLEEP}:
            return ActionOutcome(status=OutcomeStatus.SUCCEEDED)

        raise RuntimeError(f"no executor enabled for {action}")
