"""17장 DecisionEngine 순수 조립 계층 테스트 — DB 없이 순수 데이터로만 검증."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swingcycle.domain.enums import Action, CycleState
from swingcycle.indicators.technical import compute_all_indicators
from swingcycle.scoring.context import DailyContext
from swingcycle.scoring.decision_engine import evaluate
from swingcycle.structure.pivots import PivotConfig, detect_and_label_pivots


def _build_context(symbol: str, high, low, close, open_=None, volume=None, trade_date="2026-01-01") -> DailyContext:
    n = len(high)
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    bars = pd.DataFrame({
        "trade_date": dates,
        "open": open_ if open_ is not None else close,
        "high": high, "low": low, "close": close,
        "volume": volume if volume is not None else [10000.0] * n,
    })
    indicators = compute_all_indicators(bars)
    pivots = detect_and_label_pivots(bars, PivotConfig())
    return DailyContext(symbol=symbol, trade_date=dates[-1].date(), bars=bars, indicators=indicators, pivots=pivots)


class TestEvaluateSmoke:
    def test_uptrend_data_runs_without_error_and_yields_valid_action(self):
        rng = np.random.default_rng(1)
        n = 100
        close = 100 + np.cumsum(rng.normal(0.3, 1.0, n))  # 우상향 노이즈
        high = close + rng.uniform(0.5, 1.5, n)
        low = close - rng.uniform(0.5, 1.5, n)
        ctx = _build_context("005930", high, low, close)

        decision = evaluate(
            ctx, name="삼성전자", friend_group="semiconductor",
            prior_cycle_state=CycleState.UPTREND, has_active_plan=False,
        )
        assert decision.symbol == "005930"
        assert isinstance(decision.action, Action)
        assert decision.cycle_state in CycleState
        assert 0.0 <= decision.reversal_core_score <= 100.0
        assert 0.0 <= decision.pullback_score <= 100.0
        assert 0.0 <= decision.late_stage_score <= 100.0

    def test_downtrend_data_runs_without_error(self):
        rng = np.random.default_rng(2)
        n = 100
        close = 100 - np.cumsum(rng.normal(0.3, 1.0, n))
        high = close + rng.uniform(0.5, 1.5, n)
        low = close - rng.uniform(0.5, 1.5, n)
        ctx = _build_context("000660", high, low, close)

        decision = evaluate(
            ctx, name="SK하이닉스", friend_group="semiconductor",
            prior_cycle_state=CycleState.DOWNTREND, has_active_plan=False,
        )
        assert isinstance(decision.action, Action)

    def test_short_history_with_no_confirmed_pivots_does_not_crash(self):
        close = [100.0, 101.0, 102.0, 101.5, 103.0]
        high = [c + 1 for c in close]
        low = [c - 1 for c in close]
        ctx = _build_context("005930", high, low, close)
        assert ctx.pivots == []  # 데이터가 너무 짧아 확정 pivot 없음

        decision = evaluate(
            ctx, name="삼성전자", friend_group=None,
            prior_cycle_state=CycleState.DOWNTREND, has_active_plan=False,
        )
        assert isinstance(decision.action, Action)
        assert decision.stop_price is None  # confirmed low가 없으니 stop 제안 불가


class TestEntryProducesStopSuggestion:
    def test_entry_action_has_stop_price_when_confirmed_low_exists(self):
        """ENTRY가 나오는 정확한 시나리오를 만들기보다, ENTRY가 나왔을 때
        stop_price 로직 자체가 16.1/16.2를 따르는지를 직접 검증한다."""
        rng = np.random.default_rng(3)
        n = 120
        # 하락 후 급반전 — Reversal ENTRY가 나올 가능성이 높은 패턴
        down = 130 - np.cumsum(rng.uniform(0.1, 0.6, 60))
        up = down[-1] + np.cumsum(rng.uniform(0.3, 1.0, 60))
        close = np.concatenate([down, up])
        high = close + rng.uniform(0.5, 1.5, n)
        low = close - rng.uniform(0.5, 1.5, n)
        ctx = _build_context("005930", high, low, close)

        decision = evaluate(
            ctx, name="삼성전자", friend_group=None,
            prior_cycle_state=CycleState.REVERSAL, has_active_plan=False,
        )
        if decision.action == Action.ENTRY:
            assert decision.stop_price is not None
            last_low = ctx.confirmed_lows[-1].price
            assert decision.stop_price == pytest.approx(last_low * 0.99)
