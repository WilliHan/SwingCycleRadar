from __future__ import annotations

from datetime import date, datetime

from swingcycle.data.trading_calendar import latest_completed_trading_day


def test_latest_completed_trading_day_returns_previous_day_for_weekday_run() -> None:
    now = datetime(2026, 8, 13, 5, 30, 0)  # Thu 05:30 KST 배치 (변경 후 실제 크론 시각)
    assert latest_completed_trading_day(now) == date(2026, 8, 12)


def test_latest_completed_trading_day_skips_weekend() -> None:
    now = datetime(2026, 8, 10, 5, 30, 0)  # Mon 05:30 KST 배치 — 어제(일)는 거래일 아님
    assert latest_completed_trading_day(now) == date(2026, 8, 7)  # 직전 금요일


def test_latest_completed_trading_day_defaults_to_now() -> None:
    # now=None이어도 예외 없이 date를 반환해야 한다(실제 크론 실행 경로).
    result = latest_completed_trading_day()
    assert isinstance(result, date)
