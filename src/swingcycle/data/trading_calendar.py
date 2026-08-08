"""거래일 판정. 설계서 24.1 "휴장일은 오류가 아니라 NO_TRADING_DAY로 처리".

v1 최소 구현: 주말만 휴장으로 판정한다. 공휴일 캘린더 연동은 후속 작업
(pykrx.stock.get_nearest_business_day_in_a_week 등)으로 보강한다.
"""
from __future__ import annotations

from datetime import date


class NoTradingDayError(Exception):
    def __init__(self, trade_date: date) -> None:
        super().__init__(f"NO_TRADING_DAY: {trade_date.isoformat()}")
        self.trade_date = trade_date


def is_trading_day(trade_date: date) -> bool:
    return trade_date.weekday() < 5  # 0=Mon .. 4=Fri


def ensure_trading_day(trade_date: date) -> None:
    if not is_trading_day(trade_date):
        raise NoTradingDayError(trade_date)
