from __future__ import annotations

import json

import pytest

from resonance.experiments.demand_campaign import build_source_schedule
from resonance.experiments.demand_config import DemandConfig, DemandScheduleSpec, load_demand_config
from resonance.experiments.demand_notebook import render_synthesis


def _domain(seed: int, cycle: int, domain_count: int) -> int:
    del seed
    return cycle % domain_count


def _repeat_rate(schedule: list[int], *, shift_period: int, domain_count: int) -> float:
    values: list[float] = []
    for start in range(0, len(schedule), shift_period):
        end = min(len(schedule), start + shift_period)
        domains = [_domain(0, schedule[index], domain_count) for index in range(start, end)]
        values.extend(float(a == b) for a, b in zip(domains, domains[1:], strict=False))
    return sum(values) / len(values)


def test_schedule_spec_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        DemandScheduleSpec(mode="teleport")


def test_intervention_preserves_exact_regime_multiset() -> None:
    schedule = build_source_schedule(
        DemandScheduleSpec(mode="blocked"),
        seed=11,
        cycles=24,
        shift_period=12,
        domain_count=4,
        domain_fn=_domain,
    )
    assert sorted(schedule) == list(range(24))
    assert sorted(schedule[:12]) == list(range(12))
    assert sorted(schedule[12:]) == list(range(12, 24))
    assert all(target // 12 == source // 12 for target, source in enumerate(schedule))


def test_persistence_modes_span_low_to_high() -> None:
    kwargs = {
        "seed": 11,
        "cycles": 24,
        "shift_period": 12,
        "domain_count": 4,
        "domain_fn": _domain,
    }
    interleaved = build_source_schedule(DemandScheduleSpec(mode="interleaved"), **kwargs)
    paired = build_source_schedule(DemandScheduleSpec(mode="paired"), **kwargs)
    blocked = build_source_schedule(DemandScheduleSpec(mode="blocked"), **kwargs)
    low = _repeat_rate(interleaved, shift_period=12, domain_count=4)
    middle = _repeat_rate(paired, shift_period=12, domain_count=4)
    high = _repeat_rate(blocked, shift_period=12, domain_count=4)
    assert low <= middle <= high
    assert high - low >= 0.5


def test_phase_modes_change_only_at_regime_boundaries() -> None:
    spec = DemandScheduleSpec(mode="baseline", phase_modes=("blocked", "interleaved", "blocked"))
    schedule = build_source_schedule(
        spec,
        seed=4,
        cycles=30,
        shift_period=10,
        domain_count=5,
        domain_fn=_domain,
    )
    assert sorted(schedule[:10]) == list(range(10))
    assert sorted(schedule[10:20]) == list(range(10, 20))
    assert sorted(schedule[20:30]) == list(range(20, 30))


def test_config_round_trip(tmp_path) -> None:
    value = {
        "name": "demand-test",
        "environment": {
            "agents": 6,
            "domains": ["a", "b", "c"],
            "cycles": 18,
            "cycle_seconds": 30,
            "shift_period": 6,
            "candidate_count": 3,
            "task_budget": 12,
            "bid_deadline_seconds": 20,
            "trace_half_life_cycles": 8.0,
            "initial_credits": 1200,
            "base_success_probability": 0.38,
            "practice_gain": 0.14,
            "maximum_success_probability": 0.9,
            "confidence_base": 0.35,
            "confidence_evidence_weight": 0.35,
            "confidence_noise_weight": 0.2,
            "price_floor": 0.45,
            "price_span": 0.35,
            "completion_min_seconds": 5,
            "completion_span_seconds": 12,
        },
        "seeds": [1],
        "holdout_seeds": [2],
        "holdout_cycles": 21,
        "holdout_shift_period": 7,
        "holdout_candidate_count": 3,
        "success_tolerance": 0.015,
        "incumbent_tolerance": 0.05,
        "economic_tolerance": 0.08,
        "demand": {
            "public_trace_confidence_weight": 0.1,
            "knowledge_signal_threshold": 0.2,
            "retrieval_top_k": 6,
            "knowledge_tolerance": 0.1,
            "minimum_logical_improvement": 0.02,
            "minimum_persistence_change": 0.1,
            "response_modes": ["interleaved", "paired", "blocked"],
            "replication_seeds": [3],
            "minimum_unlock_winner_change": 0.01,
            "minimum_relock_winner_rebound": 0.01,
            "holdout_restore_fraction": 0.7,
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value))
    config, digest = load_demand_config(path)
    assert isinstance(config, DemandConfig)
    assert config.response_modes == ("interleaved", "paired", "blocked")
    assert len(digest) == 64


def test_null_synthesis_moves_to_endogenous_demand() -> None:
    text = render_synthesis(
        {
            "code_sha": "abc",
            "config_hash": "def",
            "selected_schedule": {"mode": "interleaved", "phase_modes": []},
            "screen_validated": False,
            "decomposition_validated": False,
            "response_validated": False,
            "reversal_validated": False,
            "replication_validated": False,
            "validated": False,
            "strong_demand_causal": False,
        }
    )
    assert "endogenous demand feedback" in text
    assert "Production behavior remains unchanged" in text
