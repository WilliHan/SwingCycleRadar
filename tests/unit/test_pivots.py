"""9.1-9.2 causal pivot 탐지 + 라벨링 테스트."""
from __future__ import annotations

import pandas as pd
import pytest

from swingcycle.structure.pivots import PivotConfig, _label_sequence, detect_and_label_pivots


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2026-01-01", periods=n, freq="D")


def _bars(high: list[float], low: list[float]) -> pd.DataFrame:
    n = len(high)
    return pd.DataFrame({
        "trade_date": _dates(n),
        "high": high,
        "low": low,
        "close": [(h + l) / 2 for h, l in zip(high, low)],
    })


class TestDetection:
    def test_single_high_pivot_detected_with_correct_confirm_date(self):
        high = [10, 11, 12, 15, 12, 11, 10]
        low = [1, 2, 3, 4, 5, 6, 7]  # 단조증가 — LOW pivot 없음
        bars = _bars(high, low)
        pivots = detect_and_label_pivots(bars, PivotConfig(left_bars=2, right_bars=2))

        highs = [p for p in pivots if p.pivot_type == "HIGH"]
        assert len(highs) == 1
        assert highs[0].pivot_date == "2026-01-04"  # 인덱스 3 (0-based) → 1/4
        assert highs[0].confirm_date == "2026-01-06"  # pivot_date + right_bars(2)일
        assert highs[0].price == 15.0
        assert not [p for p in pivots if p.pivot_type == "LOW"]

    def test_single_low_pivot_detected_with_correct_confirm_date(self):
        high = [20, 21, 22, 23, 24, 25, 26]  # 단조증가 — HIGH pivot 없음
        low = [10, 9, 8, 5, 8, 9, 10]
        bars = _bars(high, low)
        pivots = detect_and_label_pivots(bars, PivotConfig(left_bars=2, right_bars=2))

        lows = [p for p in pivots if p.pivot_type == "LOW"]
        assert len(lows) == 1
        assert lows[0].pivot_date == "2026-01-04"
        assert lows[0].confirm_date == "2026-01-06"
        assert lows[0].price == 5.0

    def test_edge_bars_never_produce_pivots(self):
        """left_bars/right_bars만큼의 양쪽 끝 구간은 윈도우가 부족해 pivot 판정 대상이 아니다."""
        high = [100, 90, 80, 70, 60]  # 첫 봉이 국소 최고점처럼 보여도 윈도우 부족으로 제외
        low = [1, 2, 3, 4, 5]
        bars = _bars(high, low)
        pivots = detect_and_label_pivots(bars, PivotConfig(left_bars=2, right_bars=2))
        assert pivots == []

    def test_confirm_date_never_precedes_pivot_date(self):
        high = [10, 11, 12, 15, 12, 11, 10, 9, 20, 9, 8]
        low = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        bars = _bars(high, low)
        pivots = detect_and_label_pivots(bars, PivotConfig(left_bars=2, right_bars=2))
        assert pivots  # 최소 1개는 있어야 의미있는 테스트
        for p in pivots:
            assert p.confirm_date >= p.pivot_date


class TestLabeling:
    def test_first_pivot_of_type_is_neutral(self):
        rows = [{"type": "HIGH", "pivot_date": "d1", "confirm_date": "c1", "price": 100.0}]
        out = _label_sequence(rows, tolerance_pct=0.20, higher_label="HH", lower_label="LH", equal_label="EH")
        assert out[0].dow_label == "EH"

    def test_clear_higher_high(self):
        rows = [
            {"type": "HIGH", "pivot_date": "d1", "confirm_date": "c1", "price": 100.0},
            {"type": "HIGH", "pivot_date": "d2", "confirm_date": "c2", "price": 110.0},
        ]
        out = _label_sequence(rows, tolerance_pct=0.20, higher_label="HH", lower_label="LH", equal_label="EH")
        assert out[1].dow_label == "HH"

    def test_clear_lower_high(self):
        rows = [
            {"type": "HIGH", "pivot_date": "d1", "confirm_date": "c1", "price": 100.0},
            {"type": "HIGH", "pivot_date": "d2", "confirm_date": "c2", "price": 90.0},
        ]
        out = _label_sequence(rows, tolerance_pct=0.20, higher_label="HH", lower_label="LH", equal_label="EH")
        assert out[1].dow_label == "LH"

    def test_within_tolerance_is_equal(self):
        # tolerance 0.20% of 100.0 = 0.20 → 100.1은 허용범위 내
        rows = [
            {"type": "HIGH", "pivot_date": "d1", "confirm_date": "c1", "price": 100.0},
            {"type": "HIGH", "pivot_date": "d2", "confirm_date": "c2", "price": 100.1},
        ]
        out = _label_sequence(rows, tolerance_pct=0.20, higher_label="HH", lower_label="LH", equal_label="EH")
        assert out[1].dow_label == "EH"

    def test_just_outside_tolerance_is_directional(self):
        rows = [
            {"type": "HIGH", "pivot_date": "d1", "confirm_date": "c1", "price": 100.0},
            {"type": "HIGH", "pivot_date": "d2", "confirm_date": "c2", "price": 100.5},
        ]
        out = _label_sequence(rows, tolerance_pct=0.20, higher_label="HH", lower_label="LH", equal_label="EH")
        assert out[1].dow_label == "HH"


class TestMergedSequence:
    def test_sorted_by_confirm_date(self):
        high = [10, 11, 20, 11, 10, 11, 12, 25, 12, 11, 10]
        low = [9, 8, 7, 2, 7, 8, 9, 10, 5, 10, 11]
        bars = _bars(high, low)
        pivots = detect_and_label_pivots(bars, PivotConfig(left_bars=2, right_bars=2))
        confirm_dates = [p.confirm_date for p in pivots]
        assert confirm_dates == sorted(confirm_dates)

    def test_no_lookahead_truncated_bars_match_prefix(self):
        """앞부분 pivot은 뒤 데이터가 추가돼도 절대 바뀌면 안 된다."""
        high = [10, 11, 20, 11, 10, 11, 12, 25, 12, 11, 10, 30, 18, 15, 14]
        low = [9, 8, 7, 2, 7, 8, 9, 10, 5, 10, 11, 12, 3, 12, 13]
        bars_full = _bars(high, low)
        bars_prefix = bars_full.iloc[:10].reset_index(drop=True)

        pivots_full = detect_and_label_pivots(bars_full, PivotConfig(left_bars=2, right_bars=2))
        pivots_prefix = detect_and_label_pivots(bars_prefix, PivotConfig(left_bars=2, right_bars=2))

        prefix_confirm_cutoff = bars_prefix["trade_date"].iloc[-1].strftime("%Y-%m-%d")
        full_within_prefix = [p for p in pivots_full if p.confirm_date <= prefix_confirm_cutoff]

        assert pivots_prefix == full_within_prefix
