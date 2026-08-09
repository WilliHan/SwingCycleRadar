"""약세 다이버전스 탐지. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 15.1.

confirmed pivot high만 사용한다(15.1 명시) — 미확정 pivot을 쓰면 look-ahead가 된다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PivotHighObservation:
    confirm_date: str
    price: float
    rsi_at_pivot: float
    adx_local_max: float | None = None  # 10.1.1/15.1 "ADX peak" 정의 재사용


@dataclass(frozen=True)
class DivergenceResult:
    price_higher_high: bool
    rsi_lower_high: bool
    rsi_bearish_divergence: bool
    rsi_lh_streak: int          # RSI LH가 몇 회 연속 누적됐는지 (15.4 +20 배점용)
    adx_peak_declining: bool | None  # ADX 로컬 최댓값이 이전 구간보다 낮은지 (보조)


def bearish_divergence(pivot_highs: list[PivotHighObservation]) -> DivergenceResult:
    """가장 최근 confirmed pivot high 2~3개를 비교한다(confirm_date 오름차순 입력 가정).
    Price HH + RSI LH면 약세 다이버전스. MACD HH는 이 판단을 무효화하지 않는다(15.1 명시
    — 그래서 이 함수는 MACD를 아예 입력받지 않는다: 무효화 로직 자체가 없어야 한다)."""
    if len(pivot_highs) < 2:
        return DivergenceResult(False, False, False, 0, None)

    latest, prev = pivot_highs[-1], pivot_highs[-2]
    price_hh = latest.price > prev.price
    rsi_lh = latest.rsi_at_pivot < prev.rsi_at_pivot
    is_divergence = price_hh and rsi_lh

    # RSI LH 연속 누적 횟수: 뒤에서부터 price HH + RSI LH 쌍이 계속되는 구간을 센다.
    streak = 0
    for i in range(len(pivot_highs) - 1, 0, -1):
        cur, prv = pivot_highs[i], pivot_highs[i - 1]
        if cur.price > prv.price and cur.rsi_at_pivot < prv.rsi_at_pivot:
            streak += 1
        else:
            break

    adx_peak_declining = None
    if latest.adx_local_max is not None and prev.adx_local_max is not None:
        adx_peak_declining = latest.adx_local_max < prev.adx_local_max

    return DivergenceResult(price_hh, rsi_lh, is_divergence, streak, adx_peak_declining)
