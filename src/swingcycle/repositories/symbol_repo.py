"""symbols 로컬 캐시 + Supabase 동기화.

설계: docs/SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md 7.3
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def sync_from_supabase(conn: sqlite3.Connection, supabase_rows: list[dict]) -> None:
    """Supabase swingcycle_symbols 전체를 읽어와 로컬 symbols에 반영한다 (7.3 표 그대로).

    - 신규/이름/그룹 변경: upsert
    - enabled=false (soft-disable) 또는 Supabase에서 완전 삭제(하드 delete, 즉 supabase_rows에
      더 이상 없음): 로컬은 절대 하드 삭제하지 않는다. enabled=0으로 두고, 완전 삭제된 경우만
      deleted_upstream=1도 같이 세팅한다.
    """
    now = datetime.now(timezone.utc).isoformat()
    supabase_symbols = {row["symbol"] for row in supabase_rows}

    for row in supabase_rows:
        existing = conn.execute("SELECT market FROM symbols WHERE symbol = ?", (row["symbol"],)).fetchone()
        market = existing["market"] if existing and existing["market"] else None
        conn.execute(
            """
            INSERT INTO symbols (symbol, name, market, friend_group, enabled, deleted_upstream, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                name = excluded.name,
                friend_group = excluded.friend_group,
                enabled = excluded.enabled,
                deleted_upstream = 0,
                updated_at = excluded.updated_at
            """,
            (row["symbol"], row["name"], market, row.get("friend_group"), int(bool(row.get("enabled", True))), now, now),
        )

    local_symbols = {r["symbol"] for r in conn.execute("SELECT symbol FROM symbols").fetchall()}
    hard_deleted = local_symbols - supabase_symbols
    for symbol in hard_deleted:
        conn.execute(
            "UPDATE symbols SET enabled = 0, deleted_upstream = 1, updated_at = ? WHERE symbol = ?",
            (now, symbol),
        )
    conn.commit()


def backfill_market_if_missing(conn: sqlite3.Connection, symbol: str, market: str) -> None:
    """6.6 역보정 규칙 — market이 NULL인 경우에만 채운다(수동 보정 존중)."""
    conn.execute(
        "UPDATE symbols SET market = ? WHERE symbol = ? AND market IS NULL",
        (market, symbol),
    )
    conn.commit()


def active_symbols(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT symbol FROM symbols WHERE enabled = 1").fetchall()
    return [r["symbol"] for r in rows]


def has_active_trade_plan(conn: sqlite3.Connection, symbol: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM trade_plans WHERE symbol = ? AND status = 'ACTIVE' LIMIT 1", (symbol,)
    ).fetchone()
    return row is not None
