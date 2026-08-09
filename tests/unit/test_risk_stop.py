"""16.1/16.3 Stop 가격/체결 시뮬레이션 테스트."""
from __future__ import annotations

from swingcycle.risk.stop import simulated_stop_fill, suggest_stop_price


def test_suggest_stop_price_default_buffer():
    assert suggest_stop_price(100.0) == 99.0


def test_suggest_stop_price_custom_buffer():
    assert suggest_stop_price(100.0, buffer_pct=2.0) == 98.0


class TestSimulatedStopFill:
    def test_gap_down_fills_at_open(self):
        assert simulated_stop_fill(open_=90.0, low=85.0, stop=95.0) == 90.0

    def test_intraday_touch_fills_at_stop(self):
        assert simulated_stop_fill(open_=100.0, low=94.0, stop=95.0) == 95.0

    def test_no_touch_is_unfilled(self):
        assert simulated_stop_fill(open_=100.0, low=96.0, stop=95.0) is None

    def test_open_exactly_at_stop_fills_at_open(self):
        assert simulated_stop_fill(open_=95.0, low=95.0, stop=95.0) == 95.0
