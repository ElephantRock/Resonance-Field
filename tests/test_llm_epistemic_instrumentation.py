from __future__ import annotations

import hashlib
import json
from pathlib import Path

from resonance.experiments.epistemic_substrate_config import load_epistemic_substrate_config
from resonance.experiments.llm_epistemic_agents import (
    EvaluatorAnswer,
    EvaluatorTask,
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
STALE_AT = "2019-03-21T00:00:00Z"


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
                metadata={
                    "provider": "fake",
                    "requested_model": "requested-model",
                    "response_model": "actual-producer-model",
                },
            ),
        )


class SparseProducer(FakeProducer):
    def produce(self, task: ProducerTask) -> tuple[EpistemicEvent, ...]:
        if task.producer_id == "producer-4":
            return ()
        return super().produce(task)


class TemporalConflictProducer(FakeProducer):
    def produce(self, task: ProducerTask) -> tuple[EpistemicEvent, ...]:
        source = task.sources[0]
        base = super().produce(task)[0]
        default_value = "legacy" if task.producer_id == "producer-1" else "current"
        conflict = EpistemicEvent(
            event_id=f"{task.case_id}:{task.producer_id}:conflict",
            case_id=task.case_id,
            producer_id=task.producer_id,
            source_id=source.source_id,
            source_sha256=source.sha256,
            subject="feature-x",
            predicate="default_is",
            object=default_value,
            confidence=0.9,
            observed_at=source.observed_at,
            metadata={
                "provider": "fake",
                "requested_model": "requested-model",
                "response_model": "actual-producer-model",
            },
        )
        return (base, conflict)


class FakeEvaluator:
    def evaluate(self, task: EvaluatorTask, tool: SubstrateRetrievalTool) -> EvaluatorAnswer:
        retrieval = tool.retrieve("system-x", "supports", 12)
        return EvaluatorAnswer(
            answer="component-y",
            confidence=0.9,
            cited_event_ids=tuple(event.event_id for event in retrieval.events),
            retrieval_operation_units=retrieval.operation_cost,
            model="actual-evaluator-model",
        )


def _manifest(
    tmp_path: Path,
    *,
    minimum_events_per_producer: int | None = None,
    minimum_temporal_conflict_keys: int | None = None,
    temporal_sources: bool = False,
) -> CorpusManifest:
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
                evidence_observed_at=(STALE_AT if temporal_sources and index == 1 else None),
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
        minimum_events_per_producer=minimum_events_per_producer,
        minimum_temporal_conflict_keys=minimum_temporal_conflict_keys,
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
    assert case["event_count"] == len(case["event_log"]["events"])
    canonical = json.dumps(
        case["event_log"], sort_keys=True, separators=(",", ":")
    ).encode()
    assert hashlib.sha256(canonical).hexdigest() == case["event_log_sha256"]
    assert case["producer_event_counts"] == {
        "producer-1": 1,
        "producer-2": 1,
        "producer-3": 1,
        "producer-4": 1,
    }
    assert case["temporal_conflict_key_count"] == 0
    assert case["observed_producer_models"] == ["actual-producer-model"]
    assert case["observed_evaluator_models"] == ["actual-evaluator-model"]
    for draw in case["draws"]:
        assert set(draw["arms"]) == {
            "pile",
            "shared_memory",
            "provenance_graph",
            "resonance_field",
        }
        assert all(arm["score"]["correct"] == 1.0 for arm in draw["arms"].values())


def test_runner_rejects_declared_producer_deposit_shortfall_before_replay(
    tmp_path: Path,
) -> None:
    campaign = load_llm_epistemic_config(CAMPAIGN_CONFIG)
    parent, _ = load_epistemic_substrate_config(PARENT_CONFIG)
    manifest = _manifest(tmp_path, minimum_events_per_producer=1)

    try:
        run_instrumentation(
            manifest,
            tmp_path,
            campaign,
            parent,
            SparseProducer(),
            FakeEvaluator(),
        )
    except ValueError as exc:
        message = str(exc)
        assert "producer deposit floor" in message
        assert "producer-4=0" in message
    else:
        raise AssertionError("producer deposit shortfall reached substrate replay")


def test_runner_rejects_missing_temporal_conflict_before_replay(tmp_path: Path) -> None:
    campaign = load_llm_epistemic_config(CAMPAIGN_CONFIG)
    parent, _ = load_epistemic_substrate_config(PARENT_CONFIG)
    manifest = _manifest(
        tmp_path,
        minimum_events_per_producer=1,
        minimum_temporal_conflict_keys=1,
        temporal_sources=True,
    )

    try:
        run_instrumentation(
            manifest,
            tmp_path,
            campaign,
            parent,
            FakeProducer(),
            FakeEvaluator(),
        )
    except ValueError as exc:
        assert "temporal conflict-key floor" in str(exc)
    else:
        raise AssertionError("missing temporal conflict reached substrate replay")


def test_runner_records_cross_time_opposing_claim_key(tmp_path: Path) -> None:
    campaign = load_llm_epistemic_config(CAMPAIGN_CONFIG)
    parent, _ = load_epistemic_substrate_config(PARENT_CONFIG)
    manifest = _manifest(
        tmp_path,
        minimum_events_per_producer=1,
        minimum_temporal_conflict_keys=1,
        temporal_sources=True,
    )

    result = run_instrumentation(
        manifest,
        tmp_path,
        campaign,
        parent,
        TemporalConflictProducer(),
        FakeEvaluator(),
    )

    case = result["cases"][0]
    assert case["temporal_conflict_key_count"] == 1
    conflict = case["temporal_conflict_keys"][0]
    assert conflict["subject"] == "feature-x"
    assert conflict["predicate"] == "default_is"
    assert conflict["objects"] == ["current", "legacy"]
    assert conflict["observed_at"] == [STALE_AT, OBSERVED_AT]
