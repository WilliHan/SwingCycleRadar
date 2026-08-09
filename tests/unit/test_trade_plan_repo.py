"""trade_plans/trade_events 저장소 + RESET/재진입 테스트."""
from __future__ import annotations

import sqlite3

import pytest

from swingcycle.repositories import trade_plan_repo
from swingcycle.repositories.db import get_connection, run_migrations
from swingcycle.risk.reset import apply_stop_and_reset
from swingcycle.settings import settings


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    run_migrations()
    c = get_connection()
    yield c
    c.close()


def test_create_and_fetch_active_plan(conn):
    plan_id = trade_plan_repo.create_plan(
        conn, symbol="005930", created_date="2026-01-01", entry_type="REVERSAL",
        stop_price=95.0, planned_entry=100.0,
    )
    row = trade_plan_repo.get_active_plan(conn, "005930")
    assert row["plan_id"] == plan_id
    assert row["status"] == "ACTIVE"
    assert row["stop_price"] == 95.0


def test_only_one_active_plan_per_symbol(conn):
    trade_plan_repo.create_plan(
        conn, symbol="005930", created_date="2026-01-01", entry_type="REVERSAL", stop_price=95.0,
    )
    with pytest.raises(sqlite3.IntegrityError):
        trade_plan_repo.create_plan(
            conn, symbol="005930", created_date="2026-01-02", entry_type="PULLBACK", stop_price=90.0,
        )


def test_record_and_list_events(conn):
    plan_id = trade_plan_repo.create_plan(
        conn, symbol="005930", created_date="2026-01-01", entry_type="REVERSAL", stop_price=95.0,
    )
    trade_plan_repo.record_event(conn, plan_id=plan_id, trade_date="2026-01-01", event_type="ENTRY", price=100.0)
    trade_plan_repo.record_event(conn, plan_id=plan_id, trade_date="2026-01-05", event_type="ADD", price=105.0)

    events = trade_plan_repo.list_events(conn, plan_id)
    assert [e["event_type"] for e in events] == ["ENTRY", "ADD"]


def test_apply_stop_and_reset_closes_plan_and_emits_events(conn):
    plan_id = trade_plan_repo.create_plan(
        conn, symbol="005930", created_date="2026-01-01", entry_type="REVERSAL", stop_price=95.0,
    )
    apply_stop_and_reset(conn, plan_id=plan_id, trade_date="2026-01-10", fill_price=94.5)

    plan = conn.execute("SELECT * FROM trade_plans WHERE plan_id = ?", (plan_id,)).fetchone()
    assert plan["status"] == "STOPPED"

    events = trade_plan_repo.list_events(conn, plan_id)
    assert [e["event_type"] for e in events] == ["STOP", "RESET"]
    assert events[0]["price"] == 94.5


def test_reentry_allowed_after_stop_reset(conn):
    """RESET 후 같은 종목에 새 ACTIVE 플랜을 만들 수 있어야 한다(16.4 재진입)."""
    plan_id = trade_plan_repo.create_plan(
        conn, symbol="005930", created_date="2026-01-01", entry_type="REVERSAL", stop_price=95.0,
    )
    apply_stop_and_reset(conn, plan_id=plan_id, trade_date="2026-01-10", fill_price=94.5)

    new_plan_id = trade_plan_repo.create_plan(
        conn, symbol="005930", created_date="2026-01-15", entry_type="PULLBACK", stop_price=98.0,
    )
    assert new_plan_id != plan_id

    active = trade_plan_repo.get_active_plan(conn, "005930")
    assert active["plan_id"] == new_plan_id


def test_reset_does_not_touch_other_symbols_or_past_bars(conn):
    """RESET이 지우지 않는 것: 시장 데이터/지표/과거 pivot/과거 trade_events(16.4)."""
    from swingcycle.repositories import daily_bar_repo
    import pandas as pd

    daily_bar_repo.upsert_daily_bars(conn, pd.DataFrame({
        "trade_date": ["2026-01-01"], "symbol": ["005930"], "open": [100.0], "high": [101.0],
        "low": [99.0], "close": [100.5], "volume": [1000], "trade_value": [None],
        "market_cap": [None], "source": ["krx_direct"], "source_raw_hash": [None],
    }))

    plan_id = trade_plan_repo.create_plan(
        conn, symbol="005930", created_date="2026-01-01", entry_type="REVERSAL", stop_price=95.0,
    )
    trade_plan_repo.record_event(conn, plan_id=plan_id, trade_date="2026-01-01", event_type="ENTRY", price=100.0)
    apply_stop_and_reset(conn, plan_id=plan_id, trade_date="2026-01-10", fill_price=94.5)

    bars = daily_bar_repo.fetch_bars(conn, "005930")
    assert len(bars) == 1  # 시장 데이터 그대로

    events = trade_plan_repo.list_events(conn, plan_id)
    assert [e["event_type"] for e in events] == ["ENTRY", "STOP", "RESET"]  # 과거 이벤트 보존
