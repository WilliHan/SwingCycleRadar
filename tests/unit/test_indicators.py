"""8장 지표 계산 엔진 테스트.

공식 reference fixture가 아직 없어(Sprint 2 완료기준에 명시된 외부 fixture는
이 저장소에 존재하지 않음), 손계산 가능한 짧은 구간 + 수학적 불변식으로 검증한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swingcycle.indicators.technical import (
    compute_all_indicators,
    compute_dmi_adx,
    compute_ma5_distance,
    compute_macd,
    compute_rsi,
    compute_supplementary_smas,
    compute_volume_oscillator,
    wilder_smooth,
)


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2026-01-01", periods=n, freq="D")


class TestWilderSmooth:
    def test_seed_is_simple_average_of_first_period(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        out = wilder_smooth(s, period=3)
        assert np.isnan(out.iloc[0])
        assert np.isnan(out.iloc[1])
        assert out.iloc[2] == pytest.approx((1 + 2 + 3) / 3)

    def test_recursion_matches_hand_calculation(self):
        s = pd.Series([1.0, 2.0, 3.0, 6.0])
        out = wilder_smooth(s, period=3)
        seed = (1 + 2 + 3) / 3  # = 2.0
        expected_next = seed + (6.0 - seed) / 3  # = 2.0 + 4/3 = 3.333...
        assert out.iloc[3] == pytest.approx(expected_next)


class TestMACD:
    def test_flat_series_gives_zero_macd(self):
        close = pd.Series([100.0] * 40, index=_dates(40))
        out = compute_macd(close)
        assert out["macd"].iloc[26:].to_numpy() == pytest.approx(0.0, abs=1e-9)
        assert out["macd_signal"].iloc[35:].to_numpy() == pytest.approx(0.0, abs=1e-9)
        assert not out["macd_above_zero"].iloc[26:].any()

    def test_cross_up_detected_after_sustained_rise(self):
        close = pd.Series([100.0] * 30 + list(np.linspace(100, 130, 20)), index=_dates(50))
        out = compute_macd(close)
        assert out["macd_cross_up"].any()


class TestRSI:
    def test_all_gains_gives_rsi_100(self):
        close = pd.Series(np.arange(100.0, 130.0), index=_dates(30))
        out = compute_rsi(close, period=14)
        assert out["rsi14"].iloc[14:].to_numpy() == pytest.approx(100.0)
        assert out["rsi_allowed"].iloc[14:].all()

    def test_all_losses_gives_rsi_0(self):
        close = pd.Series(np.arange(130.0, 100.0, -1.0), index=_dates(30))
        out = compute_rsi(close, period=14)
        assert out["rsi14"].iloc[14:].to_numpy() == pytest.approx(0.0)
        assert not out["rsi_allowed"].iloc[14:].any()

    def test_flat_series_gives_neutral_50(self):
        close = pd.Series([100.0] * 30, index=_dates(30))
        out = compute_rsi(close, period=14)
        assert out["rsi14"].iloc[14:].to_numpy() == pytest.approx(50.0)

    def test_threshold_is_configurable(self):
        close = pd.Series([100.0] * 30, index=_dates(30))
        strict = compute_rsi(close, period=14, allowed_threshold=60.0)
        assert not strict["rsi_allowed"].iloc[14:].any()  # 50 <= 60 이므로 전부 False


class TestDmiAdx:
    def test_uptrend_plus_di_dominates_minus_di(self):
        n = 60
        high = pd.Series(np.linspace(100, 160, n), index=_dates(n))
        low = high - 2.0
        close = high - 1.0
        out = compute_dmi_adx(high, low, close)
        tail = out.iloc[30:]
        assert (tail["plus_di"] > tail["minus_di"]).all()

    def test_downtrend_minus_di_dominates_plus_di(self):
        n = 60
        high = pd.Series(np.linspace(160, 100, n), index=_dates(n))
        low = high - 2.0
        close = high - 1.0
        out = compute_dmi_adx(high, low, close)
        tail = out.iloc[30:]
        assert (tail["minus_di"] > tail["plus_di"]).all()

    def test_adx_flattening_flag_on_stable_trend(self):
        n = 60
        high = pd.Series(np.linspace(100, 160, n), index=_dates(n))
        low = high - 2.0
        close = high - 1.0
        out = compute_dmi_adx(high, low, close, flat_slope_abs_max=0.25)
        # 일정한 기울기의 추세에서는 ADX 기울기가 점차 완만해져 flattening 구간이 존재해야 한다.
        assert out["adx_flattening"].iloc[40:].any()


class TestMa5Distance:
    def test_hand_calculation(self):
        close = pd.Series([10.0, 10.0, 10.0, 10.0, 15.0], index=_dates(5))
        out = compute_ma5_distance(close, zscore_window=5)
        sma5_last = (10 + 10 + 10 + 10 + 15) / 5  # 11.0
        expected_pct = (15.0 / sma5_last - 1.0) * 100.0
        assert out["sma5"].iloc[-1] == pytest.approx(sma5_last)
        assert out["ma5_distance_pct"].iloc[-1] == pytest.approx(expected_pct)


class TestVolumeOscillator:
    def test_hand_calculation_sma(self):
        volume = pd.Series([100.0] * 19 + [300.0], index=_dates(20))
        out = compute_volume_oscillator(volume, method="sma", fast=10, slow=20)
        fast_ma = (100.0 * 9 + 300.0) / 10
        slow_ma = (100.0 * 19 + 300.0) / 20
        expected = (fast_ma - slow_ma) / slow_ma * 100.0
        assert out.iloc[-1] == pytest.approx(expected)


class TestSupplementarySmas:
    def test_hand_calculation(self):
        close = pd.Series([float(i) for i in range(1, 25)], index=_dates(24))  # 1..24
        out = compute_supplementary_smas(close, windows=(20,))
        expected = sum(range(5, 25)) / 20  # 마지막 20개 값(5..24) 평균 = 14.5
        assert out["sma20"].iloc[-1] == pytest.approx(expected)


class TestComputeAllIndicators:
    def _synthetic_bars(self, n: int) -> pd.DataFrame:
        rng = np.random.default_rng(42)
        close = 100 + np.cumsum(rng.normal(0, 1, n))
        high = close + rng.uniform(0.5, 2.0, n)
        low = close - rng.uniform(0.5, 2.0, n)
        open_ = close + rng.uniform(-1.0, 1.0, n)
        volume = rng.uniform(1000, 5000, n)
        return pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=_dates(n),
        )

    def test_all_expected_columns_present(self):
        bars = self._synthetic_bars(80)
        out = compute_all_indicators(bars)
        expected = {
            "macd", "macd_signal", "macd_histogram", "macd_above_signal", "macd_cross_up",
            "macd_above_zero", "macd_slope_3",
            "rsi14", "rsi_allowed", "rsi_turn_up", "rsi_slope_3", "rsi_above_50",
            "plus_di", "minus_di", "adx", "adx_slope_1", "adx_slope_3",
            "mdi_slope_1", "mdi_slope_3", "adx_falling", "adx_flattening",
            "adx_turn_up", "mdi_falling",
            "sma5", "ma5_distance_pct", "ma5_distance_delta_1", "ma5_distance_z20",
            "sma20", "sma60", "sma120", "sma240",
            "volume_oscillator",
        }
        assert expected.issubset(set(out.columns))

    def test_no_lookahead_truncated_series_matches_prefix(self):
        """t 시점 지표가 t 이후 데이터에 영향받지 않아야 한다(선행 참조 금지 —
        design 원칙: 데이터가 수정되면 '전체 연관 구간'만 재계산 가능해야 하고,
        미래 데이터가 과거 지표값을 바꿔서는 안 된다)."""
        bars_full = self._synthetic_bars(80)
        bars_prefix = bars_full.iloc[:50]

        out_full = compute_all_indicators(bars_full)
        out_prefix = compute_all_indicators(bars_prefix)

        numeric_cols = [c for c in out_prefix.columns if out_prefix[c].dtype.kind in "fb"]
        pd.testing.assert_frame_equal(
            out_full.iloc[:50][numeric_cols].reset_index(drop=True),
            out_prefix[numeric_cols].reset_index(drop=True),
            check_dtype=False,
        )
