"""Replay canonical LLM epistemic events through the validated 138–141 substrates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .epistemic_substrate_campaign import (
    Claim,
    PileSubstrate,
    ProvenanceGraphSubstrate,
    ResonanceFieldSubstrate,
    SharedMemorySubstrate,
    Substrate,
    _activation,
)
from .epistemic_substrate_config import EpistemicSubstrateConfig
from .llm_epistemic_events import EpistemicEventLog


@dataclass(frozen=True, slots=True)
class ReplayIndex:
    entity_to_id: dict[str, int]
    relation_to_id: dict[str, int]
    producer_to_id: dict[str, int]
    source_to_id: dict[str, int]
    claim_to_event_id: dict[int, str]


@dataclass(frozen=True, slots=True)
class ReplayedEvidence:
    event_log_sha256: str
    claims: tuple[Claim, ...]
    reports: tuple[tuple[Claim, ...], ...]
    index: ReplayIndex


def _timestamp(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _normalized_epochs(event_log: EpistemicEventLog, final_epoch: int) -> dict[str, int]:
    values = {event.event_id: _timestamp(event.observed_at) for event in event_log.events}
    low = min(values.values())
    high = max(values.values())
    if high == low:
        return {event_id: final_epoch for event_id in values}
    return {
        event_id: round((value - low) * final_epoch / (high - low))
        for event_id, value in values.items()
    }


def replay_event_log(
    event_log: EpistemicEventLog,
    substrate_config: EpistemicSubstrateConfig,
) -> ReplayedEvidence:
    """Convert one substrate-neutral event log into the Claim representation used by 138–141."""
    event_log.validate()
    entities = sorted(
        {event.subject for event in event_log.events}
        | {event.object for event in event_log.events}
    )
    relations = sorted({event.predicate for event in event_log.events})
    producers = sorted({event.producer_id for event in event_log.events})
    sources = sorted({event.source_id for event in event_log.events})
    entity_to_id = {value: index for index, value in enumerate(entities)}
    relation_to_id = {value: index for index, value in enumerate(relations)}
    producer_to_id = {value: index for index, value in enumerate(producers)}
    source_to_id = {value: index for index, value in enumerate(sources)}
    epochs = _normalized_epochs(event_log, substrate_config.final_epoch)

    ordered_events = sorted(event_log.events, key=lambda event: (event.observed_at, event.event_id))
    claims: list[Claim] = []
    reports: list[list[Claim]] = [[] for _ in producers]
    claim_to_event_id: dict[int, str] = {}
    for claim_id, event in enumerate(ordered_events):
        claim = Claim(
            claim_id=claim_id,
            subject=entity_to_id[event.subject],
            relation=relation_to_id[event.predicate],
            object=entity_to_id[event.object],
            epoch=epochs[event.event_id],
            producer_id=producer_to_id[event.producer_id],
            packet_id=source_to_id[event.source_id],
        )
        claims.append(claim)
        reports[claim.producer_id].append(claim)
        claim_to_event_id[claim_id] = event.event_id

    index = ReplayIndex(
        entity_to_id=entity_to_id,
        relation_to_id=relation_to_id,
        producer_to_id=producer_to_id,
        source_to_id=source_to_id,
        claim_to_event_id=claim_to_event_id,
    )
    return ReplayedEvidence(
        event_log_sha256=event_log.sha256(),
        claims=tuple(claims),
        reports=tuple(tuple(report) for report in reports),
        index=index,
    )


def make_replayed_substrate(
    arm: str,
    evidence: ReplayedEvidence,
    substrate_config: EpistemicSubstrateConfig,
) -> Substrate:
    if arm == "pile":
        return PileSubstrate(evidence.reports, substrate_config.pile_claim_cost)
    if arm == "shared_memory":
        return SharedMemorySubstrate(evidence.claims, substrate_config.shared_claim_cost)
    if arm == "provenance_graph":
        return ProvenanceGraphSubstrate(evidence.claims, substrate_config.graph_claim_cost)
    if arm == "resonance_field":
        return ResonanceFieldSubstrate(
            evidence.claims,
            substrate_config.graph_claim_cost,
            _activation(evidence.claims, substrate_config),
            substrate_config.contradiction_override_margin,
        )
    raise ValueError(f"unknown substrate arm: {arm}")


__all__ = ["ReplayIndex", "ReplayedEvidence", "make_replayed_substrate", "replay_event_log"]
