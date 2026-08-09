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

    def test_stop_triggered_with_insufficient_bars_still_gets_a_report_row(self, conn):
        """리뷰 지적 재현: 신규상장 등으로 bar 수가 _MIN_BARS_FOR_ANALYSIS(30) 미만이어도
        STOP이 감지되면 scores_daily에 반드시 행이 남아야 한다(21장 리포트가 STOP 카드를
        보여줘야 하므로) — 예전엔 이 gate가 STOP까지 걸러서 플랜만 닫히고 리포트 행이
        안 남는 버그가 있었다."""
        last_date = _seed_symbol_and_bars(conn, "005930", n_days=10, start_price=100.0, trend=-0.5)
        assert conn.execute(
            "SELECT COUNT(*) FROM daily_bars WHERE symbol='005930'"
        ).fetchone()[0] < 30  # 워밍업 기준 미만임을 전제로 확인

        last_bar = conn.execute(
            "SELECT low FROM daily_bars WHERE symbol='005930' AND trade_date = ?", (last_date.isoformat(),)
        ).fetchone()
        trade_plan_repo.create_plan(
            conn, symbol="005930", created_date="2025-06-01", entry_type="REVERSAL",
            stop_price=last_bar["low"] + 1000.0,
        )
        conn.commit()

        result = run_decide(last_date)
        assert result["stopped"] == 1
        assert result["skipped_no_data"] == 0

        row = conn.execute(
            "SELECT action FROM scores_daily WHERE trade_date = ? AND symbol = '005930'", (last_date.isoformat(),)
        ).fetchone()
        assert row is not None, "STOP이 감지됐는데도 scores_daily 행이 없음 — 리포트에서 STOP 카드가 사라짐"
        assert row["action"] == "STOP"

        plan = conn.execute("SELECT status FROM trade_plans WHERE symbol='005930'").fetchone()
        assert plan["status"] == "STOPPED"

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
        conn.commit()  # run_decide()는 별도 커넥션을 여니, create_plan(더 이상 자체 commit 안 함)을 여기서 커밋해야 보인다

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
        conn.commit()  # create_plan은 더 이상 자체 commit하지 않으므로(리뷰 수정) 테스트가 직접 커밋

        run_decide(last_date)
        run_decide(last_date, force=True)  # 재실행해도

        events = trade_plan_repo.list_events(conn, plan_id)
        assert [e["event_type"] for e in events] == ["STOP", "RESET"]  # 한 번씩만
        assert conn.execute(
            "SELECT COUNT(*) FROM scores_daily WHERE symbol='005930' AND trade_date = ?", (last_date.isoformat(),)
        ).fetchone()[0] == 1

    def test_failure_between_stop_and_save_rolls_back_atomically(self, conn, monkeypatch):
        """리뷰 지적 사항의 실패 주입 재현: check_and_apply_stop() 이후, save_analysis()
        전에 예외가 나면 플랜 종료/STOP·RESET 이벤트까지 전부 롤백돼야 한다 — 그래야
        재실행 시 플랜이 여전히 ACTIVE라 STOP이 다시 정상 감지된다."""
        last_date = _seed_symbol_and_bars(conn, "005930", n_days=60, trend=-0.5)
        last_bar = conn.execute(
            "SELECT low FROM daily_bars WHERE symbol='005930' AND trade_date = ?", (last_date.isoformat(),)
        ).fetchone()
        plan_id = trade_plan_repo.create_plan(
            conn, symbol="005930", created_date="2025-06-01", entry_type="REVERSAL",
            stop_price=last_bar["low"] + 1000.0,  # 반드시 체결되도록
        )
        conn.commit()

        import swingcycle.jobs.daily_decide as daily_decide_module

        def _boom(*args, **kwargs):
            raise RuntimeError("주입된 실패 — 지표 계산 단계")

        # monkeypatch.context()로 범위를 좁힌다 — 이 fixture는 conn 픽스처와 같은
        # monkeypatch 인스턴스를 공유하므로, 최상위 monkeypatch.setattr()을 쓰고 나중에
        # monkeypatch.undo()를 부르면 conn 픽스처가 설정한 settings.db_path 패치까지
        # 같이 풀려서 이후 run_decide()가 전혀 다른(진짜) DB 파일을 보게 된다(실제로 겪은
        # 테스트 버그 — EMPTY_UNIVERSE로 나타남). with 블록으로 이 패치만 격리해 되돌린다.
        with monkeypatch.context() as m:
            m.setattr(daily_decide_module, "compute_all_indicators", _boom)
            result = run_decide(last_date)
            assert result["errors"], "실패가 daily_decide 레벨에서 잡혀 errors에 기록돼야 한다"

        # 롤백 확인: 플랜은 여전히 ACTIVE, STOP/RESET 이벤트도 없음, scores_daily도 없음.
        plan = conn.execute("SELECT status FROM trade_plans WHERE plan_id = ?", (plan_id,)).fetchone()
        assert plan["status"] == "ACTIVE"
        assert trade_plan_repo.list_events(conn, plan_id) == []
        assert conn.execute(
            "SELECT COUNT(*) FROM scores_daily WHERE symbol='005930' AND trade_date = ?", (last_date.isoformat(),)
        ).fetchone()[0] == 0

        # with 블록을 벗어나 compute_all_indicators는 이미 원상복구된 상태 — 재실행하면
        # STOP이 이번엔 정상적으로 끝까지 처리돼야 한다.
        result2 = run_decide(last_date, force=True)
        assert result2["stopped"] == 1
        assert result2["errors"] == []

        plan_after = conn.execute("SELECT status FROM trade_plans WHERE plan_id = ?", (plan_id,)).fetchone()
        assert plan_after["status"] == "STOPPED"
        assert [e["event_type"] for e in trade_plan_repo.list_events(conn, plan_id)] == ["STOP", "RESET"]
        row = conn.execute(
            "SELECT action FROM scores_daily WHERE symbol='005930' AND trade_date = ?", (last_date.isoformat(),)
        ).fetchone()
        assert row["action"] == "STOP"
