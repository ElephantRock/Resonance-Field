from __future__ import annotations

import math

from resonance.experiments.critical_margin_audit import (
    _auction_radius,
    _spearman,
    _target_bid_radius,
)


def _rows() -> list[dict[str, object]]:
    return [
        {
            "candidate_slot": 1,
            "confidence": 0.50,
            "total_score": 0.60,
            "selected": True,
        },
        {
            "candidate_slot": 2,
            "confidence": 0.50,
            "total_score": 0.59,
            "selected": False,
        },
    ]


def test_auction_radius_is_relative_confidence_radius() -> None:
    expected = 0.01 / 0.45 / 0.50
    assert math.isclose(_auction_radius(_rows()), expected)
    assert math.isclose(_target_bid_radius(_rows(), target_slot=2), expected)


def test_selected_target_cannot_flip_itself_by_increasing_confidence() -> None:
    assert math.isinf(_target_bid_radius(_rows(), target_slot=1))


def test_confidence_cap_can_make_crossing_unreachable() -> None:
    rows = _rows()
    rows[1]["confidence"] = 0.97
    rows[1]["total_score"] = 0.58
    assert math.isinf(_auction_radius(rows))


def test_spearman_direction() -> None:
    assert math.isclose(_spearman([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]), -1.0)
