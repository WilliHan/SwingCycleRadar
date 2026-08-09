"""Causal pivot 탐지 + Dow 라벨링. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 9.1-9.2.

**Look-ahead 방지가 이 모듈의 존재 이유다**: t일의 pivot 여부는 `right_bars`일치의
미래 봉이 확정돼야 알 수 있다. 그래서 이 모듈이 반환하는 pivot에는 실제 고점/저점이
발생한 `pivot_date`와, 그 사실을 알 수 있게 되는 `confirm_date`(= pivot_date +
right_bars 거래일 후)가 분리되어 있다. Dow 상태 분류(`dow.classify_dow_state`)는
반드시 `confirm_date` 기준으로만 pivot을 사용해야 미래 참조가 되지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .dow import Pivot


@dataclass(frozen=True)
class PivotConfig:
    left_bars: int = 2
    right_bars: int = 2
    price_mode: str = "wick"  # "wick"(high/low) | "close"
    pivot_equal_tolerance_pct: float = 0.20


def _price_columns(bars: pd.DataFrame, cfg: PivotConfig) -> tuple[pd.Series, pd.Series]:
    if cfg.price_mode == "close":
        return bars["close"], bars["close"]
    return bars["high"], bars["low"]


def _date_str(value) -> str:
    if isinstance(value, str):
        return value
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _detect_raw_pivots(bars: pd.DataFrame, cfg: PivotConfig) -> list[dict]:
    """9.1 — high[t] == max(window), low[t] == min(window). 확정은 t+right_bars 시점.
    입력 `bars`는 그 시점까지 실제로 관측 가능한 데이터만 담고 있어야 한다(호출부 책임)."""
    high, low = _price_columns(bars, cfg)
    dates = bars["trade_date"]
    n = len(bars)
    raw: list[dict] = []

    for i in range(cfg.left_bars, n - cfg.right_bars):
        window_start, window_end = i - cfg.left_bars, i + cfg.right_bars + 1
        window_high = high.iloc[window_start:window_end]
        window_low = low.iloc[window_start:window_end]

        if high.iloc[i] == window_high.max():
            raw.append({
                "type": "HIGH",
                "pivot_date": _date_str(dates.iloc[i]),
                "confirm_date": _date_str(dates.iloc[i + cfg.right_bars]),
                "price": float(high.iloc[i]),
                "order": i,
            })
        if low.iloc[i] == window_low.min():
            raw.append({
                "type": "LOW",
                "pivot_date": _date_str(dates.iloc[i]),
                "confirm_date": _date_str(dates.iloc[i + cfg.right_bars]),
                "price": float(low.iloc[i]),
                "order": i,
            })
    return raw


def _label_sequence(raw_pivots: list[dict], tolerance_pct: float, higher_label: str, lower_label: str, equal_label: str) -> list[Pivot]:
    """9.2 — 직전 동일 타입 pivot과 비교해 라벨링. 비교 대상이 없는 첫 pivot은
    상승/하락 어느 쪽도 판단할 근거가 없으므로 중립(EH/EL)으로 둔다(설계서에 명시 없는
    엣지케이스 — tolerance-내-동일가 취급과 같은 카테고리로 처리하는 것이 가장 보수적)."""
    labeled: list[Pivot] = []
    prev_price: float | None = None
    for row in raw_pivots:
        price = row["price"]
        if prev_price is None:
            label = equal_label
        else:
            tolerance = abs(prev_price) * tolerance_pct / 100.0
            if abs(price - prev_price) <= tolerance:
                label = equal_label
            elif price > prev_price:
                label = higher_label
            else:
                label = lower_label
        labeled.append(Pivot(
            confirm_date=row["confirm_date"],
            dow_label=label,
            price=price,
            pivot_type=row["type"],
            pivot_date=row["pivot_date"],
        ))
        prev_price = price
    return labeled


def detect_and_label_pivots(bars: pd.DataFrame, cfg: PivotConfig = PivotConfig()) -> list[Pivot]:
    """`bars`(trade_date 오름차순, high/low/close 컬럼)에서 확정된 pivot을 전부 찾아
    HH/LH/HL/LL/EH/EL로 라벨링하고, confirm_date 오름차순으로 정렬해 반환한다.
    HIGH/LOW를 각각 독립적으로 라벨링한 뒤 병합한다 — 서로 다른 타입끼리는 비교하지 않는다.
    """
    raw = _detect_raw_pivots(bars, cfg)
    raw_highs = [r for r in raw if r["type"] == "HIGH"]
    raw_lows = [r for r in raw if r["type"] == "LOW"]

    labeled_highs = _label_sequence(raw_highs, cfg.pivot_equal_tolerance_pct, "HH", "LH", "EH")
    labeled_lows = _label_sequence(raw_lows, cfg.pivot_equal_tolerance_pct, "HL", "LL", "EL")

    merged = labeled_highs + labeled_lows
    merged.sort(key=lambda p: (p.confirm_date, p.pivot_type or ""))
    return merged
