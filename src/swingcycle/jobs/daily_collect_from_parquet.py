"""swingcycle collect-parquet — daily_collect.py의 대안 1단계.

daily_collect.py는 KRX/pykrx에서 그날 하루치만 직접 수집한다. 이 잡은 대신 MFTS가
매일 새벽(Oracle 서버, run_collect_and_backfill.sh) 이미 갱신해둔
`{MFTS}/@RUN/cache/parquet/{symbol}.parquet`을 읽는다 — 같은 서버에 배포하면
rsync/scp 없이 로컬 파일로 바로 접근 가능하고, KRX를 별도로 또 두드리지 않아도 된다
(사용자 지시: 절친종목 검토엔 이미 MFTS가 수집한 데이터를 재사용하는 게 데이터 효율적).

MFTS의 parquet 캐시는 전체 시장(수천 종목)을 담고 있지만, 여기서는 swingcycle_symbols
(절친 유니버스, 통상 수십 종목)에 해당하는 파일만 골라 읽는다 — 관계없는 종목까지
매일 재적재하면 낭비다.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from ..data.supabase_client import fetch_all_symbols
from ..data.trading_calendar import NoTradingDayError, ensure_trading_day
from ..domain.enums import DataSource
from ..repositories import daily_bar_repo, symbol_repo
from ..repositories.db import get_connection, run_migrations

logger = logging.getLogger("daily_collect_from_parquet")


def load_symbol_parquet(path: Path) -> pd.DataFrame:
    """MFTS parquet(index='날짜', open/high/low/close/volume/amount_krw) ->
    daily_bars 스키마로 변환. 파일명 자체가 종목코드다(005930.parquet -> "005930")."""
    symbol = path.stem
    raw = pd.read_parquet(path)
    raw = raw.reset_index()
    date_col = raw.columns[0]  # 인덱스가 "날짜"였던 컬럼 — reset_index 후 첫 컬럼
    raw = raw.rename(columns={date_col: "trade_date", "amount_krw": "trade_value"})
    raw["trade_date"] = pd.to_datetime(raw["trade_date"]).dt.strftime("%Y-%m-%d")
    raw["symbol"] = symbol
    if "trade_value" not in raw.columns:  # 일부 캐시 파일엔 거래대금 컬럼이 아예 없다
        raw["trade_value"] = None
    raw["market_cap"] = None
    raw["source"] = DataSource.MFTS_PARQUET.value
    raw["source_raw_hash"] = None
    return raw[[
        "trade_date", "symbol", "open", "high", "low", "close", "volume",
        "trade_value", "market_cap", "source", "source_raw_hash",
    ]]


def run_collect_from_parquet(trade_date: date, parquet_dir: str) -> dict:
    run_migrations()
    conn = get_connection()
    try:
        try:
            supabase_rows = fetch_all_symbols()
            symbol_repo.sync_from_supabase(conn, supabase_rows)
        except RuntimeError as exc:
            logger.warning("[daily_collect_from_parquet] Supabase 동기화 건너뜀: %s", exc)

        try:
            ensure_trading_day(trade_date)
        except NoTradingDayError as exc:
            logger.info("[daily_collect_from_parquet] %s", exc)
            return {"status": "NO_TRADING_DAY", "trade_date": trade_date.isoformat()}

        universe = symbol_repo.collectable_symbols(conn)
        if not universe:
            logger.warning("[daily_collect_from_parquet] 활성 종목이 없습니다")
            return {"status": "EMPTY_UNIVERSE", "trade_date": trade_date.isoformat()}

        base = Path(parquet_dir)
        row_count = 0
        missing: list[str] = []
        stale: list[str] = []
        for symbol in universe:
            path = base / f"{symbol}.parquet"
            if not path.exists():
                missing.append(symbol)
                continue
            df = load_symbol_parquet(path)
            if df.empty or df["trade_date"].max() < trade_date.isoformat():
                # MFTS가 아직 오늘자를 못 채운 경우(장애/지연) — 있는 데이터까진 넣되 표시해둔다.
                stale.append(symbol)
            row_count += daily_bar_repo.upsert_daily_bars(conn, df)
        conn.commit()

        if missing:
            logger.warning("[daily_collect_from_parquet] parquet 없음(%d): %s", len(missing), missing)
        if stale:
            logger.warning(
                "[daily_collect_from_parquet] %s자 데이터 없음(%d, MFTS 지연 가능성): %s",
                trade_date.isoformat(), len(stale), stale,
            )

        return {
            "status": "OK", "trade_date": trade_date.isoformat(), "rows": row_count,
            "missing_parquet": missing, "stale": stale,
        }
    finally:
        conn.close()
