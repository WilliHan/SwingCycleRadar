"""scoring/signal_derivation.py 단위 테스트.

support_then_rebound 정확성 수정(rsi_turn_up 단독 근사 -> "50 부근 지지 + 재상승"
명시 조건)의 경계값을 집중적으로 검증한다.
"""
from __future__ import annotations

import pandas as pd
import pytest

from swingcycle.scoring.context import DailyContext
from swingcycle.scoring.signal_derivation import DerivationConfig, _rsi_touched_50_support_recently, derive_pullback_signals


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2026-01-01", periods=n, freq="D")


def _ctx_with_rsi(rsi_values: list[float]) -> DailyContext:
    n = len(rsi_values)
    indicators = pd.DataFrame({"trade_date": _dates(n), "rsi14": rsi_values})
    bars = pd.DataFrame({
        "trade_date": _dates(n), "open": [100.0] * n, "high": [101.0] * n,
        "low": [99.0] * n, "close": [100.0] * n, "volume": [1000.0] * n,
    })
    return DailyContext(symbol="005930", trade_date=_dates(n)[-1].date(), bars=bars, indicators=indicators, pivots=[])


class TestRsiTouchedSupportRecently:
    def test_touches_within_band_today(self):
        ctx = _ctx_with_rsi([70.0, 65.0, 60.0, 55.0, 50.5])  # 오늘 정확히 밴드 내
        assert _rsi_touched_50_support_recently(ctx, band=3.0, lookback=5) is True

    def test_touches_within_band_a_few_days_ago(self):
        ctx = _ctx_with_rsi([70.0, 51.0, 60.0, 65.0, 70.0])  # 4일 전 밴드 내, 오늘은 멀리 벗어남
        assert _rsi_touched_50_support_recently(ctx, band=3.0, lookback=5) is True

    def test_never_within_band_is_false(self):
        ctx = _ctx_with_rsi([70.0, 68.0, 65.0, 62.0, 60.0])  # 전부 50과 멂
        assert _rsi_touched_50_support_recently(ctx, band=3.0, lookback=5) is False

    def test_exact_boundary_is_inclusive(self):
        # band=3.0일 때 RSI=53.0(=50+3)은 경계값 — 포함(<=)이어야 한다
        ctx = _ctx_with_rsi([70.0, 68.0, 65.0, 62.0, 53.0])
        assert _rsi_touched_50_support_recently(ctx, band=3.0, lookback=5) is True

    def test_just_outside_boundary_is_false(self):
        ctx = _ctx_with_rsi([70.0, 68.0, 65.0, 62.0, 53.01])
        assert _rsi_touched_50_support_recently(ctx, band=3.0, lookback=5) is False

    def test_outside_lookback_window_does_not_count(self):
        # 50.0은 lookback=3 창 밖(6일 전)에만 존재 — 최근 3일은 전부 밴드 밖
        ctx = _ctx_with_rsi([50.0, 70.0, 68.0, 65.0, 62.0, 60.0])
        assert _rsi_touched_50_support_recently(ctx, band=3.0, lookback=3) is False


class TestSupportThenReboundIntegration:
    def _cycle_signals_stub(self):
        from swingcycle.cycle.state_machine import CycleSignals
        from swingcycle.domain.enums import DowState
        return CycleSignals(
            dow_state=DowState.UPTREND, adx_falling=False, adx_flattening=False, adx_turn_up=False,
            mdi_falling=False, macd_above_signal=True, macd_above_zero=True, rsi_allowed=True,
            rsi_above_50=True, hh_hl_confirmed=True, pullback_in_progress=True, hl_intact=True,
            hl_holding_or_confirmed=True, adx_strong_or_rising=True, price_new_hh=False,
            rsi_lh_accumulating=False, adx_peak_declining=False, ma5_distance_extreme=False,
            lh_candidate=False, major_hl_breached=False, new_ll_confirmed=False,
        )

    def _ctx_full(self, rsi_values: list[float]) -> DailyContext:
        n = len(rsi_values)
        rsi_series = pd.Series(rsi_values)
        indicators = pd.DataFrame({
            "trade_date": _dates(n), "rsi14": rsi_values,
            "rsi_above_50": rsi_series > 50.0,
            "rsi_turn_up": rsi_series > rsi_series.shift(1).fillna(-1e9),
            "macd_above_zero": [True] * n, "macd_above_signal": [True] * n,
            "adx": [32.0] * n, "adx_turn_up": [False] * n, "adx_falling": [False] * n,
            "sma20": [100.0] * n, "volume_oscillator": [1.0] * n,
        })
        bars = pd.DataFrame({
            "trade_date": _dates(n), "open": [100.0] * n, "high": [101.0] * n,
            "low": [99.0] * n, "close": [100.0 + i * 0.1 for i in range(n)], "volume": [1000.0] * n,
        })
        return DailyContext(symbol="005930", trade_date=_dates(n)[-1].date(), bars=bars, indicators=indicators, pivots=[])

    def test_true_when_recently_near_50_and_turning_up_today(self):
        ctx = self._ctx_full([70.0, 60.0, 51.0, 49.0, 52.0])  # 어제 49, 오늘 52 -> turn_up, 최근 51/49가 밴드 내
        _, _, rsi_signals, _, _ = derive_pullback_signals(ctx, self._cycle_signals_stub(), DerivationConfig())
        assert rsi_signals.support_then_rebound is True

    def test_false_when_turning_up_far_from_50(self):
        ctx = self._ctx_full([70.0, 72.0, 74.0, 76.0, 78.0])  # 계속 상승 중이지만 50 근처 간 적 없음
        _, _, rsi_signals, _, _ = derive_pullback_signals(ctx, self._cycle_signals_stub(), DerivationConfig())
        assert rsi_signals.support_then_rebound is False

    def test_false_when_near_50_but_not_turning_up_today(self):
        ctx = self._ctx_full([60.0, 55.0, 51.0, 50.0, 49.0])  # 50 부근이었지만 오늘도 계속 하락 중
        _, _, rsi_signals, _, _ = derive_pullback_signals(ctx, self._cycle_signals_stub(), DerivationConfig())
        assert rsi_signals.support_then_rebound is False
