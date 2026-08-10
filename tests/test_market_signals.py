from __future__ import annotations

import math

import pytest

from resonance.market import BidSignal


def test_bid_signal_rejects_non_finite_adjustment() -> None:
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="adjustment must be finite"):
            BidSignal(adjustment=value)


def test_bid_signal_rejects_non_finite_components() -> None:
    with pytest.raises(ValueError, match="signal components must be finite"):
        BidSignal(components={"reputation": math.nan})
