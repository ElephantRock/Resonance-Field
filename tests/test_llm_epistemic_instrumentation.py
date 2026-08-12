from __future__ import annotations

import hashlib
from pathlib import Path

from resonance.experiments.epistemic_substrate_config import load_epistemic_substrate_config
from resonance.experiments.llm_epistemic_agents import (
    EvaluatorAnswer,
    EvaluatorTask,
    FrozenSource,
    ProducerTask,
    SubstrateRetrievalTool,
)
from resonance.experiments.llm_epistemic_config import load_llm_epistemic_config
from resonance.experiments.llm_epistemic_corpus import (
    CorpusManifest,
    ResearchCaseManifest,
    SourceManifestEntry,
)
from resonance.experiments.llm_epistemic_events import EpistemicEvent
from resonance.experiments.llm_epistemic_instrumentation import run_instrumentation

CAMPAIGN_CONFIG = Path("configs/experiments/llm-epistemic-substrate-142-145.json")
PARENT_CONFIG = Path("configs/experiments/epistemic-substrate-138-141.json")
OBSERVED_AT = "2026-08-12T12:00:00Z"


class FakeProducer:
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
            ),
        )


class FakeEvaluator:
    def evaluate(self, task: EvaluatorTask, tool: SubstrateRetrievalTool) -> EvaluatorAnswer:
        retrieval = tool.retrieve("system-x", "supports", 12)
        return EvaluatorAnswer(
            answer="component-y",
            confidence=0.9,
            cited_event_ids=tuple(event.event_id for event in retrieval.events),
            retrieval_operation_units=retrieval.operation_cost,
            model="fake-model",
        )


def _manifest(tmp_path: Path) -> CorpusManifest:
    sources: list[SourceManifestEntry] = []
    allocations: list[tuple[str, tuple[str, ...]]] = []
    source_ids: list[str] = []
    for index in range(1, 5):
        source_id = f"source-{index}"
        content = f"frozen source {index}\n".encode()
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
            )
        )
        allocations.append((f"producer-{index}", (source_id,)))
        source_ids.append(source_id)
    case = ResearchCaseManifest(
        case_id="case-1",
        cohort="instrumentation",
        source_ids=tuple(source_ids),
        producer_source_allocations=tuple(allocations),
        held_out_question_id="question-1",
        question="Which component is supported by the distributed evidence?",
        accepted_answers=("component-y",),
        required_source_ids=("source-1", "source-2"),
    )
    return CorpusManifest(manifest_version="1.0", sources=tuple(sources), cases=(case,))


def test_runner_reuses_one_event_log_across_all_arms_and_draws(tmp_path: Path) -> None:
    campaign = load_llm_epistemic_config(CAMPAIGN_CONFIG)
    parent, _ = load_epistemic_substrate_config(PARENT_CONFIG)
    manifest = _manifest(tmp_path)

    result = run_instrumentation(
        manifest,
        tmp_path,
        campaign,
        parent,
        FakeProducer(),
        FakeEvaluator(),
    )

    assert result["inferential"] is False
    assert result["confirmatory_access"] is False
    assert result["confirmatory_cases_evaluated"] is False
    assert result["case_count"] == 1
    case = result["cases"][0]
    assert len(case["draws"]) == 5
    hashes = {
        arm_result["event_log_sha256"]
        for draw in case["draws"]
        for arm_result in draw["arms"].values()
    }
    assert hashes == {case["event_log_sha256"]}
    for draw in case["draws"]:
        assert set(draw["arms"]) == {
            "pile",
            "shared_memory",
            "provenance_graph",
            "resonance_field",
        }
        assert all(arm["score"]["correct"] == 1.0 for arm in draw["arms"].values())
