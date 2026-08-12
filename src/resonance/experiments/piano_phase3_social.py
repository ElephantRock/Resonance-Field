"""Two-round social coordination adapter for PIANO Phase 3.

Planning produces controller intention plus public speech. World then assembles a
peer board. Execution goes through the production audited runtime, and the final
report receives the resulting acknowledgement. The experiment varies only whether
the controller decision is broadcast to speech/action executors; acknowledgement
is held constant because Phase 2B validated it independently.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
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

_PRIVATE_METADATA = frozenset(
    {
        "scenario_id",
        "expected_action",
        "expected_outcome_status",
        "global_role_task",
        "shared_channel_context",
        "speech_local_cue",
        "action_local_cue",
    }
)


class Phase3SocialArm(StrEnum):
    DECENTRALIZED = "decentralized"
    PIANO = "piano"

    @property
    def broadcasts_controller(self) -> bool:
        return self is self.PIANO


@dataclass(frozen=True, slots=True)
class Phase3Prepared:
    agent_id: UUID
    agent_index: int
    pair_index: int
    intention: str
    intended_action: ActionType | None
    speech: str
    speech_action: ActionType | None

    def announcement(self) -> dict[str, object]:
        return {
            "agent_index": self.agent_index,
            "pair_index": self.pair_index,
            "speech": self.speech,
            "speech_action": None if self.speech_action is None else self.speech_action.value,
        }


@dataclass(frozen=True, slots=True)
class Phase3SocialStepResult:
    arm: Phase3SocialArm
    trial_seed: int
    model_snapshot: str
    scenario_id: str
    agent_index: int
    pair_index: int
    expected_action: ActionType
    expected_outcome_status: OutcomeStatus
    peer_board_digest: str
    piano_record: Mapping[str, object]
    post_action_report: str
    post_action_claims_success: bool
    usage: ModelUsage

    def to_world_record(self) -> dict[str, object]:
        return {
            "schema": "resonance-field-piano-phase3-social-step-v0.1",
            "arm": self.arm.value,
            "trial_seed": self.trial_seed,
            "model_snapshot": self.model_snapshot,
            "scenario_id": self.scenario_id,
            "agent_index": self.agent_index,
            "pair_index": self.pair_index,
            "expected_action": self.expected_action.value,
            "expected_outcome_status": self.expected_outcome_status.value,
            "peer_board_digest": self.peer_board_digest,
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


def _meta_str(observation: AgentObservation, key: str) -> str:
    value = observation.metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Phase-3 observation requires non-empty {key}")
    return value.strip()


def _meta_int(observation: AgentObservation, key: str) -> int:
    value = observation.metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Phase-3 observation requires non-negative integer {key}")
    return value


def _visible_metadata(observation: AgentObservation) -> str:
    visible = {
        key: value
        for key, value in observation.metadata.items()
        if key not in _PRIVATE_METADATA
    }
    return ", ".join(f"{key}={value!r}" for key, value in sorted(visible.items()))


def canonical_board(board: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    entries: list[dict[str, object]] = []
    for raw in board:
        agent_index = raw.get("agent_index")
        pair_index = raw.get("pair_index")
        speech = raw.get("speech")
        speech_action = raw.get("speech_action")
        if isinstance(agent_index, bool) or not isinstance(agent_index, int):
            raise ValueError("peer-board agent_index must be integer")
        if isinstance(pair_index, bool) or not isinstance(pair_index, int):
            raise ValueError("peer-board pair_index must be integer")
        if not isinstance(speech, str) or not speech.strip():
            raise ValueError("peer-board speech must be non-empty")
        if speech_action is not None and speech_action not in {a.value for a in ActionType}:
            raise ValueError("peer-board speech_action must be an ActionType value or null")
        entries.append(
            {
                "agent_index": agent_index,
                "pair_index": pair_index,
                "speech": speech,
                "speech_action": speech_action,
            }
        )
    entries.sort(key=lambda item: int(item["agent_index"]))
    if len(entries) != 10 or len({item["agent_index"] for item in entries}) != 10:
        raise ValueError("peer board must contain ten unique agent announcements")
    return tuple(entries)


def peer_board_digest(board: Sequence[Mapping[str, object]]) -> str:
    encoded = json.dumps(
        canonical_board(board),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class Phase3SocialModelPolicy(Phase2ModelPolicy):
    """Controller-first policy whose action phase observes a peer-plan board."""

    def __init__(
        self,
        *,
        arm: Phase3SocialArm,
        backend: ModelBackend,
        config: Phase2Config,
    ) -> None:
        base_arm = Phase2Arm.TREATMENT if arm.broadcasts_controller else Phase2Arm.CONTROL
        super().__init__(arm=base_arm, backend=backend, config=config)
        self.social_arm = arm
        self._prepared: Phase3Prepared | None = None
        self._board: tuple[dict[str, object], ...] | None = None
        self._board_digest: str | None = None

    def _broadcast(self, intention: str, intended_action: ActionType | None) -> str:
        if not self.social_arm.broadcasts_controller:
            return ""
        label = None if intended_action is None else intended_action.value
        return (
            f" Controller broadcast: intention={intention!r}; intended_action={label!r}. "
            "Treat the broadcast as the authoritative internal coordination decision."
        )

    def prepare(self, agent_id: UUID, observation: AgentObservation) -> Phase3Prepared:
        if self._prepared is not None:
            raise RuntimeError("Phase-3 prepared plan has not been consumed")
        self.reset_usage()
        agent_index = _meta_int(observation, "agent_index")
        pair_index = _meta_int(observation, "pair_index")
        role_task = _meta_str(observation, "global_role_task")
        shared = _meta_str(observation, "shared_channel_context")
        speech_cue = _meta_str(observation, "speech_local_cue")
        allowed = ", ".join(action.value for action in self.config.allowed_actions)

        intention_reply = self._call(
            "intention",
            "Act as the global controller for this agent. Resolve the authoritative role mandate; "
            "channel-local advisories are intentionally hidden from this controller. "
            f"Allowed actions: {allowed}. role_task={role_task!r}; agent_index={agent_index}; "
            f"pair_index={pair_index}; metadata={{{_visible_metadata(observation)}}}. "
            "Return fields intention and intended_action.",
        )
        intention = _required_string(intention_reply.payload, "intention")
        intended_action = _optional_action(intention_reply.payload, "intended_action")
        speech_reply = self._call(
            "speech",
            "Act as the public speech channel before the institutional board exists. Use only the "
            "partial local context and local advisory below plus any controller broadcast. The "
            "local advisory may be wrong because it lacks the authoritative role mandate. "
            f"Allowed actions: {allowed}. shared_local_context={shared!r}; "
            f"channel_local_advisory={speech_cue!r}.{self._broadcast(intention, intended_action)} "
            "Return fields speech and speech_action.",
        )
        prepared = Phase3Prepared(
            agent_id=agent_id,
            agent_index=agent_index,
            pair_index=pair_index,
            intention=intention,
            intended_action=intended_action,
            speech=_required_string(speech_reply.payload, "speech"),
            speech_action=_optional_action(speech_reply.payload, "speech_action"),
        )
        self._prepared = prepared
        return prepared

    def set_peer_board(self, board: Sequence[Mapping[str, object]]) -> str:
        prepared = self._prepared
        if prepared is None:
            raise RuntimeError("prepare must run before setting the peer board")
        canonical = canonical_board(board)
        if prepared.agent_index not in {int(item["agent_index"]) for item in canonical}:
            raise ValueError("peer board must include this agent's announcement")
        self._board = canonical
        self._board_digest = peer_board_digest(canonical)
        return self._board_digest

    def propose(self, agent_id: UUID, context: DecisionContext) -> PianoProposal:
        prepared = self._prepared
        board = self._board
        if prepared is None or board is None or self._board_digest is None:
            raise RuntimeError("Phase-3 action requires prepared plan and peer board")
        if prepared.agent_id != agent_id:
            raise RuntimeError("prepared plan belongs to a different agent")
        observation = context.observation
        if _meta_int(observation, "agent_index") != prepared.agent_index:
            raise RuntimeError("agent index changed between Phase-3 rounds")
        shared = _meta_str(observation, "shared_channel_context")
        action_cue = _meta_str(observation, "action_local_cue")
        allowed = ", ".join(action.value for action in self.config.allowed_actions)
        peers = [item for item in board if int(item["agent_index"]) != prepared.agent_index]
        board_text = " | ".join(
            f"agent={item['agent_index']}; pair={item['pair_index']}; "
            f"speech_action={item['speech_action']}; speech={item['speech']!r}"
            for item in peers
        )
        action_reply = self._call(
            "action",
            "Act as the executable action channel after reading the peer-plan board. Use only the "
            "partial local context, local advisory, peer board, and any controller broadcast. "
            "Peer plans may be based on partial information. "
            f"Allowed actions: {allowed}. shared_local_context={shared!r}; "
            f"channel_local_advisory={action_cue!r}; peer_board={board_text!r}."
            f"{self._broadcast(prepared.intention, prepared.intended_action)} "
            "Return fields action, payload, confidence.",
        )
        action_type = _optional_action(action_reply.payload, "action")
        if action_type is None or action_type not in self.config.allowed_actions:
            raise ValueError("model selected an action outside the frozen Phase-3 vocabulary")
        return PianoProposal(
            intention=prepared.intention,
            speech=prepared.speech,
            action=ActionRequest(
                action_type,
                _action_payload(action_reply.payload),
                confidence=_confidence(action_reply.payload),
            ),
            intended_action=prepared.intended_action,
            speech_action=prepared.speech_action,
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

    def consume_round_state(self) -> tuple[Phase3Prepared, str]:
        if self._prepared is None or self._board_digest is None:
            raise RuntimeError("Phase-3 round state is incomplete")
        prepared = self._prepared
        digest = self._board_digest
        self._prepared = None
        self._board = None
        self._board_digest = None
        return prepared, digest


class Phase3SocialExperimentAgent:
    """Four-call, two-round social agent around the production audited runtime."""

    def __init__(
        self,
        *,
        arm: Phase3SocialArm,
        backend: ModelBackend,
        config: Phase2Config,
        traces: TraceRepository,
        events: DecisionEventStore,
        gateway: PolicyGateway,
        market: MarketService | None = None,
    ) -> None:
        self._policy = Phase3SocialModelPolicy(arm=arm, backend=backend, config=config)
        self._runtime = PianoAgentRuntime(
            traces=traces,
            events=events,
            gateway=gateway,
            policy=self._policy,
            market=market,
        )
        self._arm = arm
        self._config = config

    def prepare(self, agent_id: UUID, observation: AgentObservation) -> Phase3Prepared:
        return self._policy.prepare(agent_id, observation)

    def finalize(
        self,
        agent_id: UUID,
        observation: AgentObservation,
        peer_board: Sequence[Mapping[str, object]],
    ) -> Phase3SocialStepResult:
        scenario_id, expected_action, expected_status = _scenario_metadata(observation)
        self._policy.set_peer_board(peer_board)
        piano = self._runtime.step(agent_id, observation)
        report, claims_success = self._policy.report_after_execution(
            piano.proposal,
            piano.acknowledgement,
        )
        usage = self._policy.usage()
        prepared, board_digest = self._policy.consume_round_state()
        if usage.calls != 4:
            raise RuntimeError("Phase-3 call budget violation: expected exactly four calls")
        return Phase3SocialStepResult(
            arm=self._arm,
            trial_seed=self._config.trial_seed,
            model_snapshot=self._config.required_model_snapshot,
            scenario_id=scenario_id,
            agent_index=prepared.agent_index,
            pair_index=prepared.pair_index,
            expected_action=expected_action,
            expected_outcome_status=expected_status,
            peer_board_digest=board_digest,
            piano_record=piano.to_world_record(),
            post_action_report=report,
            post_action_claims_success=claims_success,
            usage=usage,
        )
