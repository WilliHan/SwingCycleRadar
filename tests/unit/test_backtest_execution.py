"""22.1-22.2 체결/포지션 모델 테스트."""
from __future__ import annotations

import pandas as pd

from swingcycle.backtest.execution import Position, next_open_fill, same_close_fill
from swingcycle.domain.enums import Action


def _bars() -> pd.DataFrame:
    return pd.DataFrame({
        "trade_date": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "open": [100.0, 105.0, 110.0],
        "high": [102.0, 107.0, 112.0],
        "low": [99.0, 104.0, 109.0],
        "close": [101.0, 106.0, 111.0],
    })


class TestNextOpenFill:
    def test_fills_at_next_day_open(self):
        fill = next_open_fill(_bars(), "2026-01-01")
        assert fill.fill_date == "2026-01-02"
        assert fill.fill_price == 105.0

    def test_none_when_signal_is_last_bar(self):
        assert next_open_fill(_bars(), "2026-01-03") is None

    def test_none_when_signal_date_not_found(self):
        assert next_open_fill(_bars(), "2099-01-01") is None


class TestSameCloseFill:
    def test_fills_at_signal_day_close(self):
        fill = same_close_fill(_bars(), "2026-01-01")
        assert fill.fill_date == "2026-01-01"
        assert fill.fill_price == 101.0


class TestPosition:
    def test_entry_opens_one_unit(self):
        p = Position()
        delta = p.apply(Action.ENTRY)
        assert delta == 1
        assert p.units == 1

    def test_add_increments_up_to_max(self):
        p = Position(units=1, max_units=3)
        assert p.apply(Action.ADD) == 1
        assert p.apply(Action.ADD) == 1
        assert p.units == 3
        assert p.apply(Action.ADD) == 0  # max 도달 — 더 안 늘어남
        assert p.units == 3

    def test_take_profit_partial_removes_one_unit(self):
        p = Position(units=2)
        assert p.apply(Action.TAKE_PROFIT_PARTIAL) == -1
        assert p.units == 1

    def test_take_profit_partial_noop_when_flat(self):
        p = Position(units=0)
        assert p.apply(Action.TAKE_PROFIT_PARTIAL) == 0

    def test_stop_closes_all_remaining_units(self):
        p = Position(units=3)
        assert p.apply(Action.STOP) == -3
        assert p.units == 0

    def test_exit_closes_all_remaining_units(self):
        p = Position(units=2)
        assert p.apply(Action.EXIT) == -2
        assert p.units == 0

    def test_wait_and_ready_are_noop(self):
        p = Position(units=1)
        assert p.apply(Action.WAIT) == 0
        assert p.apply(Action.READY) == 0
        assert p.units == 1
