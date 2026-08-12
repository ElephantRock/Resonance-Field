from pathlib import Path

from resonance.experiments.epistemic_substrate_config import load_epistemic_substrate_config
from resonance.experiments.llm_epistemic_events import EpistemicEvent, EpistemicEventLog
from resonance.experiments.llm_epistemic_replay import make_replayed_substrate, replay_event_log


PARENT_CONFIG = Path("configs/experiments/epistemic-substrate-138-141.json")


def _log() -> EpistemicEventLog:
    events = (
        EpistemicEvent(
            event_id="event-1",
            case_id="case-1",
            producer_id="producer-a",
            source_id="source-a",
            source_sha256="a" * 64,
            subject="supplier-x",
            predicate="produces",
            object="component-y",
            confidence=0.9,
            observed_at="2026-01-01T00:00:00Z",
        ),
        EpistemicEvent(
            event_id="event-2",
            case_id="case-1",
            producer_id="producer-b",
            source_id="source-b",
            source_sha256="b" * 64,
            subject="component-y",
            predicate="required_by",
            object="company-z",
            confidence=0.9,
            observed_at="2026-02-01T00:00:00Z",
        ),
    )
    return EpistemicEventLog(schema_version="1.0", case_id="case-1", events=events)


def test_same_event_log_replays_once_for_all_arms() -> None:
    config, _ = load_epistemic_substrate_config(PARENT_CONFIG)
    evidence = replay_event_log(_log(), config)

    assert evidence.event_log_sha256 == _log().sha256()
    assert len(evidence.claims) == 2
    assert len(evidence.reports) == 2
    for arm in ("pile", "shared_memory", "provenance_graph", "resonance_field"):
        substrate = make_replayed_substrate(arm, evidence, config)
        assert substrate is not None
