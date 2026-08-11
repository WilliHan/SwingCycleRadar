from datetime import date

import pytest

from swingcycle.jobs import update_latest
from swingcycle.repositories.db import get_connection, run_migrations
from swingcycle.settings import settings


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    run_migrations()
    c = get_connection()
    yield c
    c.close()


def test_uses_latest_local_trade_date_when_available(conn, monkeypatch):
    conn.execute(
        "INSERT INTO scores_daily (trade_date, symbol, reasons_json) VALUES ('2026-08-07', '005930', '[]')"
    )
    conn.commit()

    seen_dates = []
    monkeypatch.setattr(
        update_latest, "run_collect_from_parquet",
        lambda trade_date_, parquet_dir: seen_dates.append(trade_date_) or {"status": "OK", "rows": 0},
    )
    monkeypatch.setattr(
        update_latest, "run_decide",
        lambda trade_date_: seen_dates.append(trade_date_) or {"status": "OK", "processed": 0},
    )

    trade_date_, collect_result, decide_result = update_latest.run_update_latest()

    assert trade_date_ == date(2026, 8, 7)
    assert seen_dates == [date(2026, 8, 7), date(2026, 8, 7)]
    assert collect_result["status"] == "OK"
    assert decide_result["status"] == "OK"


def test_falls_back_to_today_when_no_local_history(conn, monkeypatch):
    seen_dates = []
    monkeypatch.setattr(
        update_latest, "run_collect_from_parquet",
        lambda trade_date_, parquet_dir: seen_dates.append(trade_date_) or {"status": "OK"},
    )
    monkeypatch.setattr(
        update_latest, "run_decide",
        lambda trade_date_: seen_dates.append(trade_date_) or {"status": "OK"},
    )

    trade_date_, _, _ = update_latest.run_update_latest()

    assert trade_date_ == date.today()
    assert seen_dates == [date.today(), date.today()]
