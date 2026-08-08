"""KRX Direct primary + pykrx fallback 오케스트레이션.

설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 6.1, 6.5
"한 날짜의 KOSPI/KOSDAQ 전체 시장 데이터를 먼저 수집한 뒤 절친 universe만 필터링."
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from .krx_client import KRXClient, KRXDirectError, krx_response_to_dataframe
from .normalizer import validate_daily_bars
from .pykrx_client import PykrxClient

logger = logging.getLogger("market_data_service")


class MarketDataService:
    def __init__(self) -> None:
        self.krx_client = KRXClient()
        self.pykrx_client = PykrxClient()

    def fetch_universe_bars(self, trade_date: date, universe_symbols: set[str]) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        krx_symbols_found: set[str] = set()

        for market in ("KOSPI", "KOSDAQ"):
            try:
                response = self.krx_client.fetch_daily_market(market, trade_date)
                df = krx_response_to_dataframe(response)
            except KRXDirectError as exc:
                logger.warning("[market_data_service] krx_direct 실패(market=%s): %s", market, exc)
                continue
            if df.empty:
                continue
            df = df[df["symbol"].isin(universe_symbols)]
            krx_symbols_found |= set(df["symbol"])
            frames.append(df)

        missing = universe_symbols - krx_symbols_found
        if missing:
            logger.info("[market_data_service] pykrx fallback 대상 %d개: %s", len(missing), sorted(missing))
            for symbol in missing:
                try:
                    fb = self.pykrx_client.fetch_symbol_ohlcv(symbol, trade_date - timedelta(days=1), trade_date)
                    fb = fb[fb["trade_date"] == pd.Timestamp(trade_date)]
                    if not fb.empty:
                        frames.append(fb)
                except Exception as exc:  # pragma: no cover - 네트워크 의존
                    logger.warning("[market_data_service] pykrx fallback 실패(symbol=%s): %s", symbol, exc)

        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames, ignore_index=True)
        # 동일 (trade_date, symbol)에 KRX_DIRECT/PYKRX 모두 있으면 KRX_DIRECT 우선 (6.1-3)
        combined["_source_priority"] = combined["source"].map({"KRX_DIRECT": 0, "PYKRX": 1}).fillna(1)
        combined = combined.sort_values("_source_priority").drop_duplicates(subset=["symbol", "trade_date"], keep="first")
        combined = combined.drop(columns=["_source_priority"])
        return validate_daily_bars(combined)
