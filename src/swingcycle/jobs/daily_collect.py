"""swingcycle collect — 설계서 20.1 1단계.

Supabase 동기화 -> 거래일 확인 -> KRX/pykrx 수집 -> 정규화/검증 -> upsert -> market 역보정.
"""
from __future__ import annotations

import logging
from datetime import date

from ..data.market_data_service import MarketDataService
from ..data.supabase_client import fetch_all_symbols, get_supabase_client
from ..data.trading_calendar import NoTradingDayError, ensure_trading_day
from ..repositories import daily_bar_repo, symbol_repo
from ..repositories.db import get_connection, run_migrations

logger = logging.getLogger("daily_collect")


def run_collect(trade_date: date) -> dict:
    run_migrations()
    conn = get_connection()
    try:
        supabase_rows: list[dict] = []
        try:
            supabase_rows = fetch_all_symbols()
            symbol_repo.sync_from_supabase(conn, supabase_rows)
        except RuntimeError as exc:
            logger.warning("[daily_collect] Supabase 동기화 건너뜀: %s", exc)

        try:
            ensure_trading_day(trade_date)
        except NoTradingDayError as exc:
            logger.info("[daily_collect] %s", exc)
            return {"status": "NO_TRADING_DAY", "trade_date": trade_date.isoformat()}

        universe = set(symbol_repo.collectable_symbols(conn))
        if not universe:
            logger.warning("[daily_collect] 활성 종목이 없습니다 — seed_friend_universe.py 실행 여부 확인")
            return {"status": "EMPTY_UNIVERSE", "trade_date": trade_date.isoformat()}

        service = MarketDataService()
        df = service.fetch_universe_bars(trade_date, universe)
        row_count = daily_bar_repo.upsert_daily_bars(conn, df)

        for _, row in df.iterrows():
            if row.get("market"):
                symbol_repo.backfill_market_if_missing(conn, row["symbol"], row["market"])

        supabase_market_by_symbol = {r["symbol"]: r.get("market") for r in supabase_rows}
        market_updates = symbol_repo.select_new_market_backfills(
            df.to_dict("records"), supabase_market_by_symbol
        )
        if market_updates:
            try:
                symbol_repo.push_market_backfill_to_supabase(get_supabase_client(), market_updates)
            except Exception as exc:
                logger.warning("[daily_collect] market Supabase 반영 실패: %s", exc)

        return {"status": "OK", "trade_date": trade_date.isoformat(), "rows": row_count}
    finally:
        conn.close()
