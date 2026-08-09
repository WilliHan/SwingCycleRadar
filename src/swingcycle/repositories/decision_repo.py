"""DecisionEngine 산출물의 idempotent 영속화. 스키마: migrations/001_init.sql.

모든 upsert는 (trade_date, symbol) 또는 (symbol, pivot_date, pivot_type) PK 기준
`ON CONFLICT DO UPDATE`라 같은 날짜를 몇 번 재실행해도 행이 늘지 않는다(idempotent).

trade_plans/trade_events는 이 모듈이 직접 만들지 않는다 — ENTRY/ADD/TAKE_PROFIT_PARTIAL은
"시스템의 제안"이고 실제 플랜 시작/증액/일부익절은 사용자가 UI에서 확정하는 별도 행동이다
(13장 "비중 숫자는 시스템이 주문하지 않는다"는 원칙을 ADD 외의 모든 포지션 변경에도
동일하게 적용). 유일한 예외는 STOP — 16.4가 명시한 대로 기계적으로 자동 처리한다.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date

import pandas as pd

from ..domain.enums import CycleState
from ..domain.models import Decision
from ..risk.reset import apply_stop_and_reset
from ..risk.stop import simulated_stop_fill
from ..structure.dow import Pivot
from ..structure.pivots import PivotConfig
from . import trade_plan_repo


def has_scores_row(conn: sqlite3.Connection, symbol: str, trade_date: date) -> bool:
    row = conn.execute(
        "SELECT 1 FROM scores_daily WHERE trade_date = ? AND symbol = ?",
        (trade_date.isoformat(), symbol),
    ).fetchone()
    return row is not None


def get_prior_cycle_state(conn: sqlite3.Connection, symbol: str, trade_date: date) -> CycleState:
    """`trade_date` 이전 가장 최근 cycle_daily 행의 cycle_state. 없으면(신규 종목/첫 실행)
    콜드스타트 기본값 DOWNTREND — state machine이 가장 보수적으로 시작하도록(RANGE 대신
    DOWNTREND을 기본으로 두면 UPTREND 계열로 잘못 넘어가려면 명시적 조건을 다 통과해야 한다)."""
    row = conn.execute(
        "SELECT cycle_state FROM cycle_daily WHERE symbol = ? AND trade_date < ? ORDER BY trade_date DESC LIMIT 1",
        (symbol, trade_date.isoformat()),
    ).fetchone()
    if row is None:
        return CycleState.DOWNTREND
    return CycleState(row["cycle_state"])


def check_and_apply_stop(conn: sqlite3.Connection, *, symbol: str, trade_date: date, bar: pd.Series) -> bool:
    """오늘 봉이 활성 플랜의 stop_price를 건드렸는지 확인하고, 그렇다면 즉시
    16.3(체결 시뮬레이션)+16.4(RESET)를 기계적으로 처리한다. STOP이 감지되면 True —
    호출부(daily_decide.py)는 이 경우 evaluate()를 아예 부르지 않고 그 날은 STOP으로 종결한다."""
    plan = trade_plan_repo.get_active_plan(conn, symbol)
    if plan is None:
        return False

    fill_price = simulated_stop_fill(open_=float(bar["open"]), low=float(bar["low"]), stop=plan["stop_price"])
    if fill_price is None:
        return False

    apply_stop_and_reset(conn, plan_id=plan["plan_id"], trade_date=trade_date.isoformat(), fill_price=fill_price)
    return True


def _upsert_indicators(conn: sqlite3.Connection, symbol: str, trade_date: date, ind: pd.Series) -> None:
    def g(key: str) -> float | None:
        value = ind.get(key)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return float(value)

    conn.execute(
        """
        INSERT INTO indicators_daily
            (trade_date, symbol, sma5, sma20, sma60, sma120, sma240, ema12, ema26,
             macd, macd_signal, macd_hist, rsi14, rsi_signal, pdi14, mdi14, adx14,
             vo10_20, ma5_distance_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date, symbol) DO UPDATE SET
            sma5=excluded.sma5, sma20=excluded.sma20, sma60=excluded.sma60,
            sma120=excluded.sma120, sma240=excluded.sma240,
            macd=excluded.macd, macd_signal=excluded.macd_signal, macd_hist=excluded.macd_hist,
            rsi14=excluded.rsi14, pdi14=excluded.pdi14, mdi14=excluded.mdi14, adx14=excluded.adx14,
            vo10_20=excluded.vo10_20, ma5_distance_pct=excluded.ma5_distance_pct
        """,
        (
            trade_date.isoformat(), symbol, g("sma5"), g("sma20"), g("sma60"), g("sma120"), g("sma240"),
            g("macd"), g("macd_signal"), g("macd_histogram"), g("rsi14"),
            g("plus_di"), g("minus_di"), g("adx"), g("volume_oscillator"), g("ma5_distance_pct"),
        ),
    )


def _upsert_pivots(conn: sqlite3.Connection, symbol: str, pivots: list[Pivot], cfg: PivotConfig) -> None:
    for p in pivots:
        conn.execute(
            """
            INSERT INTO pivots (symbol, pivot_date, confirm_date, pivot_type, price, left_bars, right_bars, dow_label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, pivot_date, pivot_type) DO UPDATE SET
                confirm_date=excluded.confirm_date, price=excluded.price,
                left_bars=excluded.left_bars, right_bars=excluded.right_bars, dow_label=excluded.dow_label
            """,
            (symbol, p.pivot_date, p.confirm_date, p.pivot_type, p.price, cfg.left_bars, cfg.right_bars, p.dow_label),
        )


def _upsert_cycle(conn: sqlite3.Connection, symbol: str, trade_date: date, decision: Decision, dow_state: str, pivots: list[Pivot]) -> None:
    highs = [p for p in pivots if p.pivot_type == "HIGH"]
    lows = [p for p in pivots if p.pivot_type == "LOW"]
    last_high = highs[-1] if highs else None
    last_low = lows[-1] if lows else None

    conn.execute(
        """
        INSERT INTO cycle_daily
            (trade_date, symbol, cycle_state, dow_state, last_pivot_high_date, last_pivot_high,
             last_pivot_low_date, last_pivot_low)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date, symbol) DO UPDATE SET
            cycle_state=excluded.cycle_state, dow_state=excluded.dow_state,
            last_pivot_high_date=excluded.last_pivot_high_date, last_pivot_high=excluded.last_pivot_high,
            last_pivot_low_date=excluded.last_pivot_low_date, last_pivot_low=excluded.last_pivot_low
        """,
        (
            trade_date.isoformat(), symbol, decision.cycle_state.value, dow_state,
            last_high.pivot_date if last_high else None, last_high.price if last_high else None,
            last_low.pivot_date if last_low else None, last_low.price if last_low else None,
        ),
    )


def _upsert_scores(conn: sqlite3.Connection, symbol: str, trade_date: date, decision: Decision) -> None:
    conn.execute(
        """
        INSERT INTO scores_daily
            (trade_date, symbol, reversal_core_score, adx_gate, pullback_score, late_stage_score, action, reasons_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date, symbol) DO UPDATE SET
            reversal_core_score=excluded.reversal_core_score, adx_gate=excluded.adx_gate,
            pullback_score=excluded.pullback_score, late_stage_score=excluded.late_stage_score,
            action=excluded.action, reasons_json=excluded.reasons_json
        """,
        (
            trade_date.isoformat(), symbol, decision.reversal_core_score, decision.adx_gate.value,
            decision.pullback_score, decision.late_stage_score, decision.action.value,
            json.dumps(decision.reasons, ensure_ascii=False),
        ),
    )


def save_analysis(
    conn: sqlite3.Connection, *, decision: Decision, indicators_row: pd.Series, pivots: list[Pivot],
    dow_state: str, pivot_config: PivotConfig = PivotConfig(),
) -> None:
    """indicators_daily/pivots/cycle_daily/scores_daily를 한 트랜잭션으로 upsert.
    전부 PK 충돌 시 갱신이라 같은 (symbol, trade_date)를 몇 번 다시 호출해도 안전하다."""
    symbol, trade_date = decision.symbol, decision.trade_date
    _upsert_indicators(conn, symbol, trade_date, indicators_row)
    _upsert_pivots(conn, symbol, pivots, pivot_config)
    _upsert_cycle(conn, symbol, trade_date, decision, dow_state, pivots)
    _upsert_scores(conn, symbol, trade_date, decision)
    conn.commit()
