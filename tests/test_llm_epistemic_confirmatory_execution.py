from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from resonance.experiments.epistemic_substrate_config import load_epistemic_substrate_config
from resonance.experiments.llm_epistemic_agents import (
    EvaluatorAnswer,
    EvaluatorTask,
    ProducerTask,
    SubstrateRetrievalTool,
)
from resonance.experiments.llm_epistemic_config import load_llm_epistemic_config
from resonance.experiments.llm_epistemic_confirmatory_execution import (
    ConfirmatoryProtocolError,
    aggregate_confirmatory_results,
    run_confirmatory_case,
)
from resonance.experiments.llm_epistemic_confirmatory_design import load_confirmatory_design
from resonance.experiments.llm_epistemic_corpus import (
    CorpusManifest,
    ResearchCaseManifest,
    SemanticAnswerRequirements,
    SourceManifestEntry,
)
from resonance.experiments.llm_epistemic_events import EpistemicEvent

CAMPAIGN_CONFIG = Path("configs/experiments/llm-epistemic-substrate-142-145.json")
PARENT_CONFIG = Path("configs/experiments/epistemic-substrate-138-141.json")
DESIGN_CONFIG = Path(
    "configs/experiments/llm-epistemic-substrate-142-145-confirmatory-design.json"
)
OBSERVED_AT = "2026-08-12T12:00:00Z"
SEAL_SHA = "a" * 64


class ConfirmatoryFakeProducer:
    def produce(self, task: ProducerTask) -> tuple[EpistemicEvent, ...]:
        source = task.sources[0]
        return (
            EpistemicEvent(
                event_id=f"{task.case_id}:{task.producer_id}:1",
                case_id=task.case_id,
                producer_id=task.producer_id,
                source_id=source.source_id,
                source_sha256=source.sha256,
                subject="system-x",
                predicate="supports",
                object="component-y",
                confidence=0.9,
                observed_at=source.observed_at,
                metadata={
                    "provider": "zai",
                    "requested_model": "glm-5.1",
                    "response_model": "glm-5.2",
                    "base_url": "https://api.z.ai/api/coding/paas/v4",
                },
            ),
        )


class SparseConfirmatoryProducer(ConfirmatoryFakeProducer):
    def produce(self, task: ProducerTask) -> tuple[EpistemicEvent, ...]:
        if task.producer_id == "producer-4":
            return ()
        return super().produce(task)


class ConfirmatoryFakeEvaluator:
    def evaluate(self, task: EvaluatorTask, tool: SubstrateRetrievalTool) -> EvaluatorAnswer:
        retrieval = tool.retrieve("system-x", "supports", 12)
        return EvaluatorAnswer(
            answer="component-y; mode-z",
            confidence=0.9,
            cited_event_ids=tuple(event.event_id for event in retrieval.events),
            retrieval_operation_units=retrieval.operation_cost,
            model="glm-5.2",
        )


class FailingConfirmatoryEvaluator:
    def evaluate(self, task: EvaluatorTask, tool: SubstrateRetrievalTool) -> EvaluatorAnswer:
        raise RuntimeError("synthetic post-replay provider failure")


def _manifest(tmp_path: Path) -> CorpusManifest:
    sources: list[SourceManifestEntry] = []
    allocations: list[tuple[str, tuple[str, ...]]] = []
    source_ids: list[str] = []
    for index in range(1, 5):
        source_id = f"source-{index}"
        content = f"confirmatory frozen source {index}\n".encode()
        path = tmp_path / f"source-{index}.txt"
        path.write_bytes(content)
        sources.append(
            SourceManifestEntry(
                source_id=source_id,
                sha256=hashlib.sha256(content).hexdigest(),
                media_type="text/plain",
                title=f"Source {index}",
                acquired_at=OBSERVED_AT,
                local_path=path.name,
                canonical_url=f"https://example.invalid/source-{index}",
                evidence_observed_at=OBSERVED_AT,
                upstream_project_id="project-x",
                upstream_organization_id="organization-x",
            )
        )
        allocations.append((f"producer-{index}", (source_id,)))
        source_ids.append(source_id)
    case = ResearchCaseManifest(
        case_id="confirmatory-case-1",
        cohort="confirmatory",
        source_ids=tuple(source_ids),
        producer_source_allocations=tuple(allocations),
        held_out_question_id="confirmatory-question-1",
        question="Return the component and mode in order.",
        accepted_answers=("component-y; mode-z",),
        required_source_ids=tuple(source_ids[:3]),
        semantic_answer_requirements=SemanticAnswerRequirements(
            required_slots=(("component-y",), ("mode-z",)),
        ),
        minimum_events_per_producer=1,
        domain_id="programming_languages_and_runtimes",
        challenge_type="distributed_synthesis",
    )
    return CorpusManifest(manifest_version="1.0", sources=tuple(sources), cases=(case,))


