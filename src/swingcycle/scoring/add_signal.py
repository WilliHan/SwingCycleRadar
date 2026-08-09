"""ADX 상승전환과 비중확대(ADD). 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 13장.

비중 숫자는 시스템이 주문하지 않는다 — UI는 ADD_CONFIRM 신호만 보여준다(13장 명시).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.enums import AddSignal


@dataclass(frozen=True)
class AddConfirmationSignals:
    has_active_plan: bool
    price_progressing: bool     # 가격 HH/HL 진행 또는 진입 후 새 고점 형성
    macd_above_signal: bool     # MACD > Signal 유지
    rsi_above_25: bool          # RSI > 25 유지
    adx_turn_up: bool           # ADX 저점 -> 상승전환
    mdi_not_rising: bool        # MDI 낮아지거나 최소한 재상승하지 않음


def detect_add_confirmation(s: AddConfirmationSignals) -> tuple[AddSignal, list[str]]:
    if not s.has_active_plan:
        return AddSignal.NONE, []

    if (
        s.price_progressing
        and s.macd_above_signal
        and s.rsi_above_25
        and s.adx_turn_up
        and s.mdi_not_rising
    ):
        return AddSignal.ADD_CONFIRM, ["MACD_ABOVE_SIGNAL", "RSI_ABOVE_25", "ADX_TURN_UP", "MDI_FALLING"]

    return AddSignal.NONE, []
