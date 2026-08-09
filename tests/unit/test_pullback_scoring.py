"""14장 Pullback Entry Score 테스트."""
from __future__ import annotations

from swingcycle.domain.enums import Action, CycleState
from swingcycle.scoring.pullback import (
    PullbackAdxSignals,
    PullbackDowSignals,
    PullbackMacdSignals,
    PullbackQualitySignals,
    PullbackRsiSignals,
    resolve_pullback_action,
    total_pullback_score,
)

_ALL_TRUE = dict(
    dow=PullbackDowSignals(True, True, True),
    macd=PullbackMacdSignals(True, True),
    rsi=PullbackRsiSignals(True, True),
    adx=PullbackAdxSignals(True, True),
    quality=PullbackQualitySignals(True, True),
)
_ALL_FALSE = dict(
    dow=PullbackDowSignals(False, False, False),
    macd=PullbackMacdSignals(False, False),
    rsi=PullbackRsiSignals(False, False),
    adx=PullbackAdxSignals(False, False),
    quality=PullbackQualitySignals(False, False),
)


def test_full_marks_sum_to_100():
    total, _ = total_pullback_score(**_ALL_TRUE)
    assert total == 100.0


def test_zero_when_nothing_met():
    total, _ = total_pullback_score(**_ALL_FALSE)
    assert total == 0.0


def test_reason_codes_present_on_full_marks():
    _, reasons = total_pullback_score(**_ALL_TRUE)
    for code in ["DOW_HH_CONFIRMED", "PULLBACK_HL_HOLD", "MACD_ABOVE_ZERO", "RSI_ABOVE_50", "ADX_ABOVE_30"]:
        assert code in reasons


class TestResolvePullbackAction:
    def test_wait_outside_managed_cycle_states(self):
        assert resolve_pullback_action(95.0, CycleState.REVERSAL) == Action.WAIT
        assert resolve_pullback_action(95.0, CycleState.UPTREND) == Action.WAIT
        assert resolve_pullback_action(95.0, CycleState.LATE_STAGE) == Action.WAIT

    def test_wait_below_ready(self):
        assert resolve_pullback_action(64.9, CycleState.PULLBACK) == Action.WAIT

    def test_ready_between_thresholds(self):
        assert resolve_pullback_action(70.0, CycleState.PULLBACK) == Action.READY

    def test_entry_at_or_above_entry_threshold(self):
        assert resolve_pullback_action(75.0, CycleState.REACCELERATION) == Action.ENTRY

    def test_thresholds_lower_than_reversal_by_default(self):
        # 14.2: ready/entry(65/75)는 Reversal(70/80)보다 낮게 잡힌다
        assert resolve_pullback_action(65.0, CycleState.PULLBACK) == Action.READY