def _controls():
    campaign = load_llm_epistemic_config(CAMPAIGN_CONFIG)
    parent, _ = load_epistemic_substrate_config(PARENT_CONFIG)
    return campaign, parent


def test_confirmatory_case_runs_all_four_arms_from_one_event_log(tmp_path: Path) -> None:
    campaign, parent = _controls()
    manifest = _manifest(tmp_path)
    result = run_confirmatory_case(
        case=manifest.cases[0],
        manifest=manifest,
        corpus_root=tmp_path,
        campaign=campaign,
        substrate_config=parent,
        producer_client=ConfirmatoryFakeProducer(),
        evaluator_client=ConfirmatoryFakeEvaluator(),
        seal_sha256=SEAL_SHA,
    )

    assert result["status"] == "evaluable"
    assert result["seal_sha256"] == SEAL_SHA
    assert len(result["draws"]) == 5
    hashes = {
        arm_result["event_log_sha256"]
        for draw in result["draws"]
        for arm_result in draw["arms"].values()
    }
    assert hashes == {result["event_log_sha256"]}
    assert result["observed_producer_models"] == ["glm-5.2"]
    assert result["observed_evaluator_models"] == ["glm-5.2"]
    assert all(
        arm_result["score"]["correct"] == 1.0
        for draw in result["draws"]
        for arm_result in draw["arms"].values()
    )


def test_pre_replay_producer_gate_is_allowed_confirmatory_attrition(tmp_path: Path) -> None:
    campaign, parent = _controls()
    manifest = _manifest(tmp_path)
    result = run_confirmatory_case(
        case=manifest.cases[0],
        manifest=manifest,
        corpus_root=tmp_path,
        campaign=campaign,
        substrate_config=parent,
        producer_client=SparseConfirmatoryProducer(),
        evaluator_client=ConfirmatoryFakeEvaluator(),
        seal_sha256=SEAL_SHA,
    )

    assert result["status"] == "pre_replay_gate_failure"
    assert result["gate"] == "minimum_events_per_producer"
    assert result["replay_attempted"] is False
    assert result["evaluator_execution_attempted"] is False
    assert result["outcome_bearing_treatment_execution"] is False
    assert result["draws"] == []


def test_post_replay_evaluator_failure_invalidates_instead_of_dropping_case(tmp_path: Path) -> None:
    campaign, parent = _controls()
    manifest = _manifest(tmp_path)
    with pytest.raises(ConfirmatoryProtocolError, match="post-replay"):
        run_confirmatory_case(
            case=manifest.cases[0],
            manifest=manifest,
            corpus_root=tmp_path,
            campaign=campaign,
            substrate_config=parent,
            producer_client=ConfirmatoryFakeProducer(),
            evaluator_client=FailingConfirmatoryEvaluator(),
            seal_sha256=SEAL_SHA,
        )


def test_duplicate_case_results_are_rejected_before_any_outcome_selection(tmp_path: Path) -> None:
    campaign, _parent = _controls()
    design = load_confirmatory_design(DESIGN_CONFIG)
    manifest = _manifest(tmp_path)
    duplicate = {"case_id": "confirmatory-case-1", "status": "evaluable", "seal_sha256": SEAL_SHA}
    with pytest.raises(ConfirmatoryProtocolError, match="duplicate"):
        aggregate_confirmatory_results(
            results=(duplicate, duplicate),
            manifest=manifest,
            campaign=campaign,
            design=design,
            seal_sha256=SEAL_SHA,
        )
