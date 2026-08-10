"""Policy gateway between agent proposals and executors."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from .actions import ActionRequest, ActionType


class PolicyResult(StrEnum):
    ALLOW = "allow"
    REJECT = "reject"
    REQUIRE_HUMAN_APPROVAL = "require_human_approval"


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    result: PolicyResult
    reason: str


class PolicyGateway(Protocol):
    """Validate an action proposal before any side effect occurs."""

    def evaluate(self, agent_id: UUID, request: ActionRequest) -> PolicyEvaluation: ...


class DefaultPolicyGateway:
    """Conservative v0.1 gateway enabling implemented internal and market actions."""

    DEFAULT_ALLOWED = frozenset(
        {
            ActionType.OBSERVE,
            ActionType.QUERY_SUBSTRATE,
            ActionType.READ_TRACE,
            ActionType.WRITE_TRACE,
            ActionType.REINFORCE_TRACE,
            ActionType.POST_TASK,
            ActionType.BID_TASK,
            ActionType.ABSTAIN,
            ActionType.SLEEP,
        }
    )

    def __init__(
        self,
        *,
        allowed_actions: frozenset[ActionType] | None = None,
        approval_actions: frozenset[ActionType] | None = None,
    ) -> None:
        self._allowed_actions = allowed_actions or self.DEFAULT_ALLOWED
        self._approval_actions = approval_actions or frozenset()

    def evaluate(self, agent_id: UUID, request: ActionRequest) -> PolicyEvaluation:
        del agent_id
        if request.action in self._approval_actions:
            return PolicyEvaluation(
                PolicyResult.REQUIRE_HUMAN_APPROVAL,
                "action requires explicit human approval",
            )
        if request.action in self._allowed_actions:
            return PolicyEvaluation(PolicyResult.ALLOW, "action enabled by v0.1 policy")
        return PolicyEvaluation(
            PolicyResult.REJECT,
            "action primitive exists but its executor is not enabled in v0.1",
        )
