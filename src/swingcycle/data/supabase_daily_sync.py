"""배치(decide) 산출물을 Supabase에 기록하고, 로컬에 없는 최근 이력을 당겨온다.

설계 배경: 대시보드는 계속 로컬 SQLite(indicators_daily/cycle_daily/scores_daily/pivots)를
읽는다(속도·오프라인 내성 유지) — Supabase는 "기록 + 새 환경 부트스트랩 시 이력 보완" 용도로만
쓴다. 스키마는 sql/supabase_swingcycle_daily.sql(로컬 SQLite 컬럼을 그대로 미러링) 참고.

push_daily_snapshot: 테이블당 upsert 1회(총 4회, 종목 수와 무관) — 대량 개별 호출을 피한다.
reconcile_recent_history: 로컬에 이미 있는 (trade_date, symbol) 조합은 절대 덮어쓰지 않는다
(symbol_repo.backfill_market_if_missing과 동일한 "존중" 원칙) — 빈 곳만 채운다.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

_TABLE_SPECS = [
    {
        "local_table": "indicators_daily",
        "remote_table": "swingcycle_indicators_daily",
        "date_col": "trade_date",
        "key_cols": ("trade_date", "symbol"),
        "columns": (
            "trade_date", "symbol", "sma5", "sma20", "sma60", "sma120", "sma240",
            "ema12", "ema26", "macd", "macd_signal", "macd_hist", "rsi14", "rsi_signal",
            "pdi14", "mdi14", "adx14", "vo10_20", "ma5_distance_pct",
        ),
    },
    {
        "local_table": "cycle_daily",
        "remote_table": "swingcycle_cycle_daily",
        "date_col": "trade_date",
        "key_cols": ("trade_date", "symbol"),
        "columns": (
            "trade_date", "symbol", "cycle_state", "dow_state",
            "last_pivot_high_date", "last_pivot_high", "last_pivot_low_date", "last_pivot_low",
        ),
    },
    {
        "local_table": "scores_daily",
        "remote_table": "swingcycle_scores_daily",
        "date_col": "trade_date",
        "key_cols": ("trade_date", "symbol"),
        "columns": (
            "trade_date", "symbol", "reversal_core_score", "adx_gate", "pullback_score",
            "late_stage_score", "action", "reasons_json", "stop_price", "entry_type",
        ),
    },
    {
        "local_table": "pivots",
        "remote_table": "swingcycle_pivots",
        "date_col": "confirm_date",
        "key_cols": ("symbol", "pivot_date", "pivot_type"),
        "columns": (
            "symbol", "pivot_date", "confirm_date", "pivot_type", "price",
            "left_bars", "right_bars", "dow_label",
        ),
    },
]


def push_daily_snapshot(client, trade_date_: date, conn: sqlite3.Connection) -> dict:
    """`trade_date_`(pivots는 confirm_date) 하루치를 4개 테이블 각각 upsert 1회로 push."""
    counts: dict[str, int] = {}
    for spec in _TABLE_SPECS:
        rows = conn.execute(
            f"SELECT * FROM {spec['local_table']} WHERE {spec['date_col']} = ?",
            (trade_date_.isoformat(),),
        ).fetchall()
        payload = [dict(r) for r in rows]
        if payload:
            client.table(spec["remote_table"]).upsert(payload).execute()
        counts[spec["remote_table"]] = len(payload)
    return counts


def reconcile_recent_history(conn: sqlite3.Connection, client, lookback_days: int = 15) -> dict:
    """Supabase에는 있지만 로컬엔 없는 최근 `lookback_days`일 이력만 채운다.
    로컬에 이미 있는 (trade_date, symbol) 조합은 절대 건드리지 않는다."""
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    counts: dict[str, int] = {}
    for spec in _TABLE_SPECS:
        remote_rows = (
            client.table(spec["remote_table"]).select("*").gte(spec["date_col"], cutoff).execute().data or []
        )
        if not remote_rows:
            counts[spec["remote_table"]] = 0
            continue

        key_cols_sql = ", ".join(spec["key_cols"])
        local_keys = {
            tuple(row[c] for c in spec["key_cols"])
            for row in conn.execute(
                f"SELECT {key_cols_sql} FROM {spec['local_table']} WHERE {spec['date_col']} >= ?",
                (cutoff,),
            ).fetchall()
        }
        missing = [
            row for row in remote_rows
            if tuple(row.get(c) for c in spec["key_cols"]) not in local_keys
        ]
        if missing:
            cols_sql = ", ".join(spec["columns"])
            placeholders = ", ".join("?" for _ in spec["columns"])
            conn.executemany(
                f"INSERT OR IGNORE INTO {spec['local_table']} ({cols_sql}) VALUES ({placeholders})",
                [tuple(row.get(c) for c in spec["columns"]) for row in missing],
            )
            conn.commit()
        counts[spec["remote_table"]] = len(missing)
    return counts
