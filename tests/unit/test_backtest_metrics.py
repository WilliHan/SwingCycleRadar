"""22.3 백테스트 성과 지표 테스트."""
from __future__ import annotations

import pandas as pd
import pytest

from swingcycle.backtest.metrics import TradeResult, aggregate_metrics, forward_mae, forward_returns


def _trade(entry=100.0, exit_=110.0, high=115.0, low=95.0, days=5, stopped=False, is_reentry=False) -> TradeResult:
    return TradeResult(
        symbol="005930", entry_date="2026-01-01", entry_price=entry,
        exit_date="2026-01-10", exit_price=exit_, holding_days=days,
        path_high=high, path_low=low, stopped=stopped, is_reentry=is_reentry,
    )


class TestTradeResultDerived:
    def test_return_pct(self):
        t = _trade(entry=100.0, exit_=110.0)
        assert t.return_pct == pytest.approx(10.0)

    def test_mfe_and_mae(self):
        t = _trade(entry=100.0, high=120.0, low=90.0)
        assert t.mfe_pct == pytest.approx(20.0)
        assert t.mae_pct == pytest.approx(-10.0)


class TestAggregateMetrics:
    def test_empty_trades_returns_none_fields(self):
        out = aggregate_metrics([])
        assert out["trade_count"] == 0
        assert out["win_rate"] is None

    def test_win_rate_and_avg_return(self):
        trades = [_trade(exit_=110.0), _trade(exit_=90.0)]  # +10%, -10%
        out = aggregate_metrics(trades)
        assert out["trade_count"] == 2
        assert out["win_rate"] == pytest.approx(50.0)
        assert out["avg_return"] == pytest.approx(0.0)

    def test_profit_factor_all_wins_is_infinite(self):
        trades = [_trade(exit_=110.0), _trade(exit_=120.0)]
        out = aggregate_metrics(trades)
        assert out["profit_factor"] == float("inf")

    def test_profit_factor_mixed(self):
        # gross_profit=10, gross_loss=5 -> pf=2.0
        trades = [_trade(exit_=110.0), _trade(exit_=95.0)]
        out = aggregate_metrics(trades)
        assert out["profit_factor"] == pytest.approx(2.0)

    def test_stop_rate(self):
        trades = [_trade(stopped=True), _trade(stopped=False), _trade(stopped=True)]
        out = aggregate_metrics(trades)
        assert out["stop_rate"] == pytest.approx(200 / 3)

    def test_reentry_success_rate_none_when_no_reentries(self):
        trades = [_trade(is_reentry=False)]
        out = aggregate_metrics(trades)
        assert out["reentry_success_rate"] is None

    def test_reentry_success_rate_computed(self):
        trades = [_trade(exit_=110.0, is_reentry=True), _trade(exit_=90.0, is_reentry=True), _trade(is_reentry=False)]
        out = aggregate_metrics(trades)
        assert out["reentry_success_rate"] == pytest.approx(50.0)

    def test_max_drawdown_is_negative_or_zero(self):
        trades = [_trade(exit_=110.0), _trade(exit_=80.0), _trade(exit_=90.0)]
        out = aggregate_metrics(trades)
        assert out["max_drawdown"] <= 0.0


class TestForwardReturnsAndMae:
    def _bars(self) -> pd.DataFrame:
        return pd.DataFrame({
            "close": [102.0, 104.0, 103.0, 106.0, 108.0],
            "low": [99.0, 98.0, 97.0, 100.0, 101.0],
        })

    def test_forward_return_at_available_horizon(self):
        out = forward_returns(100.0, self._bars(), horizons=(5,))
        assert out[5] == pytest.approx(8.0)  # close[4]=108 -> +8%

    def test_forward_return_none_when_insufficient_data(self):
        out = forward_returns(100.0, self._bars(), horizons=(10,))
        assert out[10] is None

    def test_forward_mae_uses_window_minimum_low(self):
        out = forward_mae(100.0, self._bars(), horizons=(5,))
        assert out[5] == pytest.approx(-3.0)  # min(low[:5])=97 -> -3%
