"""체결 시뮬레이션 + 포지션 모델. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 22.1-22.2."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..domain.enums import Action


@dataclass(frozen=True)
class Fill:
    fill_date: str
    fill_price: float


def next_open_fill(bars: pd.DataFrame, signal_date: str) -> Fill | None:
    """22.1 — 기본 체결은 신호일(T) 다음 영업일(T+1) 시가.
    `bars`는 trade_date 오름차순, 문자열(YYYY-MM-DD) 또는 그와 비교 가능한 값이어야 한다.
    signal_date가 데이터에 없거나 마지막 거래일이면(다음 봉이 없으면) None."""
    dates = bars["trade_date"].astype(str)
    matches = bars.index[dates == str(signal_date)]
    if len(matches) == 0:
        return None
    pos = bars.index.get_loc(matches[0])
    if pos + 1 >= len(bars):
        return None
    next_row = bars.iloc[pos + 1]
    return Fill(fill_date=str(next_row["trade_date"])[:10], fill_price=float(next_row["open"]))


def same_close_fill(bars: pd.DataFrame, signal_date: str) -> Fill | None:
    """연구용 옵션 — 기본 OFF(22.1). 당일 종가 체결."""
    dates = bars["trade_date"].astype(str)
    matches = bars[dates == str(signal_date)]
    if matches.empty:
        return None
    row = matches.iloc[0]
    return Fill(fill_date=str(row["trade_date"])[:10], fill_price=float(row["close"]))


@dataclass
class Position:
    """22.2 v1 단순 유닛 모델. ENTRY=1, ADD=+1(max_units까지), TAKE_PROFIT_PARTIAL=-1,
    STOP/EXIT=잔여 전량 청산."""
    units: int = 0
    max_units: int = 3

    def apply(self, action: Action) -> int:
        """이번 액션으로 변화한 unit 수(양수=매수, 음수=매도)를 반환하고 내부 상태를 갱신한다."""
        if action == Action.ENTRY:
            delta = 1
        elif action == Action.ADD:
            delta = 1 if self.units < self.max_units else 0
        elif action == Action.TAKE_PROFIT_PARTIAL:
            delta = -1 if self.units > 0 else 0
        elif action in (Action.STOP, Action.EXIT):
            delta = -self.units
        else:
            delta = 0
        self.units += delta
        return delta
