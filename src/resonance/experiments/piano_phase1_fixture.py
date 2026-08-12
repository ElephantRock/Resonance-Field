"""Deterministic Field-owned fixture for the PIANO Phase-1 contract smoke test.

The fixture is not a scientific agent policy. It exists only to prove that Resonance
World can consume mechanically scored proposal/acknowledgement records without
reconstructing Field-private cognition.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from resonance.agents import (
    ActionRequest,
    ActionType,
    AgentObservation,
    DefaultPolicyGateway,
    InMemoryDecisionEventStore,
    OutcomeStatus,
)

from .piano_agent_runtime import PianoAgentRuntime, PianoProposal

_AGENT_ID = UUID("00000000-0000-0000-0000-000000000501")
_START = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _embedding() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 1535


class _SearchOnlyTraceRepository:
    def search(self, query_embedding, *, at, limit=10, weights=None):
        del query_embedding, at, limit, weights
        return ()


class _FixturePolicy:
    def __init__(self, arm: str) -> None:
        if arm not in {"control", "treatment"}:
            raise ValueError("arm must be control or treatment")
        self._arm = arm

    def propose(self, agent_id, context) -> PianoProposal:
        del agent_id
        step = int(context.observation.metadata["fixture_step"])
        if self._arm == "treatment":
            return PianoProposal(
                intention="Inspect the available Field evidence before making a claim.",
                speech="I will inspect the available evidence before reporting success.",
                action=ActionRequest(ActionType.OBSERVE, confidence=0.8),
                intended_action=ActionType.OBSERVE,
                speech_action=ActionType.OBSERVE,
                speech_claims_success=False,
                expected_outcome_status=OutcomeStatus.SUCCEEDED,
                expected_effects={"retrieved_count": 0},
            )

        if step == 0:
            return PianoProposal(
                intention="Inspect the available Field evidence.",
                speech="I will use an external tool instead.",
                action=ActionRequest(ActionType.OBSERVE, confidence=0.8),
                intended_action=ActionType.OBSERVE,
                speech_action=ActionType.REQUEST_TOOL,
                speech_claims_success=False,
                expected_outcome_status=OutcomeStatus.SUCCEEDED,
            )
        if step == 1:
            return PianoProposal(
                intention="Use an external tool.",
                speech="I will inspect the local evidence.",
                action=ActionRequest(ActionType.OBSERVE, confidence=0.8),
                intended_action=ActionType.REQUEST_TOOL,
                speech_action=ActionType.OBSERVE,
                speech_claims_success=False,
                expected_outcome_status=OutcomeStatus.SUCCEEDED,
            )
        return PianoProposal(
            intention="Use an external tool and report the result.",
            speech="The external search succeeded and I have the result.",
            action=ActionRequest(ActionType.REQUEST_TOOL, {"tool": "fixture-search"}, confidence=0.9),
            intended_action=ActionType.REQUEST_TOOL,
            speech_action=ActionType.REQUEST_TOOL,
            speech_claims_success=True,
            expected_outcome_status=OutcomeStatus.SUCCEEDED,
        )


def run_fixture(arm: str) -> dict[str, object]:
    runtime = PianoAgentRuntime(
        traces=_SearchOnlyTraceRepository(),
        events=InMemoryDecisionEventStore(),
        gateway=DefaultPolicyGateway(),
        policy=_FixturePolicy(arm),
    )
    records: list[dict[str, object]] = []
    for step in range(3):
        observation = AgentObservation(
            trigger=f"piano-phase1-fixture-{step}",
            observed_at=_START + timedelta(seconds=step),
            query_embedding=_embedding(),
            metadata={"fixture_step": step},
        )
        records.append(runtime.step(_AGENT_ID, observation).to_world_record())
    return {
        "schema": "resonance-field-piano-fixture-v0.1",
        "arm": arm,
        "scientific_claim_allowed": False,
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", required=True, choices=("control", "treatment"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(run_fixture(args.arm), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
