"""15.1 약세 다이버전스 테스트."""
from __future__ import annotations

from swingcycle.divergence.bearish_divergence import PivotHighObservation, bearish_divergence


def test_fewer_than_two_pivots_returns_no_divergence():
    result = bearish_divergence([PivotHighObservation("d1", 100.0, 70.0)])
    assert result.rsi_bearish_divergence is False
    assert result.rsi_lh_streak == 0


def test_price_hh_rsi_lh_is_divergence():
    pivots = [
        PivotHighObservation("d1", 100.0, 75.0),
        PivotHighObservation("d2", 110.0, 65.0),  # price HH, rsi LH
    ]
    result = bearish_divergence(pivots)
    assert result.price_higher_high is True
    assert result.rsi_lower_high is True
    assert result.rsi_bearish_divergence is True


def test_price_hh_rsi_hh_is_not_divergence():
    pivots = [
        PivotHighObservation("d1", 100.0, 60.0),
        PivotHighObservation("d2", 110.0, 70.0),  # price HH, rsi도 HH
    ]
    result = bearish_divergence(pivots)
    assert result.rsi_bearish_divergence is False


def test_rsi_lh_streak_counts_consecutive_pairs():
    pivots = [
        PivotHighObservation("d1", 100.0, 80.0),
        PivotHighObservation("d2", 110.0, 70.0),  # divergence 1
        PivotHighObservation("d3", 120.0, 60.0),  # divergence 2 (연속)
    ]
    result = bearish_divergence(pivots)
    assert result.rsi_lh_streak == 2


def test_streak_breaks_on_non_divergent_pair():
    pivots = [
        PivotHighObservation("d1", 100.0, 80.0),
        PivotHighObservation("d2", 90.0, 85.0),   # divergence 아님 (price도 하락)
        PivotHighObservation("d3", 120.0, 60.0),  # 이번만 divergence
    ]
    result = bearish_divergence(pivots)
    assert result.rsi_lh_streak == 1


def test_adx_peak_declining_computed_when_available():
    pivots = [
        PivotHighObservation("d1", 100.0, 75.0, adx_local_max=40.0),
        PivotHighObservation("d2", 110.0, 65.0, adx_local_max=30.0),
    ]
    result = bearish_divergence(pivots)
    assert result.adx_peak_declining is True


def test_adx_peak_declining_none_when_missing():
    pivots = [
        PivotHighObservation("d1", 100.0, 75.0),
        PivotHighObservation("d2", 110.0, 65.0),
    ]
    result = bearish_divergence(pivots)
    assert result.adx_peak_declining is None
