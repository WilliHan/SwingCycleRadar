"""pykrx fallback. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 6.5"""
from __future__ import annotations

from datetime import date

import pandas as pd

from ..settings import strip_pykrx_legacy_env
from .krx_web_session import KRXWebSession


class PykrxClient:
    def fetch_symbol_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        # pykrx도 KRX 웹 로그인이 필요하므로 krx_client와 같은 세션을 재사용한다
        # (6.5 — 각자 독립 로그인하면 IP 차단 위험이 두 배가 된다).
        # get_authenticated_session()의 반환값은 안 쓰지만, 로그인 성공 시
        # _do_login 내부에서 _patch_pykrx()가 호출되는 부수효과가 필요하다.
        KRXWebSession.instance().get_authenticated_session()

        # 방어적 이중 처리: settings import 시점에 이미 KRX_ID/KRX_PW를 제거하지만,
        # 향후 리팩터링으로 import 순서가 바뀌어도 pykrx import 직전에 한 번 더 막는다.
        strip_pykrx_legacy_env()

        from pykrx import stock

        df = stock.get_market_ohlcv_by_date(
            start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), symbol
        )
        df = df.rename(columns={
            "시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume",
        })
        df["symbol"] = symbol
        df["source"] = "PYKRX"
        df["market"] = None  # pykrx 단일 종목 조회는 시장 구분을 안 주므로 역보정 대상에서 제외
        return df.reset_index().rename(columns={"날짜": "trade_date"})
