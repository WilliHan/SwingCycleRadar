from datetime import date

import pandas as pd
import pytest

from swingcycle.repositories import daily_bar_repo
from swingcycle.repositories.db import get_connection, run_migrations
from swingcycle.settings import settings


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    run_migrations()
    c = get_connection()
    yield c
    c.close()


def _bars(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "trade_date": dates,
        "symbol": ["005930"] * len(dates),
        "open": [100.0] * len(dates),
        "high": [101.0] * len(dates),
        "low": [99.0] * len(dates),
        "close": [100.5] * len(dates),
        "volume": [1000] * len(dates),
        "trade_value": [None] * len(dates),
        "market_cap": [None] * len(dates),
        "source": ["krx_direct"] * len(dates),
        "source_raw_hash": [None] * len(dates),
    })


def test_fetch_bars_returns_ascending_order(conn):
    daily_bar_repo.upsert_daily_bars(conn, _bars(["2026-01-03", "2026-01-01", "2026-01-02"]))
    out = daily_bar_repo.fetch_bars(conn, "005930")
    assert list(out["trade_date"].dt.strftime("%Y-%m-%d")) == ["2026-01-01", "2026-01-02", "2026-01-03"]


def test_fetch_bars_respects_end_date_no_lookahead(conn):
    daily_bar_repo.upsert_daily_bars(conn, _bars(["2026-01-01", "2026-01-02", "2026-01-03"]))
    out = daily_bar_repo.fetch_bars(conn, "005930", end_date=date(2026, 1, 2))
    assert list(out["trade_date"].dt.strftime("%Y-%m-%d")) == ["2026-01-01", "2026-01-02"]


def test_fetch_bars_lookback_limits_rows(conn):
    daily_bar_repo.upsert_daily_bars(conn, _bars(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]))
    out = daily_bar_repo.fetch_bars(conn, "005930", lookback=2)
    assert list(out["trade_date"].dt.strftime("%Y-%m-%d")) == ["2026-01-03", "2026-01-04"]


def test_fetch_bars_only_returns_requested_symbol(conn):
    daily_bar_repo.upsert_daily_bars(conn, _bars(["2026-01-01"]))
    other = _bars(["2026-01-01"])
    other["symbol"] = "000660"
    daily_bar_repo.upsert_daily_bars(conn, other)

    out = daily_bar_repo.fetch_bars(conn, "005930")
    assert len(out) == 1
