"""Dow 상태 분류. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 9.3.1

전문가 리뷰에서 발견된 버그(last_highs[-1]과 "마지막 확정 LH"를 혼동, 미정의 분기)를
막기 위해 반드시 _last_labeled()로 라벨 검색하고, 어떤 조건도 안 걸리면 RANGE로
귀결시키는 명시적 default를 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.enums import DowState


@dataclass(frozen=True)
class Pivot:
    confirm_date: str
    dow_label: str  # "HH" | "LH" | "HL" | "LL" | "EH" | "EL"
    price: float


@dataclass(frozen=True)
class DowStateConfig:
    downtrend_confirm_run: int = 2
    uptrend_confirm_run: int = 1
    range_lookback_pivots: int = 4
    range_amplitude_shrink_pct: float = 20.0


def _all_labeled(pivots: list[Pivot], label: str) -> bool:
    return bool(pivots) and all(p.dow_label == label for p in pivots)


def _last_labeled(pivots: list[Pivot], label: str) -> Pivot | None:
    """뒤에서부터 순회해 해당 label을 가진 가장 최근 pivot을 반환. last_highs[-1]과는 다르다."""
    for p in reversed(pivots):
        if p.dow_label == label:
            return p
    return None


def classify_dow_state(
    last_highs: list[Pivot],
    last_lows: list[Pivot],
    unconfirmed_low_price: float | None,
    latest_close: float | None,
    cfg: DowStateConfig = DowStateConfig(),
) -> DowState:
    if not last_highs or not last_lows:
        return DowState.RANGE  # pivot 부족(backfill 초기 구간) — 명시적 default

    if (
        _all_labeled(last_highs[-cfg.uptrend_confirm_run:], "HH")
        and _all_labeled(last_lows[-cfg.uptrend_confirm_run:], "HL")
    ):
        return DowState.UPTREND

    if (
        _all_labeled(last_highs[-cfg.downtrend_confirm_run:], "LH")
        and _all_labeled(last_lows[-cfg.downtrend_confirm_run:], "LL")
    ):
        return DowState.DOWNTREND

    last_lh = _last_labeled(last_highs, "LH")
    last_ll = _last_labeled(last_lows, "LL")
    cond_a = last_lh is not None and latest_close is not None and latest_close > last_lh.price
    cond_b = (
        unconfirmed_low_price is not None
        and last_ll is not None
        and unconfirmed_low_price > last_ll.price
    )
    if cond_a or cond_b:
        return DowState.REVERSAL_CANDIDATE

    return DowState.RANGE  # 명시적 default — 미정의 분기를 없앤다
