"""Instrumentation runner for the stochastic Epistemic Substrate replication."""

from __future__ import annotations

import hashlib
import random
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .epistemic_substrate_config import EpistemicSubstrateConfig
from .llm_epistemic_agents import (
    EvaluatorClient,
    EvaluatorTask,
    FrozenSource,
    ProducerClient,
    ProducerTask,
    SubstrateRetrievalTool,
    run_producers,
)
from .llm_epistemic_config import LLMEpistemicConfig
from .llm_epistemic_corpus import CorpusManifest, ResearchCaseManifest, verify_source_file
from .llm_epistemic_replay import make_replayed_substrate, replay_event_log
from .llm_epistemic_scoring import score_case

ARMS = ("pile", "shared_memory", "provenance_graph", "resonance_field")


def _arm_order(case_id: str, draw_id: int) -> tuple[str, ...]:
    digest = hashlib.sha256(f"{case_id}:{draw_id}".encode()).digest()
    seed = int.from_bytes(digest[:8], "big")
    arms = list(ARMS)
    random.Random(seed).shuffle(arms)
    return tuple(arms)


def _frozen_sources(manifest: CorpusManifest, corpus_root: str | Path) -> dict[str, FrozenSource]:
    root = Path(corpus_root)
    sources: dict[str, FrozenSource] = {}
    for entry in manifest.sources:
        if entry.local_path is None:
            raise ValueError(f"frozen source {entry.source_id} has no local_path")
        verify_source_file(entry, root)
        text = (root / entry.local_path).read_text()
        sources[entry.source_id] = FrozenSource(
            source_id=entry.source_id,
            sha256=entry.sha256,
            text=text,
            observed_at=entry.controlled_evidence_time,
        )
    return sources


def _producer_tasks(
    case: ResearchCaseManifest,
    sources: dict[str, FrozenSource],
) -> tuple[ProducerTask, ...]:
    tasks: list[ProducerTask] = []
    for producer_id, source_ids in case.producer_source_allocations:
        tasks.append(
            ProducerTask(
                case_id=case.case_id,
                producer_id=producer_id,
                sources=tuple(sources[source_id] for source_id in source_ids),
                research_goal=case.question,
            )
        )
    return tuple(tasks)


def _event_log_mapping(event_log: Any) -> dict[str, Any]:
    """Return the exact canonical event-log payload used for hashing and replay."""
    return {
        "schema_version": event_log.schema_version,
        "case_id": event_log.case_id,
        "events": [event.canonical_mapping() for event in event_log.events],
    }


def _observed_producer_models(event_log: Any) -> list[str]:
    values = {
        str(event.metadata["response_model"])
        for event in event_log.events
        if event.metadata.get("response_model")
    }
    return sorted(values)


def _producer_event_counts(
    case: ResearchCaseManifest,
    event_log: Any,
) -> dict[str, int]:
    observed = Counter(event.producer_id for event in event_log.events)
    return {
        producer_id: observed.get(producer_id, 0)
        for producer_id, _source_ids in case.producer_source_allocations
    }


def _enforce_minimum_producer_deposits(
    case: ResearchCaseManifest,
    event_log: Any,
) -> dict[str, int]:
    counts = _producer_event_counts(case, event_log)
    minimum = case.minimum_events_per_producer
    if minimum is None:
        return counts
    shortfalls = {
        producer_id: count
        for producer_id, count in counts.items()
        if count < minimum
    }
    if shortfalls:
        details = ", ".join(
            f"{producer_id}={count}" for producer_id, count in sorted(shortfalls.items())
        )
        raise ValueError(
            "producer deposit floor not met before substrate replay: "
            f"minimum={minimum}; {details}"
        )
    return counts


def _temporal_conflict_keys(event_log: Any) -> tuple[dict[str, Any], ...]:
    grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for event in event_log.events:
        grouped[(event.subject, event.predicate)].append(event)

    conflicts: list[dict[str, Any]] = []
    for (subject, predicate), events in sorted(grouped.items()):
        producers = {event.producer_id for event in events}
        observed_times = {event.observed_at for event in events}
        objects = {event.object for event in events}
        if len(producers) < 2 or len(observed_times) < 2 or len(objects) < 2:
            continue
        conflicts.append(
            {
                "subject": subject,
                "predicate": predicate,
                "objects": sorted(objects),
                "producer_ids": sorted(producers),
                "observed_at": sorted(observed_times),
                "event_ids": sorted(event.event_id for event in events),
            }
        )
    return tuple(conflicts)


