"""거래일 판정. 설계서 24.1 "휴장일은 오류가 아니라 NO_TRADING_DAY로 처리".

v1 최소 구현: 주말만 휴장으로 판정한다. 공휴일 캘린더 연동은 후속 작업
(pykrx.stock.get_nearest_business_day_in_a_week 등)으로 보강한다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")


class NoTradingDayError(Exception):
    def __init__(self, trade_date: date) -> None:
        super().__init__(f"NO_TRADING_DAY: {trade_date.isoformat()}")
        self.trade_date = trade_date


def is_trading_day(trade_date: date) -> bool:
    return trade_date.weekday() < 5  # 0=Mon .. 4=Fri


def ensure_trading_day(trade_date: date) -> None:
    if not is_trading_day(trade_date):
        raise NoTradingDayError(trade_date)


def latest_completed_trading_day(now: datetime | None = None) -> date:
    """가장 최근 완료된 거래일(주말만 제외, 공휴일 미반영)을 반환한다.

    SwingCycle 일별 배치(run_daily_batch_parquet.sh)는 MFTS의 로컬 parquet
    캐시를 읽는데, MFTS 자신은 KST 01:00 크론에서 "직전 거래일" 데이터를
    이 함수와 동일한 정책(MFTS/batch/date_policy.py의
    resolve_latest_completed_trading_day)으로 계산해 수집한다. SwingCycle
    배치가 "오늘"을 기본값으로 쓰면 MFTS가 아직 채우지 않은 날짜를 요청하게
    되어 전 종목이 stale 처리되는 문제가 있었다(2026-08-11~08-12 실측)
    — 반드시 이 함수로 계산한 날짜를 기본 대상일로 써야 한다.
    """
    current = now.astimezone(_KST) if now and now.tzinfo else (
        now.replace(tzinfo=_KST) if now else datetime.now(_KST)
    )
    anchor = current.date() - timedelta(days=1)
    while anchor.weekday() >= 5:
        anchor -= timedelta(days=1)
    return anchor
