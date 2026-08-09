"""오케스트레이션 입출력 계약. 설계: 17장/28장(ScoreContext).

`DailyContext`는 "이 종목의 이 날짜까지 관측 가능한 데이터"만 담는다 — bars 자체가
이미 `daily_bar_repo.fetch_bars(..., end_date=trade_date)`로 컷오프된 것이라는 전제
위에서, 여기서 파생되는 지표/피벗도 자동으로 그 날짜를 넘지 않는다(선행 참조 방지가
"경계 하나"에서 강제됨 — 이 규칙을 어기는 유일한 방법은 컷오프 없이 bars를 넘기는 것뿐).

`prior_cycle_state`/`has_active_plan` 등 "다른 테이블(cycle_daily 전일치, trade_plans)에서
오는 상태"는 의도적으로 DailyContext에 넣지 않는다 — bars 파생값과 외부 상태를 같은
객체에 섞으면 어디서 온 값인지 추적하기 어려워진다(28장 ScoreContext의 취지 유지).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from ..structure.dow import Pivot


@dataclass(frozen=True)
class DailyContext:
    symbol: str
    trade_date: date
    bars: pd.DataFrame            # trade_date <= self.trade_date, 오름차순, open/high/low/close/volume
    indicators: pd.DataFrame      # compute_all_indicators(bars) 결과, bars와 같은 길이/순서
    pivots: list[Pivot] = field(default_factory=list)  # confirm_date <= self.trade_date, confirm_date 오름차순

    @property
    def latest_bar(self) -> pd.Series:
        return self.bars.iloc[-1]

    @property
    def latest_indicators(self) -> pd.Series:
        return self.indicators.iloc[-1]

    @property
    def confirmed_highs(self) -> list[Pivot]:
        return [p for p in self.pivots if p.pivot_type == "HIGH"]

    @property
    def confirmed_lows(self) -> list[Pivot]:
        return [p for p in self.pivots if p.pivot_type == "LOW"]

    def has_enough_history(self, min_bars: int = 30) -> bool:
        """지표(RSI14/ADX14 등)가 워밍업을 마쳤다고 볼 수 있는 최소 바 수.
        부족하면 orchestrator가 이 종목/날짜는 건너뛰어야 한다(가짜 신호 방지)."""
        return len(self.bars) >= min_bars
