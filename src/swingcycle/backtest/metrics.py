"""백테스트 성과 지표. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 22.3."""
from __future__ import annotations

import statistics
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TradeResult:
    symbol: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    holding_days: int
    path_high: float   # 보유기간 중 최고가(MFE 계산용)
    path_low: float    # 보유기간 중 최저가(MAE 계산용)
    stopped: bool
    is_reentry: bool = False

    @property
    def return_pct(self) -> float:
        return (self.exit_price / self.entry_price - 1.0) * 100.0

    @property
    def mfe_pct(self) -> float:
        return (self.path_high / self.entry_price - 1.0) * 100.0

    @property
    def mae_pct(self) -> float:
        return (self.path_low / self.entry_price - 1.0) * 100.0


def _max_drawdown_pct(returns_pct: list[float]) -> float:
    """거래를 주어진 순서대로 복리 연결한 단순 equity curve 기준 최대낙폭(음수, %)."""
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for r in returns_pct:
        equity *= (1 + r / 100.0)
        peak = max(peak, equity)
        max_dd = min(max_dd, (equity / peak - 1.0) * 100.0)
    return max_dd


def aggregate_metrics(trades: list[TradeResult]) -> dict:
    if not trades:
        return {
            "trade_count": 0, "win_rate": None, "avg_return": None, "median_return": None,
            "profit_factor": None, "expectancy": None, "max_drawdown": None,
            "avg_holding_days": None, "avg_mfe": None, "avg_mae": None,
            "stop_rate": None, "reentry_success_rate": None,
        }

    returns = [t.return_pct for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    reentries = [t for t in trades if t.is_reentry]
    reentry_success_rate = (
        sum(1 for t in reentries if t.return_pct > 0) / len(reentries) * 100.0 if reentries else None
    )

    return {
        "trade_count": len(trades),
        "win_rate": len(wins) / len(trades) * 100.0,
        "avg_return": statistics.mean(returns),
        "median_return": statistics.median(returns),
        "profit_factor": profit_factor,
        "expectancy": statistics.mean(returns),  # v1 unit 모델 — 평균 수익률 자체가 기대값
        "max_drawdown": _max_drawdown_pct(returns),
        "avg_holding_days": statistics.mean(t.holding_days for t in trades),
        "avg_mfe": statistics.mean(t.mfe_pct for t in trades),
        "avg_mae": statistics.mean(t.mae_pct for t in trades),
        "stop_rate": sum(1 for t in trades if t.stopped) / len(trades) * 100.0,
        "reentry_success_rate": reentry_success_rate,
    }


def forward_returns(entry_price: float, bars_after_entry: pd.DataFrame, horizons: tuple[int, ...] = (5, 10, 20)) -> dict[int, float | None]:
    """ENTRY 이후 h영업일째 종가 기준 수익률(%). 데이터가 h일 미만이면 None."""
    out: dict[int, float | None] = {}
    for h in horizons:
        if len(bars_after_entry) >= h:
            close_h = float(bars_after_entry["close"].iloc[h - 1])
            out[h] = (close_h / entry_price - 1.0) * 100.0
        else:
            out[h] = None
    return out


def forward_mae(entry_price: float, bars_after_entry: pd.DataFrame, horizons: tuple[int, ...] = (5, 10, 20)) -> dict[int, float | None]:
    """ENTRY 이후 h영업일 구간 내 최저가 기준 최대 역행폭(%, 음수). 데이터가 h일 미만이면 None."""
    out: dict[int, float | None] = {}
    for h in horizons:
        if len(bars_after_entry) >= h:
            window_low = float(bars_after_entry["low"].iloc[:h].min())
            out[h] = (window_low / entry_price - 1.0) * 100.0
        else:
            out[h] = None
    return out
