"""repositories/decision_repo.py idempotency + STOP 자동처리 테스트."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from swingcycle.domain.enums import Action, CycleState, Gate
from swingcycle.domain.models import Decision
from swingcycle.repositories import decision_repo, trade_plan_repo
from swingcycle.repositories.db import get_connection, run_migrations
from swingcycle.settings import settings
from swingcycle.structure.dow import Pivot


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    run_migrations()
    c = get_connection()
    yield c
    c.close()


def _decision(action=Action.WAIT, trade_date=date(2026, 1, 10)) -> Decision:
    return Decision(
        symbol="005930", name="삼성전자", friend_group="semiconductor", trade_date=trade_date,
        cycle_state=CycleState.REVERSAL, reversal_core_score=72.0, adx_gate=Gate.PASS,
        pullback_score=0.0, late_stage_score=0.0, action=action,
        reasons=["DOW_REVERSAL_CANDIDATE"], stop_price=None,
    )


def _indicators_row() -> pd.Series:
    return pd.Series({
        "sma5": 100.0, "sma20": 98.0, "sma60": 95.0, "sma120": 90.0, "sma240": None,
        "macd": 1.2, "macd_signal": 0.8, "macd_histogram": 0.4, "rsi14": 55.0,
        "plus_di": 25.0, "minus_di": 15.0, "adx": 28.0, "volume_oscillator": 5.0,
        "ma5_distance_pct": 2.0,
    })


def _pivots() -> list[Pivot]:
    return [
        Pivot(confirm_date="2026-01-05", dow_label="LL", price=95.0, pivot_type="LOW", pivot_date="2026-01-03"),
        Pivot(confirm_date="2026-01-07", dow_label="HH", price=105.0, pivot_type="HIGH", pivot_date="2026-01-06"),
    ]


class TestSaveAnalysisIdempotency:
    def test_creates_one_row_per_table(self, conn):
        decision_repo.save_analysis(
            conn, decision=_decision(), indicators_row=_indicators_row(),
            pivots=_pivots(), dow_state="REVERSAL_CANDIDATE",
        )
        assert conn.execute("SELECT COUNT(*) FROM scores_daily").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM indicators_daily").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM cycle_daily").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM pivots").fetchone()[0] == 2

    def test_rerun_same_day_does_not_duplicate(self, conn):
        for _ in range(3):
            decision_repo.save_analysis(
                conn, decision=_decision(), indicators_row=_indicators_row(),
                pivots=_pivots(), dow_state="REVERSAL_CANDIDATE",
            )
        assert conn.execute("SELECT COUNT(*) FROM scores_daily").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM indicators_daily").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM cycle_daily").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM pivots").fetchone()[0] == 2  # 늘지 않음

    def test_rerun_updates_changed_values(self, conn):
        decision_repo.save_analysis(
            conn, decision=_decision(action=Action.WAIT), indicators_row=_indicators_row(),
            pivots=_pivots(), dow_state="REVERSAL_CANDIDATE",
        )
        decision_repo.save_analysis(
            conn, decision=_decision(action=Action.ENTRY), indicators_row=_indicators_row(),
            pivots=_pivots(), dow_state="REVERSAL_CANDIDATE",
        )
        row = conn.execute("SELECT action FROM scores_daily").fetchone()
        assert row["action"] == "ENTRY"

    def test_has_scores_row(self, conn):
        assert not decision_repo.has_scores_row(conn, "005930", date(2026, 1, 10))
        decision_repo.save_analysis(
            conn, decision=_decision(), indicators_row=_indicators_row(),
            pivots=_pivots(), dow_state="REVERSAL_CANDIDATE",
        )
        assert decision_repo.has_scores_row(conn, "005930", date(2026, 1, 10))


class TestGetLatestTradeDate:
    def test_none_when_no_data(self, conn):
        assert decision_repo.get_latest_trade_date(conn) is None

    def test_returns_the_max_date(self, conn):
        decision_repo.save_analysis(
            conn, decision=_decision(trade_date=date(2026, 1, 5)), indicators_row=_indicators_row(),
            pivots=_pivots(), dow_state="REVERSAL_CANDIDATE",
        )
        decision_repo.save_analysis(
            conn, decision=_decision(trade_date=date(2026, 1, 10)), indicators_row=_indicators_row(),
            pivots=_pivots(), dow_state="REVERSAL_CANDIDATE",
        )
        decision_repo.save_analysis(
            conn, decision=_decision(trade_date=date(2026, 1, 3)), indicators_row=_indicators_row(),
            pivots=_pivots(), dow_state="REVERSAL_CANDIDATE",
        )
        assert decision_repo.get_latest_trade_date(conn) == date(2026, 1, 10)


class TestCheckAndApplyStop:
    def test_no_active_plan_returns_false(self, conn):
        bar = pd.Series({"open": 100.0, "low": 90.0})
        assert decision_repo.check_and_apply_stop(conn, symbol="005930", trade_date=date(2026, 1, 10), bar=bar) is False

    def test_stop_triggered_closes_plan_and_emits_events(self, conn):
        plan_id = trade_plan_repo.create_plan(
            conn, symbol="005930", created_date="2026-01-01", entry_type="REVERSAL", stop_price=95.0,
        )
        bar = pd.Series({"open": 100.0, "low": 90.0})  # low(90) <= stop(95) → 체결
        triggered = decision_repo.check_and_apply_stop(conn, symbol="005930", trade_date=date(2026, 1, 10), bar=bar)
        assert triggered is True

        plan = conn.execute("SELECT status FROM trade_plans WHERE plan_id = ?", (plan_id,)).fetchone()
        assert plan["status"] == "STOPPED"
        events = trade_plan_repo.list_events(conn, plan_id)
        assert [e["event_type"] for e in events] == ["STOP", "RESET"]

    def test_not_triggered_when_low_above_stop(self, conn):
        trade_plan_repo.create_plan(
            conn, symbol="005930", created_date="2026-01-01", entry_type="REVERSAL", stop_price=95.0,
        )
        bar = pd.Series({"open": 100.0, "low": 96.0})  # stop 안 건드림
        triggered = decision_repo.check_and_apply_stop(conn, symbol="005930", trade_date=date(2026, 1, 10), bar=bar)
        assert triggered is False

    def test_rerun_after_stop_is_safe_since_no_longer_active(self, conn):
        """RESET 후 plan이 더 이상 ACTIVE가 아니므로, 같은 날 재실행해도 두 번째 STOP 이벤트가 안 생긴다."""
        plan_id = trade_plan_repo.create_plan(
            conn, symbol="005930", created_date="2026-01-01", entry_type="REVERSAL", stop_price=95.0,
        )
        bar = pd.Series({"open": 100.0, "low": 90.0})
        decision_repo.check_and_apply_stop(conn, symbol="005930", trade_date=date(2026, 1, 10), bar=bar)
        triggered_again = decision_repo.check_and_apply_stop(conn, symbol="005930", trade_date=date(2026, 1, 10), bar=bar)
        assert triggered_again is False  # get_active_plan이 이제 None을 반환

        events = trade_plan_repo.list_events(conn, plan_id)
        assert len(events) == 2  # STOP, RESET 한 번씩만
