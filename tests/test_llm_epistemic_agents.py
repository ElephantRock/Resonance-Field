from pathlib import Path

from resonance.experiments.epistemic_substrate_config import load_epistemic_substrate_config
from resonance.experiments.llm_epistemic_agents import (
    FrozenSource,
    ProducerTask,
    SubstrateRetrievalTool,
    run_producers,
)
from resonance.experiments.llm_epistemic_events import EpistemicEvent
from resonance.experiments.llm_epistemic_replay import make_replayed_substrate, replay_event_log

PARENT_CONFIG = Path("configs/experiments/epistemic-substrate-138-141.json")
OBSERVED_AT = "2026-08-12T12:00:00Z"


class FakeProducer:
    def produce(self, task: ProducerTask) -> tuple[EpistemicEvent, ...]:
        source = task.sources[0]
        return (
            EpistemicEvent(
                event_id=f"event-{task.producer_id}",
                case_id=task.case_id,
                producer_id=task.producer_id,
                source_id=source.source_id,
                source_sha256=source.sha256,
                subject="supplier-x",
                predicate="produces",
                object="component-y",
                confidence=0.9,
                observed_at=OBSERVED_AT,
            ),
        )


def test_producers_emit_one_validated_log_then_replay() -> None:
    tasks = (
        ProducerTask(
            case_id="case-1",
            producer_id="producer-a",
            sources=(FrozenSource("source-a", "a" * 64, "source A", OBSERVED_AT),),
        ),
        ProducerTask(
            case_id="case-1",
            producer_id="producer-b",
            sources=(FrozenSource("source-b", "b" * 64, "source B", OBSERVED_AT),),
        ),
    )
    log = run_producers(tasks, FakeProducer())
    config, _ = load_epistemic_substrate_config(PARENT_CONFIG)
    evidence = replay_event_log(log, config)
    substrate = make_replayed_substrate("provenance_graph", evidence, config)
    tool = SubstrateRetrievalTool(log, evidence, substrate)
    result = tool.retrieve("supplier-x", "produces", config.max_retrieval_items_per_query)

    assert len(log.events) == 2
    assert result.complete
    assert len(result.events) == 2
    assert result.chosen_event_id in {"event-producer-a", "event-producer-b"}
    assert tool.subjects() == ("supplier-x",)
