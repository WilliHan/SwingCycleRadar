"""jobs/daily_decide.py 하루치 end-to-end 통합 테스트.

검증 대상(사용자 권장 순서 4번): 배치가 실제로 DB를 왔다갔다 하며 붙는지,
그리고 idempotency(같은 날 재실행해도 중복 안 생김) + 거래일 컷오프.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from swingcycle.jobs.daily_decide import run_decide
from swingcycle.repositories import daily_bar_repo, trade_plan_repo
from swingcycle.repositories.db import get_connection, run_migrations
from swingcycle.settings import settings


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    run_migrations()
    c = get_connection()
    yield c
    c.close()


def _seed_symbol_and_bars(conn, symbol: str, n_days: int, start_price: float = 100.0, trend: float = 0.3):
    conn.execute(
        "INSERT INTO symbols (symbol, name, market, sector_group, friend_group, enabled, deleted_upstream, note, created_at, updated_at) "
        "VALUES (?, ?, 'KOSPI', NULL, 'semiconductor', 1, 0, NULL, '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
        (symbol, f"테스트종목{symbol}"),
    )
    conn.commit()

    rng = np.random.default_rng(7)
    # 평일만 골라 trade_date 생성(주말 제외) — 실제 daily_bars는 거래일에만 존재해야 한다.
    dates = []
    d = date(2025, 6, 1)
    while len(dates) < n_days:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)

    close = start_price + np.cumsum(rng.normal(trend, 1.0, n_days))
    high = close + rng.uniform(0.5, 1.5, n_days)
    low = close - rng.uniform(0.5, 1.5, n_days)
    open_ = close + rng.uniform(-1.0, 1.0, n_days)

    df = pd.DataFrame({
        "trade_date": [d.isoformat() for d in dates],
        "symbol": [symbol] * n_days,
        "open": open_, "high": high, "low": low, "close": close,
        "volume": rng.uniform(1000, 5000, n_days),
        "trade_value": [None] * n_days, "market_cap": [None] * n_days,
        "source": ["krx_direct"] * n_days, "source_raw_hash": [None] * n_days,
    })
    daily_bar_repo.upsert_daily_bars(conn, df)
    return dates[-1]


class TestEndToEnd:
    def test_full_pipeline_produces_all_expected_rows(self, conn):
        last_date = _seed_symbol_and_bars(conn, "005930", n_days=60)

        result = run_decide(last_date)

        assert result["status"] == "OK"
        assert result["processed"] == 1
        assert result["errors"] == []

        assert conn.execute(
            "SELECT COUNT(*) FROM scores_daily WHERE trade_date = ? AND symbol = '005930'", (last_date.isoformat(),)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM indicators_daily WHERE trade_date = ? AND symbol = '005930'", (last_date.isoformat(),)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM cycle_daily WHERE trade_date = ? AND symbol = '005930'", (last_date.isoformat(),)
        ).fetchone()[0] == 1

    def test_rerun_same_day_is_idempotent(self, conn):
        last_date = _seed_symbol_and_bars(conn, "005930", n_days=60)

        first = run_decide(last_date)
        second = run_decide(last_date)  # force=False 기본값 — 전부 skip돼야 함

        assert first["processed"] == 1
        assert second["processed"] == 0
        assert second["skipped_already_done"] == 1

        assert conn.execute(
            "SELECT COUNT(*) FROM scores_daily WHERE trade_date = ? AND symbol = '005930'", (last_date.isoformat(),)
        ).fetchone()[0] == 1  # 여전히 1행 — 중복 없음

    def test_force_rerun_updates_without_duplicating(self, conn):
        last_date = _seed_symbol_and_bars(conn, "005930", n_days=60)
        run_decide(last_date)
        result = run_decide(last_date, force=True)

        assert result["processed"] == 1  # force라서 다시 처리됨
        assert conn.execute(
            "SELECT COUNT(*) FROM scores_daily WHERE trade_date = ? AND symbol = '005930'", (last_date.isoformat(),)
        ).fetchone()[0] == 1  # 그래도 행은 1개(upsert)

    def test_no_trading_day_short_circuits_without_touching_db(self, conn):
        _seed_symbol_and_bars(conn, "005930", n_days=60)
        saturday = date(2026, 8, 8)  # 실제 토요일
        assert saturday.weekday() == 5

        result = run_decide(saturday)
        assert result["status"] == "NO_TRADING_DAY"
        assert conn.execute("SELECT COUNT(*) FROM scores_daily").fetchone()[0] == 0

    def test_stop_triggered_symbol_still_gets_a_report_row_with_stop_action(self, conn):
        last_date = _seed_symbol_and_bars(conn, "005930", n_days=60, start_price=100.0, trend=-0.5)

        # 활성 플랜을 만들고, 마지막 날 저가보다 훨씬 높은 stop_price를 줘서 반드시 체결되게 한다.
        last_bar = conn.execute(
            "SELECT low FROM daily_bars WHERE symbol='005930' AND trade_date = ?", (last_date.isoformat(),)
        ).fetchone()
        trade_plan_repo.create_plan(
            conn, symbol="005930", created_date="2025-06-01", entry_type="REVERSAL",
            stop_price=last_bar["low"] + 1000.0,  # 무조건 체결되도록 아주 높게
        )

        result = run_decide(last_date)
        assert result["stopped"] == 1
        assert result["processed"] == 0

        row = conn.execute(
            "SELECT action FROM scores_daily WHERE trade_date = ? AND symbol = '005930'", (last_date.isoformat(),)
        ).fetchone()
        assert row["action"] == "STOP"  # 21장 리포트가 STOP 카드를 보여줄 수 있어야 한다

        plan = conn.execute("SELECT status FROM trade_plans WHERE symbol='005930'").fetchone()
        assert plan["status"] == "STOPPED"

    def test_rerun_after_stop_does_not_duplicate_events_or_scores(self, conn):
        last_date = _seed_symbol_and_bars(conn, "005930", n_days=60, trend=-0.5)
        last_bar = conn.execute(
            "SELECT low FROM daily_bars WHERE symbol='005930' AND trade_date = ?", (last_date.isoformat(),)
        ).fetchone()
        plan_id = trade_plan_repo.create_plan(
            conn, symbol="005930", created_date="2025-06-01", entry_type="REVERSAL",
            stop_price=last_bar["low"] + 1000.0,
        )

        run_decide(last_date)
        run_decide(last_date, force=True)  # 재실행해도

        events = trade_plan_repo.list_events(conn, plan_id)
        assert [e["event_type"] for e in events] == ["STOP", "RESET"]  # 한 번씩만
        assert conn.execute(
            "SELECT COUNT(*) FROM scores_daily WHERE symbol='005930' AND trade_date = ?", (last_date.isoformat(),)
        ).fetchone()[0] == 1