def _enforce_temporal_conflict_floor(
    case: ResearchCaseManifest,
    event_log: Any,
) -> tuple[dict[str, Any], ...]:
    conflicts = _temporal_conflict_keys(event_log)
    minimum = case.minimum_temporal_conflict_keys
    if minimum is not None and len(conflicts) < minimum:
        raise ValueError(
            "temporal conflict-key floor not met before substrate replay: "
            f"minimum={minimum}; observed={len(conflicts)}"
        )
    return conflicts


def run_instrumentation_case(
    case: ResearchCaseManifest,
    manifest: CorpusManifest,
    corpus_root: str | Path,
    campaign_config: LLMEpistemicConfig,
    substrate_config: EpistemicSubstrateConfig,
    producer_client: ProducerClient,
    evaluator_client: EvaluatorClient,
) -> dict[str, Any]:
    if case.cohort != "instrumentation":
        raise PermissionError("instrumentation runner cannot execute a confirmatory case")
    sources = _frozen_sources(manifest, corpus_root)
    event_log = run_producers(_producer_tasks(case, sources), producer_client)
    producer_event_counts = _enforce_minimum_producer_deposits(case, event_log)
    temporal_conflict_keys = _enforce_temporal_conflict_floor(case, event_log)
    evidence = replay_event_log(event_log, substrate_config)
    event_log_sha256 = event_log.sha256()
    draws: list[dict[str, Any]] = []
    evaluator_models: set[str] = set()

    for draw_id in range(1, campaign_config.evaluator_draws + 1):
        order = _arm_order(case.case_id, draw_id)
        arm_results: dict[str, Any] = {}
        for arm in order:
            substrate = make_replayed_substrate(arm, evidence, substrate_config)
            tool = SubstrateRetrievalTool(event_log, evidence, substrate)
            answer = evaluator_client.evaluate(
                EvaluatorTask(
                    case_id=case.case_id,
                    question_id=case.held_out_question_id,
                    question=case.question,
                    draw_id=draw_id,
                ),
                tool,
            )
            evaluator_models.add(answer.model)
            score = score_case(case, answer, event_log)
            arm_results[arm] = {
                "answer": asdict(answer),
                "score": asdict(score),
                "event_log_sha256": event_log_sha256,
            }
        draws.append(
            {
                "draw_id": draw_id,
                "arm_order": list(order),
                "arms": arm_results,
            }
        )

    return {
        "case_id": case.case_id,
        "cohort": "instrumentation",
        "inferential": False,
        "event_log_sha256": event_log_sha256,
        "event_count": len(event_log.events),
        "event_log": _event_log_mapping(event_log),
        "producer_ids": list(event_log.producer_ids()),
        "producer_event_counts": producer_event_counts,
        "temporal_conflict_key_count": len(temporal_conflict_keys),
        "temporal_conflict_keys": list(temporal_conflict_keys),
        "observed_producer_models": _observed_producer_models(event_log),
        "observed_evaluator_models": sorted(evaluator_models),
        "draws": draws,
    }


def run_instrumentation(
    manifest: CorpusManifest,
    corpus_root: str | Path,
    campaign_config: LLMEpistemicConfig,
    substrate_config: EpistemicSubstrateConfig,
    producer_client: ProducerClient,
    evaluator_client: EvaluatorClient,
) -> dict[str, Any]:
    cases = manifest.cases_for_instrumentation()
    if len(cases) > campaign_config.instrumentation_case_count:
        raise ValueError("instrumentation manifest exceeds frozen case-count ceiling")
    results = [
        run_instrumentation_case(
            case,
            manifest,
            corpus_root,
            campaign_config,
            substrate_config,
            producer_client,
            evaluator_client,
        )
        for case in cases
    ]
    return {
        "campaign": campaign_config.name,
        "cohort": "instrumentation",
        "inferential": False,
        "confirmatory_access": False,
        "confirmatory_cases_evaluated": False,
        "manifest_sha256": manifest.sha256(),
        "case_count": len(results),
        "cases": results,
    }


__all__ = ["ARMS", "run_instrumentation", "run_instrumentation_case"]
