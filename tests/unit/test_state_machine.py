"""10장/10.1.1 Cycle State Machine 테스트."""
from __future__ import annotations

from dataclasses import replace

from swingcycle.cycle.state_machine import CycleSignals, next_cycle_state
from swingcycle.domain.enums import CycleState, DowState

_NEUTRAL = CycleSignals(
    dow_state=DowState.RANGE,
    adx_falling=False, adx_flattening=False, adx_turn_up=False, mdi_falling=False,
    macd_above_signal=False, macd_above_zero=False,
    rsi_allowed=False, rsi_above_50=False,
    hh_hl_confirmed=False, pullback_in_progress=False, hl_intact=False,
    hl_holding_or_confirmed=False, adx_strong_or_rising=False,
    price_new_hh=False, rsi_lh_accumulating=False, adx_peak_declining=False,
    ma5_distance_extreme=False, lh_candidate=False, major_hl_breached=False,
    new_ll_confirmed=False,
)


def test_stays_put_when_no_condition_met():
    state, reasons = next_cycle_state(CycleState.DOWNTREND, _NEUTRAL)
    assert state == CycleState.DOWNTREND
    assert reasons == []


def test_downtrend_to_bottoming():
    s = replace(_NEUTRAL, adx_falling=True, mdi_falling=True)
    state, reasons = next_cycle_state(CycleState.DOWNTREND, s)
    assert state == CycleState.BOTTOMING
    assert "ADX_FALLING_FROM_HIGH" in reasons


def test_bottoming_to_reversal():
    s = replace(_NEUTRAL, dow_state=DowState.REVERSAL_CANDIDATE, macd_above_signal=True, rsi_allowed=True)
    state, reasons = next_cycle_state(CycleState.BOTTOMING, s)
    assert state == CycleState.REVERSAL
    assert "DOW_REVERSAL_CANDIDATE" in reasons


def test_bottoming_stays_if_rsi_blocked():
    s = replace(_NEUTRAL, dow_state=DowState.REVERSAL_CANDIDATE, macd_above_signal=True, rsi_allowed=False)
    state, _ = next_cycle_state(CycleState.BOTTOMING, s)
    assert state == CycleState.BOTTOMING


def test_reversal_to_uptrend():
    s = replace(_NEUTRAL, hh_hl_confirmed=True, macd_above_signal=True)
    state, reasons = next_cycle_state(CycleState.REVERSAL, s)
    assert state == CycleState.UPTREND
    assert "CYCLE_HH_HL_CONFIRMED" in reasons


def test_uptrend_to_pullback():
    s = replace(_NEUTRAL, pullback_in_progress=True, hl_intact=True)
    state, reasons = next_cycle_state(CycleState.UPTREND, s)
    assert state == CycleState.PULLBACK


def test_uptrend_pullback_without_hl_intact_stays_uptrend():
    s = replace(_NEUTRAL, pullback_in_progress=True, hl_intact=False)
    state, _ = next_cycle_state(CycleState.UPTREND, s)
    assert state == CycleState.UPTREND


def test_uptrend_to_late_stage_takes_priority_over_pullback():
    s = replace(
        _NEUTRAL,
        pullback_in_progress=True, hl_intact=True,
        price_new_hh=True, rsi_lh_accumulating=True, adx_peak_declining=True,
    )
    state, reasons = next_cycle_state(CycleState.UPTREND, s)
    assert state == CycleState.LATE_STAGE
    assert "LATE_BEARISH_DIVERGENCE" in reasons


def test_pullback_to_reacceleration():
    s = replace(
        _NEUTRAL,
        hl_holding_or_confirmed=True, macd_above_zero=True, rsi_above_50=True, adx_strong_or_rising=True,
    )
    state, reasons = next_cycle_state(CycleState.PULLBACK, s)
    assert state == CycleState.REACCELERATION


def test_late_stage_ma5_reason_only_when_extreme():
    s = replace(
        _NEUTRAL,
        price_new_hh=True, rsi_lh_accumulating=True, adx_peak_declining=True, ma5_distance_extreme=False,
    )
    _, reasons = next_cycle_state(CycleState.REACCELERATION, s)
    assert "LATE_MA5_ACCELERATION" not in reasons

    s2 = replace(s, ma5_distance_extreme=True)
    _, reasons2 = next_cycle_state(CycleState.REACCELERATION, s2)
    assert "LATE_MA5_ACCELERATION" in reasons2


def test_late_stage_to_downtrend_transition():
    s = replace(_NEUTRAL, lh_candidate=True, major_hl_breached=True)
    state, reasons = next_cycle_state(CycleState.LATE_STAGE, s)
    assert state == CycleState.DOWNTREND_TRANSITION


def test_downtrend_transition_to_downtrend():
    s = replace(_NEUTRAL, new_ll_confirmed=True)
    state, reasons = next_cycle_state(CycleState.DOWNTREND_TRANSITION, s)
    assert state == CycleState.DOWNTREND
    assert "DOW_DOWNTREND" in reasons


def test_downtrend_transition_stays_without_new_ll():
    state, _ = next_cycle_state(CycleState.DOWNTREND_TRANSITION, _NEUTRAL)
    assert state == CycleState.DOWNTREND_TRANSITION
