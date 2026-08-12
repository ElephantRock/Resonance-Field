"""Experiment 138 discrete causal-event lineage instrumentation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import Connection

from .auction_margin_campaign import preactivation_equal
from .auction_margin_config import AuctionMarginConfig
from .controlled_kick_dose_136 import _write_csv
from .controlled_kick_dose_campaign import (
    _all_invariants,
    campaign_environment,
    load_campaign_base,
    run_control_cell,
    run_kick_cell,
)
from .integration_campaign import _draw
from .lineage_instrumentation_config import LineageConfig

_EXPERIMENT_NUMBER = 138
_SLOT_PATTERN = re.compile(r"slot\s+(\d+)\s*$")
_STAGE_ORDER = {
    "feedback_domain_choice": 10,
    "trace_retrieval_selection": 20,
    "trace_evidence_gate": 30,
    "auction_award": 40,
    "settlement_transfer": 50,
    "success_outcome": 60,
    "practice_update": 70,
    "public_knowledge_write": 80,
}
_CHANNEL_ORDER = (
    "settlement_transfer",
    "success_outcome",
    "practice_update",
    "trace_evidence_gate",
    "trace_retrieval_selection",
    "feedback_domain_choice",
    "public_knowledge_write",
)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_value(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _slot_from_strategy(value: object) -> int:
    match = _SLOT_PATTERN.search(str(value))
    if match is None:
        raise ValueError(f"cannot recover logical slot from strategy summary: {value!r}")
    return int(match.group(1))


def _load_feedback(connection: Connection[Any], run_id: str) -> dict[int, dict[str, object]]:
    rows = connection.execute(
        """
        SELECT cycle, baseline_domain_index, generated_domain_index, feedback_strength,
               controller_mode, rolling_success_counts, feedback_branch_taken,
               feedback_probability, generation_probability, generated_domain_source,
               post_state_fingerprint
        FROM endogenous_demand_observations
        WHERE run_id = %s
        ORDER BY cycle
        """,
        (UUID(run_id),),
    ).fetchall()
    return {int(row["cycle"]): dict(row) for row in rows}


def _load_auctions(connection: Connection[Any], run_id: str) -> dict[int, list[dict[str, object]]]:
    rows = connection.execute(
        """
        SELECT o.cycle, b.bidder_agent_id, b.price, b.confidence,
               b.estimated_completion_seconds, b.strategy_summary,
               s.baseline_score, s.signal_adjustment, s.total_score,
               s.provider_label, s.components, s.selected
        FROM integration_campaign_outcomes o
        JOIN market_bids b ON b.task_id = o.task_id
        JOIN market_auction_scores s ON s.bid_id = b.bid_id
        WHERE o.run_id = %s
        ORDER BY o.cycle, b.submitted_at, b.bid_id
        """,
        (UUID(run_id),),
    ).fetchall()
    by_cycle: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_cycle[int(row["cycle"])].append(
            {
                "slot": _slot_from_strategy(row["strategy_summary"]),
                "price": int(row["price"]),
                "confidence": float(row["confidence"]),
                "estimated_completion_seconds": int(row["estimated_completion_seconds"]),
                "baseline_score": float(row["baseline_score"]),
                "signal_adjustment": float(row["signal_adjustment"]),
                "total_score": float(row["total_score"]),
                "provider_label": str(row["provider_label"] or ""),
                "components": dict(row["components"] or {}),
                "selected": bool(row["selected"]),
            }
        )
    return dict(by_cycle)


def _arm_evidence(
    connection: Connection[Any],
    cell: Mapping[str, object],
) -> dict[str, object]:
    rows = cell["rows"]
    assert isinstance(rows, Sequence)
    run_id = str(cell["run_id"])
    outcomes = {int(row["cycle"]): dict(row) for row in rows if isinstance(row, Mapping)}
    return {
        "run_id": run_id,
        "outcomes": outcomes,
        "feedback": _load_feedback(connection, run_id),
        "auctions": _load_auctions(connection, run_id),
    }


def _trace_key(row: Mapping[str, object]) -> str:
    return (
        f"trace:{int(row['cycle'])}:{int(row['winner_slot'])}:"
        f"{str(row['required_skill'])}"
    )


def _trace_catalog(
    outcomes: Mapping[int, Mapping[str, object]],
    *,
    cycle: int,
    env: Any,
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    half_life_seconds = float(env.trace_half_life_cycles) * int(env.cycle_seconds)
    created_offset = int(env.bid_deadline_seconds) + 1
    for source_cycle, row in outcomes.items():
        if source_cycle >= cycle or not bool(row["success"]):
            continue
        age_seconds = max(
            0.0,
            float((cycle - source_cycle) * int(env.cycle_seconds) - created_offset),
        )
        energy = 0.9 * (2.0 ** (-age_seconds / half_life_seconds))
        values.append(
            {
                "key": _trace_key(row),
                "source_cycle": source_cycle,
                "slot": int(row["winner_slot"]),
                "skill": str(row["required_skill"]),
                "energy": energy,
            }
        )
    return values


def _trace_view(
    outcomes: Mapping[int, Mapping[str, object]],
    *,
    cycle: int,
    required_skill: str,
    candidate_slots: Sequence[int],
    env: Any,
    retrieval_top_k: int,
) -> dict[str, object]:
    catalog = [
        item
        for item in _trace_catalog(outcomes, cycle=cycle, env=env)
        if str(item["skill"]) == required_skill
    ]
    ranked = sorted(catalog, key=lambda item: (-float(item["energy"]), str(item["key"])))
    query_limit = max(retrieval_top_k * 4, retrieval_top_k)
    queried = ranked[:query_limit]
    selected = queried[:retrieval_top_k]
    public_signal = max((float(item["energy"]) for item in queried), default=0.0)
    own: dict[int, dict[str, object]] = {}
    for slot in candidate_slots:
        relevant = [item for item in catalog if int(item["slot"]) == slot]
        best = max(relevant, key=lambda item: float(item["energy"]), default=None)
        own[slot] = {
            "signal": 0.0 if best is None else float(best["energy"]),
            "trace_key": None if best is None else str(best["key"]),
        }
    return {
        "queried": queried,
        "selected_keys": tuple(str(item["key"]) for item in selected),
        "public_signal": public_signal,
        "own": own,
    }


def _practice_before(
    outcomes: Mapping[int, Mapping[str, object]],
    *,
    cycle: int,
    slot: int,
    skill: str,
) -> int:
    return sum(
        source_cycle < cycle
        and int(row["winner_slot"]) == slot
        and str(row["required_skill"]) == skill
        for source_cycle, row in outcomes.items()
    )


def _feedback_reads(
    outcomes: Mapping[int, Mapping[str, object]],
    *,
    cycle: int,
    window: int,
) -> dict[str, object]:
    reads: dict[str, object] = {}
    for source_cycle, row in outcomes.items():
        if cycle - window <= source_cycle < cycle and bool(row["success"]):
            reads[f"feedback_success:{source_cycle}"] = {
                "domain": int(row["domain_index"]),
                "success": True,
            }
    return reads


def _candidate_confidence_provenance(
    *,
    seed: int,
    cycle: int,
    auction_rows: Sequence[Mapping[str, object]],
    trace_view: Mapping[str, object],
    env: Any,
    public_trace_confidence_weight: float,
) -> tuple[list[dict[str, object]], float]:
    own = trace_view["own"]
    assert isinstance(own, Mapping)
    public_signal = float(trace_view["public_signal"])
    result: list[dict[str, object]] = []
    max_error = 0.0
    for row in sorted(auction_rows, key=lambda item: int(item["slot"])):
        slot = int(row["slot"])
        own_value = own[slot]
        assert isinstance(own_value, Mapping)
        own_signal = float(own_value["signal"])
        gate = own_signal < 0.20
        raw = (
            float(env.confidence_base)
            + float(env.confidence_evidence_weight) * own_signal
            + public_trace_confidence_weight * public_signal
            + float(env.confidence_noise_weight) * _draw(seed, cycle, slot, "confidence")
        )
        if gate:
            raw += float(env.confidence_inflation)
        post_cap = max(0.05, min(0.98, raw))
        stored = float(row["confidence"])
        max_error = max(max_error, abs(stored - post_cap))
        result.append(
            {
                **dict(row),
                "own_trace_signal": own_signal,
                "own_trace_key": own_value["trace_key"],
                "trace_gate_below_0_20": gate,
                "public_trace_signal": public_signal,
                "pre_cap_confidence": raw,
                "post_cap_confidence": post_cap,
                "confidence_cap_active": raw > 0.98 or raw < 0.05,
            }
        )
    return result, max_error


def _state_hash_rows(
    control: Mapping[str, object],
    kick: Mapping[str, object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for key in sorted(set(control) | set(kick)):
        rows.append(
            {
                "key": key,
                "control_hash": _hash_value(control.get(key, {"absent": True})),
                "kick_hash": _hash_value(kick.get(key, {"absent": True})),
            }
        )
    return rows


def _event_id(seed: int, cycle: int, event_class: str, entity: str) -> str:
    stage = _STAGE_ORDER[event_class]
    return f"e138:{seed}:{cycle:03d}:{stage:02d}:{event_class}:{entity}"


def _build_lineage(
    *,
    seed: int,
    config: LineageConfig,
    base: Any,
    env: Any,
    control: Mapping[str, object],
    kick: Mapping[str, object],
) -> dict[str, object]:
    control_outcomes = control["outcomes"]
    kick_outcomes = kick["outcomes"]
    control_feedback = control["feedback"]
    kick_feedback = kick["feedback"]
    control_auctions = control["auctions"]
    kick_auctions = kick["auctions"]
    assert isinstance(control_outcomes, Mapping) and isinstance(kick_outcomes, Mapping)
    assert isinstance(control_feedback, Mapping) and isinstance(kick_feedback, Mapping)
    assert isinstance(control_auctions, Mapping) and isinstance(kick_auctions, Mapping)

    events: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    latest_writer: dict[str, str] = {}
    event_by_id: dict[str, dict[str, object]] = {}
    confidence_error = 0.0
    success_reconstruction_matches = True

    def add_event(
        *,
        cycle: int,
        event_class: str,
        entity: str,
        control_payload: Mapping[str, object],
        kick_payload: Mapping[str, object],
        control_reads: Mapping[str, object],
        kick_reads: Mapping[str, object],
        control_writes: Mapping[str, object],
        kick_writes: Mapping[str, object],
        root: bool = False,
    ) -> None:
        event_id = _event_id(seed, cycle, event_class, entity)
        read_keys = sorted(set(control_reads) | set(kick_reads))
        parent_keys: dict[str, list[str]] = defaultdict(list)
        if not root:
            for key in read_keys:
                parent = latest_writer.get(key)
                if parent is not None:
                    parent_keys[parent].append(key)
        parents = sorted(parent_keys)
        reachable_parent_depths = [
            int(event_by_id[parent]["depth"])
            for parent in parents
            if event_by_id[parent].get("depth") is not None
        ]
        if root:
            classification = "root"
            depth: int | None = 0
            root_reachable = True
        else:
            classification = (
                "orphan" if not parents else "single_parent" if len(parents) == 1 else "multi_parent"
            )
            depth = 1 + max(reachable_parent_depths) if reachable_parent_depths else None
            root_reachable = depth is not None
        event = {
            "seed": seed,
            "event_id": event_id,
            "cycle": cycle,
            "stage": _STAGE_ORDER[event_class],
            "event_class": event_class,
            "entity": entity,
            "classification": classification,
            "direct_parents": parents,
            "direct_parent_count": len(parents),
            "depth": depth,
            "root_reachable": root_reachable,
            "primary_window": config.primary_window[0] <= cycle <= config.primary_window[1],
            "pre_root": cycle < config.activation_cycle,
            "control_payload": dict(control_payload),
            "kick_payload": dict(kick_payload),
            "read_set": _state_hash_rows(control_reads, kick_reads),
            "write_set": _state_hash_rows(control_writes, kick_writes),
        }
        events.append(event)
        event_by_id[event_id] = event
        for parent, keys in parent_keys.items():
            edges.append(
                {
                    "seed": seed,
                    "parent_event_id": parent,
                    "child_event_id": event_id,
                    "parent_event_class": event_by_id[parent]["event_class"],
                    "child_event_class": event_class,
                    "child_cycle": cycle,
                    "state_keys": sorted(keys),
                    "primary_window": config.primary_window[0] < cycle <= config.primary_window[1],
                }
            )
        for key in sorted(set(control_writes) | set(kick_writes)):
            latest_writer[key] = event_id

    for cycle in range(config.cycles):
        c_out = control_outcomes[cycle]
        k_out = kick_outcomes[cycle]
        c_fb = control_feedback[cycle]
        k_fb = kick_feedback[cycle]
        c_auction = control_auctions[cycle]
        k_auction = kick_auctions[cycle]
        assert isinstance(c_out, Mapping) and isinstance(k_out, Mapping)
        assert isinstance(c_fb, Mapping) and isinstance(k_fb, Mapping)
        assert isinstance(c_auction, Sequence) and isinstance(k_auction, Sequence)

        c_candidates = tuple(sorted(int(row["slot"]) for row in c_auction if isinstance(row, Mapping)))
        k_candidates = tuple(sorted(int(row["slot"]) for row in k_auction if isinstance(row, Mapping)))
        if c_candidates != k_candidates:
            raise RuntimeError(f"candidate slots diverged at seed={seed} cycle={cycle}")

        c_skill = str(c_out["required_skill"])
        k_skill = str(k_out["required_skill"])
        c_traces = _trace_view(
            control_outcomes,  # type: ignore[arg-type]
            cycle=cycle,
            required_skill=c_skill,
            candidate_slots=c_candidates,
            env=env,
            retrieval_top_k=base.retrieval_top_k,
        )
        k_traces = _trace_view(
            kick_outcomes,  # type: ignore[arg-type]
            cycle=cycle,
            required_skill=k_skill,
            candidate_slots=k_candidates,
            env=env,
            retrieval_top_k=base.retrieval_top_k,
        )
        c_bid_prov, c_error = _candidate_confidence_provenance(
            seed=seed,
            cycle=cycle,
            auction_rows=c_auction,  # type: ignore[arg-type]
            trace_view=c_traces,
            env=env,
            public_trace_confidence_weight=base.public_trace_confidence_weight,
        )
        k_bid_prov, k_error = _candidate_confidence_provenance(
            seed=seed,
            cycle=cycle,
            auction_rows=k_auction,  # type: ignore[arg-type]
            trace_view=k_traces,
            env=env,
            public_trace_confidence_weight=base.public_trace_confidence_weight,
        )
        confidence_error = max(confidence_error, c_error, k_error)

        c_domain = int(c_fb["generated_domain_index"])
        k_domain = int(k_fb["generated_domain_index"])
        if c_domain != k_domain:
            c_reads = _feedback_reads(
                control_outcomes,  # type: ignore[arg-type]
                cycle=cycle,
                window=base.feedback_window,
            )
            k_reads = _feedback_reads(
                kick_outcomes,  # type: ignore[arg-type]
                cycle=cycle,
                window=base.feedback_window,
            )
            c_reads.update(
                {
                    f"draw:feedback_switch:{cycle}": _draw(seed, cycle, 0, "endogenous-demand-switch"),
                    f"draw:feedback_domain:{cycle}": _draw(seed, cycle, 0, "endogenous-demand-domain"),
                }
            )
            k_reads.update(
                {
                    f"draw:feedback_switch:{cycle}": _draw(seed, cycle, 0, "endogenous-demand-switch"),
                    f"draw:feedback_domain:{cycle}": _draw(seed, cycle, 0, "endogenous-demand-domain"),
                }
            )
            add_event(
                cycle=cycle,
                event_class="feedback_domain_choice",
                entity="domain",
                control_payload={
                    "baseline_domain": int(c_fb["baseline_domain_index"]),
                    "generated_domain": c_domain,
                    "branch_taken": bool(c_fb["feedback_branch_taken"]),
                    "rolling_success_counts": list(c_fb["rolling_success_counts"]),
                    "feedback_probability": float(c_fb["feedback_probability"]),
                    "generation_probability": float(c_fb["generation_probability"]),
                },
                kick_payload={
                    "baseline_domain": int(k_fb["baseline_domain_index"]),
                    "generated_domain": k_domain,
                    "branch_taken": bool(k_fb["feedback_branch_taken"]),
                    "rolling_success_counts": list(k_fb["rolling_success_counts"]),
                    "feedback_probability": float(k_fb["feedback_probability"]),
                    "generation_probability": float(k_fb["generation_probability"]),
                },
                control_reads=c_reads,
                kick_reads=k_reads,
                control_writes={
                    f"domain:{cycle}": c_domain,
                    f"required_skill:{cycle}": c_skill,
                },
                kick_writes={
                    f"domain:{cycle}": k_domain,
                    f"required_skill:{cycle}": k_skill,
                },
            )

        c_selected = tuple(c_traces["selected_keys"])
        k_selected = tuple(k_traces["selected_keys"])
        if c_selected != k_selected:
            c_reads = {
                str(item["key"]): float(item["energy"])
                for item in c_traces["queried"]  # type: ignore[union-attr]
            }
            k_reads = {
                str(item["key"]): float(item["energy"])
                for item in k_traces["queried"]  # type: ignore[union-attr]
            }
            c_reads[f"required_skill:{cycle}"] = c_skill
            k_reads[f"required_skill:{cycle}"] = k_skill
            add_event(
                cycle=cycle,
                event_class="trace_retrieval_selection",
                entity="public-top-k",
                control_payload={
                    "selected_trace_keys": list(c_selected),
                    "public_trace_signal": float(c_traces["public_signal"]),
                },
                kick_payload={
                    "selected_trace_keys": list(k_selected),
                    "public_trace_signal": float(k_traces["public_signal"]),
                },
                control_reads=c_reads,
                kick_reads=k_reads,
                control_writes={
                    f"trace_selection:{cycle}": list(c_selected),
                    f"public_trace_signal:{cycle}": float(c_traces["public_signal"]),
                },
                kick_writes={
                    f"trace_selection:{cycle}": list(k_selected),
                    f"public_trace_signal:{cycle}": float(k_traces["public_signal"]),
                },
            )

        c_own = c_traces["own"]
        k_own = k_traces["own"]
        assert isinstance(c_own, Mapping) and isinstance(k_own, Mapping)
        for slot in c_candidates:
            c_own_value = c_own[slot]
            k_own_value = k_own[slot]
            assert isinstance(c_own_value, Mapping) and isinstance(k_own_value, Mapping)
            c_gate = float(c_own_value["signal"]) < 0.20
            k_gate = float(k_own_value["signal"]) < 0.20
            if c_gate != k_gate:
                c_reads: dict[str, object] = {f"required_skill:{cycle}": c_skill}
                k_reads: dict[str, object] = {f"required_skill:{cycle}": k_skill}
                if c_own_value["trace_key"] is not None:
                    c_reads[str(c_own_value["trace_key"])] = float(c_own_value["signal"])
                if k_own_value["trace_key"] is not None:
                    k_reads[str(k_own_value["trace_key"])] = float(k_own_value["signal"])
                add_event(
                    cycle=cycle,
                    event_class="trace_evidence_gate",
                    entity=f"slot:{slot}",
                    control_payload={
                        "slot": slot,
                        "own_signal": float(c_own_value["signal"]),
                        "below_0_20": c_gate,
                        "allocation_inert_confidence_inflation": float(env.confidence_inflation),
                    },
                    kick_payload={
                        "slot": slot,
                        "own_signal": float(k_own_value["signal"]),
                        "below_0_20": k_gate,
                        "allocation_inert_confidence_inflation": float(env.confidence_inflation),
                    },
                    control_reads=c_reads,
                    kick_reads=k_reads,
                    control_writes={f"trace_gate:{cycle}:{slot}": c_gate},
                    kick_writes={f"trace_gate:{cycle}:{slot}": k_gate},
                )

        c_winner = int(c_out["winner_slot"])
        k_winner = int(k_out["winner_slot"])
        if c_winner != k_winner:
            c_reads: dict[str, object] = {
                f"domain:{cycle}": c_domain,
                f"required_skill:{cycle}": c_skill,
            }
            k_reads: dict[str, object] = {
                f"domain:{cycle}": k_domain,
                f"required_skill:{cycle}": k_skill,
            }
            if c_selected:
                c_reads[f"public_trace_signal:{cycle}"] = float(c_traces["public_signal"])
            if k_selected:
                k_reads[f"public_trace_signal:{cycle}"] = float(k_traces["public_signal"])
            for slot in c_candidates:
                c_value = c_own[slot]
                k_value = k_own[slot]
                assert isinstance(c_value, Mapping) and isinstance(k_value, Mapping)
                if c_value["trace_key"] is not None:
                    c_reads[str(c_value["trace_key"])] = float(c_value["signal"])
                if k_value["trace_key"] is not None:
                    k_reads[str(k_value["trace_key"])] = float(k_value["signal"])
                c_reads[f"draw:confidence:{cycle}:{slot}"] = _draw(seed, cycle, slot, "confidence")
                k_reads[f"draw:confidence:{cycle}:{slot}"] = _draw(seed, cycle, slot, "confidence")
                c_reads[f"draw:price:{cycle}:{slot}"] = _draw(seed, cycle, slot, "price")
                k_reads[f"draw:price:{cycle}:{slot}"] = _draw(seed, cycle, slot, "price")
            root = cycle == config.activation_cycle
            add_event(
                cycle=cycle,
                event_class="auction_award",
                entity="winner",
                control_payload={
                    "winner_slot": c_winner,
                    "winning_price": int(c_out["winning_price"]),
                    "candidates": c_bid_prov,
                },
                kick_payload={
                    "winner_slot": k_winner,
                    "winning_price": int(k_out["winning_price"]),
                    "candidates": k_bid_prov,
                },
                control_reads=c_reads,
                kick_reads=k_reads,
                control_writes={
                    f"winner:{cycle}": c_winner,
                    f"award:{cycle}": {
                        "winner_slot": c_winner,
                        "winning_price": int(c_out["winning_price"]),
                    },
                },
                kick_writes={
                    f"winner:{cycle}": k_winner,
                    f"award:{cycle}": {
                        "winner_slot": k_winner,
                        "winning_price": int(k_out["winning_price"]),
                    },
                },
                root=root,
            )

        c_settlement = {
            "winner_slot": c_winner,
            "winner_amount": int(c_out["winning_price"]),
            "requester_slot": cycle % int(env.agents),
            "refund": int(c_out["task_budget"]) - int(c_out["winning_price"]),
        }
        k_settlement = {
            "winner_slot": k_winner,
            "winner_amount": int(k_out["winning_price"]),
            "requester_slot": cycle % int(env.agents),
            "refund": int(k_out["task_budget"]) - int(k_out["winning_price"]),
        }
        if c_settlement != k_settlement:
            c_read = {
                f"award:{cycle}": {
                    "winner_slot": c_winner,
                    "winning_price": int(c_out["winning_price"]),
                }
            }
            k_read = {
                f"award:{cycle}": {
                    "winner_slot": k_winner,
                    "winning_price": int(k_out["winning_price"]),
                }
            }
            c_writes = {
                f"balance_delta:{cycle}:{c_winner}": int(c_out["winning_price"]),
                f"balance_delta:{cycle}:{cycle % int(env.agents)}": c_settlement["refund"],
            }
            k_writes = {
                f"balance_delta:{cycle}:{k_winner}": int(k_out["winning_price"]),
                f"balance_delta:{cycle}:{cycle % int(env.agents)}": k_settlement["refund"],
            }
            add_event(
                cycle=cycle,
                event_class="settlement_transfer",
                entity="task-settlement",
                control_payload=c_settlement,
                kick_payload=k_settlement,
                control_reads=c_read,
                kick_reads=k_read,
                control_writes=c_writes,
                kick_writes=k_writes,
            )

        c_practice = _practice_before(
            control_outcomes,  # type: ignore[arg-type]
            cycle=cycle,
            slot=c_winner,
            skill=c_skill,
        )
        k_practice = _practice_before(
            kick_outcomes,  # type: ignore[arg-type]
            cycle=cycle,
            slot=k_winner,
            skill=k_skill,
        )
        c_success_probability = min(
            float(env.maximum_success_probability),
            float(env.base_success_probability) + float(env.practice_gain) * math.sqrt(c_practice),
        )
        k_success_probability = min(
            float(env.maximum_success_probability),
            float(env.base_success_probability) + float(env.practice_gain) * math.sqrt(k_practice),
        )
        c_draw = _draw(seed, cycle, c_winner, "outcome")
        k_draw = _draw(seed, cycle, k_winner, "outcome")
        c_success_rebuilt = c_draw < c_success_probability
        k_success_rebuilt = k_draw < k_success_probability
        success_reconstruction_matches = success_reconstruction_matches and (
            c_success_rebuilt == bool(c_out["success"])
            and k_success_rebuilt == bool(k_out["success"])
        )
        if bool(c_out["success"]) != bool(k_out["success"]):
            add_event(
                cycle=cycle,
                event_class="success_outcome",
                entity="task-outcome",
                control_payload={
                    "winner_slot": c_winner,
                    "required_skill": c_skill,
                    "practice_before": c_practice,
                    "success_probability": c_success_probability,
                    "outcome_draw": c_draw,
                    "success": bool(c_out["success"]),
                },
                kick_payload={
                    "winner_slot": k_winner,
                    "required_skill": k_skill,
                    "practice_before": k_practice,
                    "success_probability": k_success_probability,
                    "outcome_draw": k_draw,
                    "success": bool(k_out["success"]),
                },
                control_reads={
                    f"winner:{cycle}": c_winner,
                    f"required_skill:{cycle}": c_skill,
                    f"practice:{c_winner}:{c_skill}": c_practice,
                    f"draw:outcome:{cycle}:{c_winner}": c_draw,
                },
                kick_reads={
                    f"winner:{cycle}": k_winner,
                    f"required_skill:{cycle}": k_skill,
                    f"practice:{k_winner}:{k_skill}": k_practice,
                    f"draw:outcome:{cycle}:{k_winner}": k_draw,
                },
                control_writes={f"success:{cycle}": bool(c_out["success"])},
                kick_writes={f"success:{cycle}": bool(k_out["success"])},
            )

        c_target = (c_winner, c_skill)
        k_target = (k_winner, k_skill)
        if c_target != k_target:
            add_event(
                cycle=cycle,
                event_class="practice_update",
                entity="practice-target",
                control_payload={
                    "target_slot": c_winner,
                    "required_skill": c_skill,
                    "before": c_practice,
                    "after": c_practice + 1,
                },
                kick_payload={
                    "target_slot": k_winner,
                    "required_skill": k_skill,
                    "before": k_practice,
                    "after": k_practice + 1,
                },
                control_reads={
                    f"winner:{cycle}": c_winner,
                    f"required_skill:{cycle}": c_skill,
                    f"practice:{c_winner}:{c_skill}": c_practice,
                },
                kick_reads={
                    f"winner:{cycle}": k_winner,
                    f"required_skill:{cycle}": k_skill,
                    f"practice:{k_winner}:{k_skill}": k_practice,
                },
                control_writes={f"practice:{c_winner}:{c_skill}": c_practice + 1},
                kick_writes={f"practice:{k_winner}:{k_skill}": k_practice + 1},
            )

        c_write = bool(c_out["success"])
        k_write = bool(k_out["success"])
        c_write_target = (c_winner, c_skill) if c_write else None
        k_write_target = (k_winner, k_skill) if k_write else None
        if (c_write, c_write_target) != (k_write, k_write_target):
            c_writes: dict[str, object] = {}
            k_writes: dict[str, object] = {}
            if c_write:
                trace_key = _trace_key(c_out)
                c_writes[trace_key] = {"initial_energy": 0.9, "source_cycle": cycle}
                c_writes[f"feedback_success:{cycle}"] = c_domain
            if k_write:
                trace_key = _trace_key(k_out)
                k_writes[trace_key] = {"initial_energy": 0.9, "source_cycle": cycle}
                k_writes[f"feedback_success:{cycle}"] = k_domain
            add_event(
                cycle=cycle,
                event_class="public_knowledge_write",
                entity="verified-outcome-trace",
                control_payload={
                    "write": c_write,
                    "winner_slot": c_winner if c_write else None,
                    "required_skill": c_skill if c_write else None,
                    "feedback_domain": c_domain if c_write else None,
                },
                kick_payload={
                    "write": k_write,
                    "winner_slot": k_winner if k_write else None,
                    "required_skill": k_skill if k_write else None,
                    "feedback_domain": k_domain if k_write else None,
                },
                control_reads={
                    f"success:{cycle}": bool(c_out["success"]),
                    f"winner:{cycle}": c_winner,
                    f"required_skill:{cycle}": c_skill,
                },
                kick_reads={
                    f"success:{cycle}": bool(k_out["success"]),
                    f"winner:{cycle}": k_winner,
                    f"required_skill:{cycle}": k_skill,
                },
                control_writes=c_writes,
                kick_writes=k_writes,
            )

    events.sort(key=lambda item: (int(item["cycle"]), int(item["stage"]), str(item["event_id"])))
    edges.sort(key=lambda item: (int(item["child_cycle"]), str(item["parent_event_id"]), str(item["child_event_id"])))
    primary_downstream = [
        event
        for event in events
        if config.activation_cycle < int(event["cycle"]) <= config.primary_window[1]
    ]
    attributable = [event for event in primary_downstream if int(event["direct_parent_count"]) > 0]
    orphans = [event for event in primary_downstream if int(event["direct_parent_count"]) == 0]
    root_reachable = [event for event in attributable if bool(event["root_reachable"])]
    capture = len(attributable) / len(primary_downstream) if primary_downstream else 0.0
    root_path_share = len(root_reachable) / len(attributable) if attributable else 1.0
    single = [event for event in attributable if event["classification"] == "single_parent"]
    multi = [event for event in attributable if event["classification"] == "multi_parent"]
    single_share = len(single) / len(attributable) if attributable else 0.0
    pre_root = [event for event in events if int(event["cycle"]) < config.activation_cycle]
    root_events = [
        event
        for event in events
        if int(event["cycle"]) == config.activation_cycle and event["event_class"] == "auction_award"
    ]
    reachable_all = [event for event in events if bool(event["root_reachable"])]
    max_depth = max((int(event["depth"]) for event in reachable_all if event["depth"] is not None), default=0)
    width_counts = Counter(int(event["depth"]) for event in reachable_all if event["depth"] is not None)
    max_width = max(width_counts.values(), default=0)
    last_cycle = max((int(event["cycle"]) for event in reachable_all), default=config.activation_cycle)

    channel_edge_counts = Counter(
        str(edge["parent_event_class"])
        for edge in edges
        if bool(edge["primary_window"])
        and str(edge["parent_event_class"]) in _CHANNEL_ORDER
    )
    return {
        "events": events,
        "edges": edges,
        "event_count": len(events),
        "primary_downstream_event_count": len(primary_downstream),
        "attributable_primary_event_count": len(attributable),
        "orphan_primary_event_count": len(orphans),
        "capture": capture,
        "root_path_share": root_path_share,
        "single_parent_count": len(single),
        "multi_parent_count": len(multi),
        "single_parent_share": single_share,
        "pre_root_event_count": len(pre_root),
        "root_event_count": len(root_events),
        "root_event_id": root_events[0]["event_id"] if len(root_events) == 1 else None,
        "confidence_reconstruction_max_abs_error": confidence_error,
        "success_reconstruction_matches": success_reconstruction_matches,
        "max_depth": max_depth,
        "max_width": max_width,
        "last_root_reachable_cycle": last_cycle,
        "lineage_lifetime_cycles": last_cycle - config.activation_cycle + 1,
        "channel_edge_counts": dict(channel_edge_counts),
    }


def _pair_calibration(
    connection: Connection[Any],
    *,
    config: LineageConfig,
    margin_config: AuctionMarginConfig,
    base: Any,
    config_hash: str,
    code_sha: str,
    seed: int,
) -> dict[str, object]:
    control = run_control_cell(
        connection,
        config=config,  # type: ignore[arg-type]
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=_EXPERIMENT_NUMBER,
        seed=seed,
    )
    kick = run_kick_cell(
        connection,
        config=config,  # type: ignore[arg-type]
        margin_config=margin_config,
        base=base,
        config_hash=config_hash,
        code_sha=code_sha,
        experiment_number=_EXPERIMENT_NUMBER,
        seed=seed,
        dose=1,
        kick_cycles=(config.activation_cycle,),
    )
    pre_equal = preactivation_equal(
        connection,
        control,
        kick,
        activation_cycle=config.activation_cycle,
    )
    audits = kick["kick_audits"]
    assert isinstance(audits, Sequence) and len(audits) == 1
    audit = audits[0]
    assert isinstance(audit, Mapping)
    root_controller_valid = all(
        (
            bool(audit["margin_only_preserved"]),
            bool(audit["probe_crossed"]),
            int(audit["predicted_winner_slot"]) == int(audit["awarded_winner_slot"]),
            tuple(int(x) for x in kick["nonzero_adjustment_cycles"]) == (config.activation_cycle,),
        )
    )
    hard_invariants = _all_invariants(control) and _all_invariants(kick)
    env = campaign_environment(base, config)  # type: ignore[arg-type]
    control_evidence = _arm_evidence(connection, control)
    kick_evidence = _arm_evidence(connection, kick)
    lineage = _build_lineage(
        seed=seed,
        config=config,
        base=base,
        env=env,
        control=control_evidence,
        kick=kick_evidence,
    )
    replay = _build_lineage(
        seed=seed,
        config=config,
        base=base,
        env=env,
        control=control_evidence,
        kick=kick_evidence,
    )
    deterministic_replay_exact = _hash_value(
        {"events": lineage["events"], "edges": lineage["edges"]}
    ) == _hash_value({"events": replay["events"], "edges": replay["edges"]})
    root_gate = all(
        (
            pre_equal,
            root_controller_valid,
            hard_invariants,
            bool(lineage["success_reconstruction_matches"]),
            float(lineage["confidence_reconstruction_max_abs_error"]) <= 1e-9,
            int(lineage["pre_root_event_count"]) == 0,
            int(lineage["root_event_count"]) == 1,
            deterministic_replay_exact,
        )
    )
    return {
        "seed": seed,
        "control_run_id": str(control["run_id"]),
        "kick_run_id": str(kick["run_id"]),
        "preactivation_identity": pre_equal,
        "root_controller_valid": root_controller_valid,
        "hard_invariants": hard_invariants,
        "deterministic_replay_exact": deterministic_replay_exact,
        "root_gate": root_gate,
        **lineage,
    }


def _aggregate_calibration(
    pairs: Sequence[Mapping[str, object]],
    *,
    config: LineageConfig,
) -> dict[str, object]:
    downstream = sum(int(pair["primary_downstream_event_count"]) for pair in pairs)
    attributable = sum(int(pair["attributable_primary_event_count"]) for pair in pairs)
    orphan = sum(int(pair["orphan_primary_event_count"]) for pair in pairs)
    capture = attributable / downstream if downstream else 0.0
    per_seed_path_guard = all(
        int(pair["attributable_primary_event_count"]) == 0
        or float(pair["root_path_share"]) >= config.attribution_threshold
        for pair in pairs
    )
    root_gate = all(bool(pair["root_gate"]) for pair in pairs)
    calibration_ready = all(
        (
            downstream > 0,
            root_gate,
            capture >= config.attribution_threshold,
            orphan / downstream <= 1.0 - config.attribution_threshold + 1e-12 if downstream else False,
            per_seed_path_guard,
        )
    )
    attributable_total = attributable
    single = sum(int(pair["single_parent_count"]) for pair in pairs)
    multi = sum(int(pair["multi_parent_count"]) for pair in pairs)
    single_share = single / attributable_total if attributable_total else 0.0
    structure = (
        "predominantly_single_parent_lineage"
        if single_share >= config.single_parent_threshold
        else "multi_parent_lineage_material"
    )
    channel_edges = Counter()
    channel_pairs = Counter()
    for pair in pairs:
        counts = pair["channel_edge_counts"]
        assert isinstance(counts, Mapping)
        for channel, count in counts.items():
            channel_edges[str(channel)] += int(count)
            if int(count) > 0:
                channel_pairs[str(channel)] += 1
    total_channel_edges = sum(channel_edges.values())
    channel_summary = {
        channel: {
            "edge_count": channel_edges[channel],
            "edge_share": channel_edges[channel] / total_channel_edges if total_channel_edges else 0.0,
            "pair_presence": channel_pairs[channel],
        }
        for channel in _CHANNEL_ORDER
    }
    return {
        "pooled_primary_downstream_events": downstream,
        "pooled_attributable_events": attributable,
        "pooled_orphan_events": orphan,
        "pooled_capture": capture,
        "pooled_orphan_share": orphan / downstream if downstream else 1.0,
        "per_seed_root_path_guard": per_seed_path_guard,
        "all_root_invariant_gates": root_gate,
        "calibration_ready": calibration_ready,
        "calibration_conclusion": (
            "calibration_ready_for_schema_freeze"
            if calibration_ready
            else "lineage_capture_not_calibration_ready"
        ),
        "single_parent_count": single,
        "multi_parent_count": multi,
        "single_parent_share": single_share,
        "lineage_structure_diagnostic": structure,
        "channel_summary_descriptive_only": channel_summary,
    }


def run_experiment_138_calibration(
    connection: Connection[Any],
    *,
    config: LineageConfig,
    margin_config: AuctionMarginConfig,
    config_hash: str,
    code_sha: str,
) -> dict[str, object]:
    """Run schema-v1 calibration only; held-out validation seeds remain untouched."""
    base = load_campaign_base(config)  # type: ignore[arg-type]
    pairs = [
        _pair_calibration(
            connection,
            config=config,
            margin_config=margin_config,
            base=base,
            config_hash=config_hash,
            code_sha=code_sha,
            seed=seed,
        )
        for seed in config.calibration_seeds
    ]
    aggregate = _aggregate_calibration(pairs, config=config)
    events = [event for pair in pairs for event in pair["events"]]  # type: ignore[index]
    edges = [edge for pair in pairs for edge in pair["edges"]]  # type: ignore[index]
    pair_summaries = [
        {key: value for key, value in pair.items() if key not in {"events", "edges"}}
        for pair in pairs
    ]
    return {
        "experiment_number": _EXPERIMENT_NUMBER,
        "phase": "calibration",
        "schema_version": config.schema_version,
        "config_hash": config_hash,
        "code_sha": code_sha,
        "calibration_seeds": list(config.calibration_seeds),
        "validation_seeds_exposed": False,
        "validation_seed_count": len(config.validation_seeds),
        "event_ontology": list(config.event_classes),
        "attribution_threshold": config.attribution_threshold,
        "single_parent_threshold": config.single_parent_threshold,
        "maximum_corrective_revisions": config.maximum_corrective_revisions,
        "schema_revision_history": [
            {
                "version": "v1",
                "status": "initial_implementation",
                "validation_outputs_observed": False,
            }
        ],
        **aggregate,
        "pairs": pair_summaries,
        "events": events,
        "edges": edges,
        "interpretation_boundary": (
            "calibration_only_no_heldout_validation_and_no_139_141_authorization"
        ),
    }


def write_experiment_138_calibration_outputs(
    result: Mapping[str, object],
    output_dir: str | Path,
) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "experiment-138-calibration.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    pairs = result["pairs"]
    events = result["events"]
    edges = result["edges"]
    assert isinstance(pairs, Sequence) and isinstance(events, Sequence) and isinstance(edges, Sequence)
    _write_csv(
        output / "experiment-138-pair-summary.csv",
        pairs,  # type: ignore[arg-type]
        (
            "seed",
            "control_run_id",
            "kick_run_id",
            "root_gate",
            "preactivation_identity",
            "root_controller_valid",
            "hard_invariants",
            "deterministic_replay_exact",
            "primary_downstream_event_count",
            "attributable_primary_event_count",
            "orphan_primary_event_count",
            "capture",
            "root_path_share",
            "single_parent_count",
            "multi_parent_count",
            "single_parent_share",
            "pre_root_event_count",
            "root_event_count",
            "max_depth",
            "max_width",
            "lineage_lifetime_cycles",
            "confidence_reconstruction_max_abs_error",
            "success_reconstruction_matches",
            "channel_edge_counts",
        ),
    )
    _write_csv(
        output / "experiment-138-event-nodes.csv",
        events,  # type: ignore[arg-type]
        (
            "seed",
            "event_id",
            "cycle",
            "stage",
            "event_class",
            "entity",
            "classification",
            "direct_parents",
            "direct_parent_count",
            "depth",
            "root_reachable",
            "primary_window",
            "pre_root",
            "control_payload",
            "kick_payload",
            "read_set",
            "write_set",
        ),
    )
    _write_csv(
        output / "experiment-138-parent-edges.csv",
        edges,  # type: ignore[arg-type]
        (
            "seed",
            "parent_event_id",
            "child_event_id",
            "parent_event_class",
            "child_event_class",
            "child_cycle",
            "state_keys",
            "primary_window",
        ),
    )
    manifest = {
        "experiment_number": result["experiment_number"],
        "phase": result["phase"],
        "schema_version": result["schema_version"],
        "config_hash": result["config_hash"],
        "code_sha": result["code_sha"],
        "schema_revision_history": result["schema_revision_history"],
        "calibration_seeds": result["calibration_seeds"],
        "validation_seeds_exposed": result["validation_seeds_exposed"],
        "event_ontology": result["event_ontology"],
        "attribution_threshold": result["attribution_threshold"],
        "single_parent_threshold": result["single_parent_threshold"],
        "maximum_corrective_revisions": result["maximum_corrective_revisions"],
    }
    (output / "experiment-138-schema-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = [
        "## Experiment 138 — Discrete Causal-Event Lineage calibration (schema v1)",
        "",
        f"- Config hash: `{result['config_hash']}`",
        f"- Code SHA: `{result['code_sha']}`",
        f"- Calibration seeds: `{result['calibration_seeds']}`",
        "- Held-out validation seeds exposed: **False**",
        f"- Root/invariant gates all pass: **{result['all_root_invariant_gates']}**",
        f"- Primary downstream divergent events: **{result['pooled_primary_downstream_events']}**",
        f"- Attributable events: **{result['pooled_attributable_events']}**",
        f"- Orphan events: **{result['pooled_orphan_events']}**",
        f"- Pooled capture: **{result['pooled_capture']}**",
        f"- Per-seed root-path guard: **{result['per_seed_root_path_guard']}**",
        f"- Calibration ready: **{result['calibration_ready']}**",
        f"- Calibration conclusion: **{result['calibration_conclusion']}**",
        f"- Single-parent share: **{result['single_parent_share']}**",
        f"- Structure diagnostic: **{result['lineage_structure_diagnostic']}**",
        "",
        "### Interpretation boundary",
        "",
        (
            "This run is calibration-only. It does not validate lineage capture, does not expose "
            "seeds 3107–3112, and does not authorize Experiments 139–141. A passing calibration "
            "only permits a separate schema-freeze step before one-time held-out validation."
        ),
    ]
    (output / "experiment-138-calibration-report.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "run_experiment_138_calibration",
    "write_experiment_138_calibration_outputs",
]
