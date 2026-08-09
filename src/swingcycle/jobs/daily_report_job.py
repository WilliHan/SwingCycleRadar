"""swingcycle report — 20장 3단계. daily_decide.py 다음 단계.

scores_daily(+indicators_daily/pivots)에 이미 저장된 그날 분석 결과를 읽어
21장 리포트(html/csv/json)로 내보낸다. 이 잡 자체는 아무 계산도 하지 않는다 —
전부 daily_decide.py가 이미 DB에 적어둔 값을 그대로 조립만 한다.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date
from pathlib import Path

from ..domain.enums import Action, CycleState, Gate
from ..domain.models import Decision
from ..reports.daily_report import ReportCard
from ..reports.storage import cleanup_old_reports, save_report
from ..repositories import symbol_repo
from ..repositories.db import get_connection, run_migrations
from ..settings import load_yaml_config

logger = logging.getLogger("daily_report_job")


def _build_card(conn: sqlite3.Connection, row: sqlite3.Row, trade_date: date) -> ReportCard:
    symbol = row["symbol"]
    symbol_row = symbol_repo.get_symbol(conn, symbol)
    name = symbol_row["name"] if symbol_row else symbol
    friend_group = symbol_row["friend_group"] if symbol_row else None

    # cycle_state/dow_state는 scores_daily가 아니라 cycle_daily에 있다(스키마 7장 —
    # scores_daily는 점수/액션만, cycle 상태는 별도 테이블).
    cycle_row = conn.execute(
        "SELECT cycle_state, dow_state FROM cycle_daily WHERE trade_date = ? AND symbol = ?",
        (trade_date.isoformat(), symbol),
    ).fetchone()

    decision = Decision(
        symbol=symbol, name=name, friend_group=friend_group, trade_date=trade_date,
        cycle_state=CycleState(cycle_row["cycle_state"]) if cycle_row and cycle_row["cycle_state"] else CycleState.DOWNTREND,
        reversal_core_score=row["reversal_core_score"] or 0.0,
        adx_gate=Gate(row["adx_gate"]) if row["adx_gate"] else Gate.CAUTION,
        pullback_score=row["pullback_score"] or 0.0, late_stage_score=row["late_stage_score"] or 0.0,
        action=Action(row["action"]), reasons=json.loads(row["reasons_json"] or "[]"),
        stop_price=None,
    )

    ind = conn.execute(
        "SELECT * FROM indicators_daily WHERE trade_date = ? AND symbol = ?",
        (trade_date.isoformat(), symbol),
    ).fetchone()

    last_high = conn.execute(
        "SELECT dow_label, price FROM pivots WHERE symbol = ? AND pivot_type = 'HIGH' AND confirm_date <= ? ORDER BY confirm_date DESC LIMIT 1",
        (symbol, trade_date.isoformat()),
    ).fetchone()
    last_low = conn.execute(
        "SELECT dow_label, price FROM pivots WHERE symbol = ? AND pivot_type = 'LOW' AND confirm_date <= ? ORDER BY confirm_date DESC LIMIT 1",
        (symbol, trade_date.isoformat()),
    ).fetchone()
    pivot_labels = {}
    if last_high and last_high["dow_label"]:
        pivot_labels[last_high["dow_label"]] = last_high["price"]
    if last_low and last_low["dow_label"]:
        pivot_labels[last_low["dow_label"]] = last_low["price"]

    return ReportCard(
        decision=decision,
        dow_state=(cycle_row["dow_state"] if cycle_row and cycle_row["dow_state"] else "-"),
        macd=(ind["macd"] if ind else None) or 0.0,
        macd_signal=(ind["macd_signal"] if ind else None) or 0.0,
        macd_above_zero=bool(ind and ind["macd"] and ind["macd"] > 0),
        rsi14=(ind["rsi14"] if ind else None) or 0.0,
        rsi_above_25=bool(ind and ind["rsi14"] and ind["rsi14"] > 25.0),
        rsi_above_50=bool(ind and ind["rsi14"] and ind["rsi14"] > 50.0),
        adx=(ind["adx14"] if ind else None) or 0.0,
        mdi=(ind["mdi14"] if ind else None) or 0.0,
        last_pivot_labels=pivot_labels,
    )


def run_report(trade_date: date, retention_days: int | None = None, base_dir: Path | None = None) -> dict:
    run_migrations()
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM scores_daily WHERE trade_date = ?", (trade_date.isoformat(),)).fetchall()
        if not rows:
            return {"status": "NO_DECISIONS", "trade_date": trade_date.isoformat()}

        cards = [_build_card(conn, row, trade_date) for row in rows]
        paths = save_report(cards, trade_date, base_dir=base_dir)

        retention = retention_days if retention_days is not None else load_yaml_config("app.yml").get("reports", {}).get("retention_days", 90)
        removed = cleanup_old_reports(base_dir=base_dir, retention_days=retention)
        if removed:
            logger.info("[daily_report_job] 보존기한(%s일) 초과로 %d개 리포트 디렉토리 삭제", retention, len(removed))

        return {
            "status": "OK", "trade_date": trade_date.isoformat(), "card_count": len(cards),
            "paths": {k: str(v) for k, v in paths.items()}, "cleaned_up": len(removed),
        }
    finally:
        conn.close()
