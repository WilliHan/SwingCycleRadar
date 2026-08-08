import sqlite3
from datetime import datetime, timezone

import pandas as pd


def upsert_daily_bars(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    """idempotent upsert (6장 요청 정책 — 동일 날짜 재실행은 idempotent upsert)."""
    if df.empty:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            r["trade_date"], r["symbol"], r["open"], r["high"], r["low"], r["close"],
            int(r["volume"]) if pd.notna(r.get("volume")) else 0,
            r.get("trade_value"), r.get("market_cap"), r["source"], r.get("source_raw_hash"), now,
        )
        for _, r in df.iterrows()
    ]
    conn.executemany(
        """
        INSERT INTO daily_bars
            (trade_date, symbol, open, high, low, close, volume, trade_value, market_cap, source, source_raw_hash, collected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date, symbol) DO UPDATE SET
            open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
            volume=excluded.volume, trade_value=excluded.trade_value, market_cap=excluded.market_cap,
            source=excluded.source, source_raw_hash=excluded.source_raw_hash, collected_at=excluded.collected_at
        """,
        rows,
    )
    conn.commit()
    return len(rows)
