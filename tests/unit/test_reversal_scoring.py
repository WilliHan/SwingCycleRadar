"""12장 Reversal Entry Score 테스트."""
from __future__ import annotations

from swingcycle.domain.enums import Action, CycleState, Gate
from swingcycle.scoring.reversal import (
    AdxGateSignals,
    ReversalDowSignals,
    ReversalMacdSignals,
    ReversalRsiSignals,
    core_reversal_score,
    evaluate_adx_gate,
    resolve_reversal_action,
    score_dow_reversal,
)

_ALL_TRUE_DOW = ReversalDowSignals(True, True, True, True)
_ALL_FALSE_DOW = ReversalDowSignals(False, False, False, False)
_ALL_TRUE_MACD = ReversalMacdSignals(True, True, True)
_ALL_FALSE_MACD = ReversalMacdSignals(False, False, False)
_ALL_TRUE_RSI = ReversalRsiSignals(True, True, True)
_ALL_FALSE_RSI = ReversalRsiSignals(False, False, False)

_GATE_NEUTRAL = AdxGateSignals(
    mdi_slope_negative=False, adx_slope_negative=False, adx_flattening=False,
    adx_turn_up=False, core_already_bullish=False, mdi_rising=False, adx_rising=False,
    rsi_below_25=False, dow_downtrend_no_lh_break=False,
)


class TestDowScore:
    def test_full_marks_at_default_weight(self):
        part = score_dow_reversal(_ALL_TRUE_DOW)
        assert part.points == 45.0
        assert part.max_points == 45.0

    def test_zero_when_nothing_met(self):
        part = score_dow_reversal(_ALL_FALSE_DOW)
        assert part.points == 0.0

    def test_proportional_scaling_with_custom_category_max(self):
        part = score_dow_reversal(_ALL_TRUE_DOW, category_max=90.0)
        assert part.points == 90.0  # 두 배 총점이면 만점도 두 배


class TestCoreScore:
    def test_full_marks_sum_to_100(self):
        total, _ = core_reversal_score(_ALL_TRUE_DOW, _ALL_TRUE_MACD, _ALL_TRUE_RSI)
        assert total == 100.0

    def test_rsi_below_25_caps_total_at_69(self):
        rsi_blocked = ReversalRsiSignals(above_25=False, turning_up_or_reversing=True, higher_low_structure=True)
        total, reasons = core_reversal_score(_ALL_TRUE_DOW, _ALL_TRUE_MACD, rsi_blocked)
        assert total == 69.0
        assert "RSI_BELOW_25_BLOCK" in reasons

    def test_rsi_cap_does_not_raise_already_low_score(self):
        total, _ = core_reversal_score(_ALL_FALSE_DOW, _ALL_FALSE_MACD, _ALL_FALSE_RSI)
        assert total == 0.0


class TestAdxGate:
    def test_pass_a_mdi_down_adx_down(self):
        s = replace_gate(mdi_slope_negative=True, adx_slope_negative=True)
        gate, reasons = evaluate_adx_gate(s)
        assert gate == Gate.PASS

    def test_pass_b_mdi_down_adx_flattening(self):
        s = replace_gate(mdi_slope_negative=True, adx_flattening=True)
        gate, _ = evaluate_adx_gate(s)
        assert gate == Gate.PASS

    def test_pass_c_requires_core_bullish(self):
        s = replace_gate(mdi_slope_negative=True, adx_turn_up=True, core_already_bullish=False)
        gate, _ = evaluate_adx_gate(s)
        assert gate != Gate.PASS  # core_already_bullish 없으면 C 불성립

        s2 = replace_gate(mdi_slope_negative=True, adx_turn_up=True, core_already_bullish=True)
        gate2, _ = evaluate_adx_gate(s2)
        assert gate2 == Gate.PASS

    def test_block_mdi_up_adx_up(self):
        s = replace_gate(mdi_rising=True, adx_rising=True)
        gate, reasons = evaluate_adx_gate(s)
        assert gate == Gate.BLOCK
        assert "MDI_RISING_BLOCK" in reasons

    def test_block_rsi_below_25(self):
        s = replace_gate(rsi_below_25=True)
        gate, _ = evaluate_adx_gate(s)
        assert gate == Gate.BLOCK

    def test_mdi_rising_adx_falling_is_caution_not_undefined(self):
        """v1.0에서 미정의였던 조합(MDI 상승 + ADX 하락) — v1.1 default로 CAUTION이어야 한다."""
        s = replace_gate(mdi_rising=True, adx_slope_negative=True)
        gate, _ = evaluate_adx_gate(s)
        assert gate == Gate.CAUTION

    def test_fully_neutral_is_caution(self):
        gate, _ = evaluate_adx_gate(_GATE_NEUTRAL)
        assert gate == Gate.CAUTION


def replace_gate(**overrides) -> AdxGateSignals:
    from dataclasses import replace
    return replace(_GATE_NEUTRAL, **overrides)


class TestResolveReversalAction:
    def test_wait_outside_managed_cycle_states(self):
        action = resolve_reversal_action(95.0, Gate.PASS, CycleState.UPTREND)
        assert action == Action.WAIT

    def test_wait_below_ready_threshold(self):
        action = resolve_reversal_action(69.9, Gate.PASS, CycleState.REVERSAL)
        assert action == Action.WAIT

    def test_ready_between_ready_and_entry_when_not_blocked(self):
        action = resolve_reversal_action(75.0, Gate.CAUTION, CycleState.BOTTOMING)
        assert action == Action.READY

    def test_wait_between_ready_and_entry_when_blocked(self):
        action = resolve_reversal_action(75.0, Gate.BLOCK, CycleState.BOTTOMING)
        assert action == Action.WAIT

    def test_entry_at_or_above_entry_threshold_with_pass_gate(self):
        action = resolve_reversal_action(85.0, Gate.PASS, CycleState.REVERSAL)
        assert action == Action.ENTRY

    def test_ready_at_or_above_entry_threshold_with_caution_gate(self):
        action = resolve_reversal_action(85.0, Gate.CAUTION, CycleState.REVERSAL)
        assert action == Action.READY

    def test_wait_at_or_above_entry_threshold_with_block_gate(self):
        action = resolve_reversal_action(85.0, Gate.BLOCK, CycleState.REVERSAL)
        assert action == Action.WAIT
