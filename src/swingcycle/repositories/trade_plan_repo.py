"""trade_plans / trade_events 저장소. 스키마: migrations/001_init.sql.

**커밋 책임은 호출자에게 있다** — 이 모듈의 함수들은 `conn.execute()`만 하고
`conn.commit()`을 호출하지 않는다. STOP 처리(risk/reset.py)처럼 "플랜 종료 + 이벤트
기록 + 그날의 scores_daily 저장"이 하나의 원자적 단위여야 하는 호출부가 있는데,
여기서 각 함수가 즉시 커밋해버리면 그 사이 다른 단계가 실패했을 때 "플랜은 이미
닫혔는데 그날 분석 결과는 없는" 부분 반영 상태가 남는다(재실행해도 플랜이 더 이상
ACTIVE가 아니라 STOP이 다시 감지되지 않아 영구히 누락됨 — 실제 리뷰에서 발견된 버그).
호출부(jobs/daily_decide.py)가 관련 작업을 전부 마친 뒤 한 번에 commit/rollback한다."""
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
    return plan_id


def get_active_plan(conn: sqlite3.Connection, symbol: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM trade_plans WHERE symbol = ? AND status = 'ACTIVE'", (symbol,),
    ).fetchone()


def close_plan(conn: sqlite3.Connection, plan_id: str, status: str) -> None:
    if status not in ("STOPPED", "CLOSED", "RESET"):
        raise ValueError(f"ACTIVE로 되돌리는 close_plan 호출은 불가: status={status!r}")
    conn.execute("UPDATE trade_plans SET status = ? WHERE plan_id = ?", (status, plan_id))


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
    return event_id


def list_events(conn: sqlite3.Connection, plan_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM trade_events WHERE plan_id = ? ORDER BY created_at ASC", (plan_id,),
    ).fetchall()
