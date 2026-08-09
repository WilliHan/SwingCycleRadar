"""trade_plans / trade_events 저장소. 스키마: migrations/001_init.sql."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone


def create_plan(
    conn: sqlite3.Connection, *, symbol: str, created_date: str, entry_type: str,
    stop_price: float, planned_entry: float | None = None, stop_basis_pivot_date: str | None = None,
) -> str:
    """새 ACTIVE 플랜 생성. 종목당 ACTIVE 플랜은 1개만 허용된다 — 위반 시
    `idx_trade_plans_one_active_per_symbol` 유니크 인덱스가 sqlite3.IntegrityError를 낸다
    (이전 플랜이 STOPPED/CLOSED/RESET이면 문제없이 재진입 가능)."""
    plan_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO trade_plans
            (plan_id, symbol, created_date, entry_type, planned_entry, stop_price, stop_basis_pivot_date, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
        """,
        (plan_id, symbol, created_date, entry_type, planned_entry, stop_price, stop_basis_pivot_date),
    )
    conn.commit()
    return plan_id


def get_active_plan(conn: sqlite3.Connection, symbol: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM trade_plans WHERE symbol = ? AND status = 'ACTIVE'", (symbol,),
    ).fetchone()


def close_plan(conn: sqlite3.Connection, plan_id: str, status: str) -> None:
    if status not in ("STOPPED", "CLOSED", "RESET"):
        raise ValueError(f"ACTIVE로 되돌리는 close_plan 호출은 불가: status={status!r}")
    conn.execute("UPDATE trade_plans SET status = ? WHERE plan_id = ?", (status, plan_id))
    conn.commit()


def record_event(
    conn: sqlite3.Connection, *, plan_id: str, trade_date: str, event_type: str,
    price: float | None = None, qty_weight: float | None = None, note: str | None = None,
) -> str:
    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO trade_events (event_id, plan_id, trade_date, event_type, price, qty_weight, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (event_id, plan_id, trade_date, event_type, price, qty_weight, note, now),
    )
    conn.commit()
    return event_id


def list_events(conn: sqlite3.Connection, plan_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM trade_events WHERE plan_id = ? ORDER BY created_at ASC", (plan_id,),
    ).fetchall()
