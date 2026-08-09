"""RESET 처리. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 16.4.

RESET이 지우지 않는 것: 시장 데이터/지표/과거 pivot/과거 trade_events.
RESET이 지우는 것: 현재 active plan, 진입가격 앵커, 현재 포지션 기대.

이 스키마(migrations/001_init.sql)에는 "진입가격 앵커"를 담는 별도 테이블이 없다 —
trade_plans.status를 ACTIVE가 아닌 값으로 바꾸는 것 자체가 앵커 해제다(다음 create_plan
호출이 idx_trade_plans_one_active_per_symbol에 걸리지 않고 재진입 가능해짐).
"""
from __future__ import annotations

import sqlite3

from ..repositories import trade_plan_repo


def apply_stop_and_reset(conn: sqlite3.Connection, *, plan_id: str, trade_date: str, fill_price: float) -> None:
    """stop 체결 확정 시 호출. 16.4의 close_plan -> emit(STOP) -> emit(RESET) 순서를 그대로 따른다."""
    trade_plan_repo.close_plan(conn, plan_id, status="STOPPED")
    trade_plan_repo.record_event(
        conn, plan_id=plan_id, trade_date=trade_date, event_type="STOP", price=fill_price,
    )
    trade_plan_repo.record_event(
        conn, plan_id=plan_id, trade_date=trade_date, event_type="RESET",
    )
