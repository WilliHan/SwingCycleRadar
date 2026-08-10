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
        local_market = existing["market"] if existing and existing["market"] else None
        # 로컬 값이 이미 있으면 그대로 존중, 없으면 Supabase 쪽 값으로 채운다(예: KRX 직접수집
        # 경로가 없는 배포 — 로컬에서 market을 알아낼 방법이 아예 없는 parquet 경로).
        market = local_market or row.get("market") or None
        conn.execute(
            """
            INSERT INTO symbols (symbol, name, market, friend_group, enabled, sort_order, deleted_upstream, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                name = excluded.name,
                friend_group = excluded.friend_group,
                enabled = excluded.enabled,
                sort_order = excluded.sort_order,
                deleted_upstream = 0,
                updated_at = excluded.updated_at
            """,
            (
                row["symbol"], row["name"], market, row.get("friend_group"),
                int(bool(row.get("enabled", True))), row.get("sort_order"), now, now,
            ),
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


def select_new_market_backfills(
    krx_rows: list[dict], supabase_market_by_symbol: dict[str, str | None]
) -> list[dict]:
    """KRX 응답에서 market을 얻었고 Supabase 쪽엔 아직 비어있는 종목만 골라 push 대상으로 만든다.

    backfill_market_if_missing은 로컬 SQLite만 갱신하고 Supabase(종목관리 UI가 보는 원본)에는
    반영하지 않던 설계 공백을 메운다. 이미 Supabase에 값이 있으면(수동 보정 포함) 건드리지 않는다.
    """
    updates = []
    seen = set()
    for row in krx_rows:
        symbol, market = row.get("symbol"), row.get("market")
        if market and symbol not in seen and not supabase_market_by_symbol.get(symbol):
            updates.append({"symbol": symbol, "market": market})
            seen.add(symbol)
    return updates


def push_market_backfill_to_supabase(client, updates: list[dict]) -> None:
    if updates:
        client.table("swingcycle_symbols").upsert(updates).execute()


def active_symbols(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT symbol FROM symbols WHERE enabled = 1").fetchall()
    return [r["symbol"] for r in rows]


def collectable_symbols(conn: sqlite3.Connection) -> list[str]:
    """일일 수집 대상 종목: enabled=1 인 종목 + (비활성/upstream 삭제됐어도, 심지어
    symbols row 자체가 없어도) ACTIVE trade_plan이 남아있는 종목.

    설계 7.3 — "비활성화는 신규 진입 금지를 의미하지, 기존 포지션 방치를 의미하지
    않는다." active_symbols()만 쓰면 disable/삭제 직후 열려 있는 포지션의 STOP/EXIT
    판정을 계속할 데이터가 끊긴다(전문가 리뷰에서 발견).

    UNION으로 trade_plans를 독립 조회한다 — symbols를 기준으로 LEFT JOIN하면
    symbols row 자체가 (비정상 복구 등으로) 없는 경우 ACTIVE 플랜이 있어도 결과에서
    빠지는 문제가 있었다(전문가 리뷰 2차 지적). trade_plans는 symbols와 무관하게
    항상 그 자체로 조회한다.
    """
    rows = conn.execute(
        """
        SELECT symbol FROM symbols WHERE enabled = 1
        UNION
        SELECT symbol FROM trade_plans WHERE status = 'ACTIVE'
        """
    ).fetchall()
    return [r["symbol"] for r in rows]


def has_active_trade_plan(conn: sqlite3.Connection, symbol: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM trade_plans WHERE symbol = ? AND status = 'ACTIVE' LIMIT 1", (symbol,)
    ).fetchone()
    return row is not None


def get_symbol(conn: sqlite3.Connection, symbol: str) -> sqlite3.Row | None:
    """symbols row 자체가 없는 경우도 있다(collectable_symbols의 ACTIVE-plan-only 케이스,
    7.3 참고) — 호출부는 None을 종목명 미상 fallback으로 처리해야 한다."""
    return conn.execute("SELECT * FROM symbols WHERE symbol = ?", (symbol,)).fetchone()
