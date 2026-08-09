"""13장 ADD 신호 테스트."""
from __future__ import annotations

from dataclasses import replace

from swingcycle.domain.enums import AddSignal
from swingcycle.scoring.add_signal import AddConfirmationSignals, detect_add_confirmation

_ALL_TRUE = AddConfirmationSignals(
    has_active_plan=True, price_progressing=True, macd_above_signal=True,
    rsi_above_25=True, adx_turn_up=True, mdi_not_rising=True,
)


def test_no_active_plan_is_always_none():
    s = replace(_ALL_TRUE, has_active_plan=False)
    signal, reasons = detect_add_confirmation(s)
    assert signal == AddSignal.NONE
    assert reasons == []


def test_all_conditions_met_confirms_add():
    signal, reasons = detect_add_confirmation(_ALL_TRUE)
    assert signal == AddSignal.ADD_CONFIRM
    assert "ADX_TURN_UP" in reasons


def test_missing_any_single_condition_is_none():
    for field in ["price_progressing", "macd_above_signal", "rsi_above_25", "adx_turn_up", "mdi_not_rising"]:
        s = replace(_ALL_TRUE, **{field: False})
        signal, _ = detect_add_confirmation(s)
        assert signal == AddSignal.NONE, f"{field}=False인데 ADD_CONFIRM이 나오면 안 됨"
