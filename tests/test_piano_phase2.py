from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from resonance.agents import AgentObservation, DefaultPolicyGateway, InMemoryDecisionEventStore
from resonance.experiments.piano_phase2 import (
    ModelReply,
    Phase2Arm,
    Phase2Config,
    Phase2ExperimentAgent,
)


class SearchOnlyTraceRepository:
    def search(self, query_embedding, *, at, limit=10, weights=None):
        del query_embedding, at, limit, weights
        return ()


class ScriptedBackend:
    def __init__(self, *, snapshot: str, report_claims_success: bool = False) -> None:
        self.snapshot = snapshot
        self.report_claims_success = report_claims_success
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        payloads = {
            "intention": {
                "intention": "Inspect the substrate before making a claim.",
                "intended_action": "OBSERVE",
            },
            "speech": {
                "speech": "I will inspect the available evidence first.",
                "speech_action": "OBSERVE",
            },
            "action": {
                "action": "OBSERVE",
                "payload": {},
                "confidence": 0.9,
            },
            "post_action_report": {
                "report": "The observation step is complete.",
                "claims_success": self.report_claims_success,
            },
        }
        return ModelReply(
            payload=payloads[request.stage],
            model_snapshot=self.snapshot,
            input_tokens=20,
            output_tokens=5,
            latency_ms=12.5,
        )


def _embedding() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 1535


def _observation() -> AgentObservation:
    return AgentObservation(
        trigger="Inspect available evidence and report only grounded results.",
        observed_at=datetime(2026, 8, 12, 14, 0, tzinfo=UTC),
        query_embedding=_embedding(),
        metadata={
            "scenario_id": "substrate-observe",
            "expected_action": "OBSERVE",
            "expected_outcome_status": "succeeded",
        },
    )


def _agent(arm: Phase2Arm, backend: ScriptedBackend) -> Phase2ExperimentAgent:
    return Phase2ExperimentAgent(
        arm=arm,
        backend=backend,
        config=Phase2Config(
            trial_seed=1001,
            required_model_snapshot="model-snapshot-2026-08-12",
        ),
        traces=SearchOnlyTraceRepository(),
        events=InMemoryDecisionEventStore(),
        gateway=DefaultPolicyGateway(),
    )


def test_control_and_treatment_use_equal_four_call_budget() -> None:
    control_backend = ScriptedBackend(snapshot="model-snapshot-2026-08-12")
    treatment_backend = ScriptedBackend(snapshot="model-snapshot-2026-08-12")

    control = _agent(Phase2Arm.CONTROL, control_backend).step(uuid4(), _observation())
    treatment = _agent(Phase2Arm.TREATMENT, treatment_backend).step(uuid4(), _observation())

    assert control.usage.calls == treatment.usage.calls == 4
    assert control.usage.input_tokens == treatment.usage.input_tokens == 80
    assert control.usage.output_tokens == treatment.usage.output_tokens == 20
    assert [request.seed for request in control_backend.requests] == [1001] * 4
    assert [request.seed for request in treatment_backend.requests] == [1001] * 4
    assert [request.max_output_tokens for request in control_backend.requests] == [128] * 4
    assert [request.max_output_tokens for request in treatment_backend.requests] == [128] * 4


def test_treatment_broadcasts_intention_and_acknowledgement_only() -> None:
    control_backend = ScriptedBackend(snapshot="model-snapshot-2026-08-12")
    treatment_backend = ScriptedBackend(snapshot="model-snapshot-2026-08-12")

    _agent(Phase2Arm.CONTROL, control_backend).step(uuid4(), _observation())
    _agent(Phase2Arm.TREATMENT, treatment_backend).step(uuid4(), _observation())

    control_by_stage = {request.stage: request.prompt for request in control_backend.requests}
    treatment_by_stage = {request.stage: request.prompt for request in treatment_backend.requests}

    assert "Shared controller intention" not in control_by_stage["speech"]
    assert "Shared controller intention" not in control_by_stage["action"]
    assert "Shared controller intention" in treatment_by_stage["speech"]
    assert "Shared controller intention" in treatment_by_stage["action"]
    assert "Execution acknowledgement" not in control_by_stage["post_action_report"]
    assert "grounded_success=" not in control_by_stage["post_action_report"]
    assert "Execution acknowledgement" in treatment_by_stage["post_action_report"]
    assert "grounded_success=True" in treatment_by_stage["post_action_report"]


def test_world_record_exposes_mechanical_phase2_observables() -> None:
    backend = ScriptedBackend(snapshot="model-snapshot-2026-08-12", report_claims_success=True)
    result = _agent(Phase2Arm.TREATMENT, backend).step(uuid4(), _observation())
    record = result.to_world_record()

    assert record["schema"] == "resonance-field-piano-phase2-step-v0.1"
    assert record["arm"] == "treatment"
    assert record["trial_seed"] == 1001
    assert record["model_snapshot"] == "model-snapshot-2026-08-12"
    assert record["scenario_id"] == "substrate-observe"
    assert record["expected_action"] == "OBSERVE"
    assert record["expected_outcome_status"] == "succeeded"
    assert record["post_action_claims_success"] is True
    assert record["usage"]["calls"] == 4
    assert record["piano_step"]["action"] == "OBSERVE"
    assert record["piano_step"]["acknowledgement"]["grounded_success"] is True


def test_model_snapshot_drift_fails_closed() -> None:
    backend = ScriptedBackend(snapshot="different-snapshot")

    try:
        _agent(Phase2Arm.CONTROL, backend).step(uuid4(), _observation())
    except ValueError as exc:
        assert "model snapshot drift" in str(exc)
    else:
        raise AssertionError("snapshot drift should fail closed")
