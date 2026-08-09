import sqlite3
from datetime import date, datetime, timezone

import pandas as pd


def fetch_bars(
    conn: sqlite3.Connection, symbol: str, *, end_date: date | None = None, lookback: int | None = None,
) -> pd.DataFrame:
    """`symbol`의 일봉을 trade_date 오름차순으로 반환한다.

    - `end_date`: 지정하면 그 날짜까지(포함)만 조회 — 지표는 계산 시점 이후 데이터를
      절대 참조해서는 안 되므로(선행 참조 금지), 배치/백테스트 모두 반드시 이 파라미터로
      "그 시점까지의 데이터"만 넘겨야 한다.
    - `lookback`: 지정하면 (end_date 이전 포함) 최근 N개 행만 반환.
    """
    query = "SELECT trade_date, open, high, low, close, volume FROM daily_bars WHERE symbol = ?"
    params: list = [symbol]
    if end_date is not None:
        query += " AND trade_date <= ?"
        params.append(end_date.isoformat())
    query += " ORDER BY trade_date ASC"

    df = pd.read_sql_query(query, conn, params=params, parse_dates=["trade_date"])
    if lookback is not None and len(df) > lookback:
        df = df.iloc[-lookback:].reset_index(drop=True)
    return df


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
