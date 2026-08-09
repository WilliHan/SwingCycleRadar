"""Cycle State Machine. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 10장/10.1.1.

10.1.1이 규정하지 못한 세부 하나: transition에 쓰이는 reason code는 29장 카탈로그를
최대한 재사용하되, 카탈로그에 없는 cycle 고유 전이(예: HH+HL 확정, HL 훼손)는
`CYCLE_` 접두사를 붙인 신규 코드로 명시적으로 구분한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.enums import CycleState, DowState


@dataclass(frozen=True)
class CycleSignals:
    """상태 전이 판단에 필요한 입력. 계산 자체는 indicators/structure 모듈이 담당하고
    (선행 참조 없이) 이 dataclass는 그 결과만 담는 순수 입력이다."""

    dow_state: DowState
    adx_falling: bool
    adx_flattening: bool
    adx_turn_up: bool
    mdi_falling: bool
    macd_above_signal: bool
    macd_above_zero: bool
    rsi_allowed: bool          # rsi14 > threshold(기본 25)
    rsi_above_50: bool
    hh_hl_confirmed: bool      # "HH + HL 확정" (REVERSAL -> UPTREND)
    pullback_in_progress: bool  # "HH 이후 조정" 관찰 상태 (UPTREND -> PULLBACK)
    hl_intact: bool            # "구조상 기존 HL 미훼손"
    hl_holding_or_confirmed: bool  # "HL 확정/유지" (PULLBACK -> REACCELERATION)
    adx_strong_or_rising: bool  # "ADX >= 30 또는 강한 영역 재상승"
    price_new_hh: bool         # "가격 HH"
    rsi_lh_accumulating: bool  # "RSI LH 누적" (late-stage 다이버전스 재사용)
    adx_peak_declining: bool   # "ADX peak가 이전보다 낮음" (10.1.1/15장 공통 정의)
    ma5_distance_extreme: bool  # "고점권 MA5 이격 급팽창" (15.2 threshold 재사용)
    lh_candidate: bool         # "LH 후보"
    major_hl_breached: bool    # "주요 HL 훼손"
    new_ll_confirmed: bool     # "LL 확정"


def _downtrend_to_bottoming(s: CycleSignals) -> list[str] | None:
    if s.adx_falling and s.mdi_falling:
        return ["ADX_FALLING_FROM_HIGH", "MDI_FALLING"]
    return None


def _bottoming_to_reversal(s: CycleSignals) -> list[str] | None:
    if (
        s.dow_state in (DowState.REVERSAL_CANDIDATE, DowState.UPTREND)
        and s.macd_above_signal
        and s.rsi_allowed
    ):
        return ["DOW_REVERSAL_CANDIDATE", "MACD_ABOVE_SIGNAL", "RSI_ABOVE_25"]
    return None


def _reversal_to_uptrend(s: CycleSignals) -> list[str] | None:
    if s.hh_hl_confirmed and s.macd_above_signal:
        return ["CYCLE_HH_HL_CONFIRMED", "MACD_ABOVE_SIGNAL"]
    return None


def _uptrend_to_pullback(s: CycleSignals) -> list[str] | None:
    if s.pullback_in_progress and s.hl_intact:
        return ["CYCLE_PULLBACK_STARTED", "PULLBACK_HL_HOLD"]
    return None


def _pullback_to_reacceleration(s: CycleSignals) -> list[str] | None:
    if (
        s.hl_holding_or_confirmed
        and s.macd_above_zero
        and s.rsi_above_50
        and s.adx_strong_or_rising
    ):
        return ["PULLBACK_HL_HOLD", "MACD_ABOVE_ZERO", "RSI_ABOVE_50", "ADX_ABOVE_30"]
    return None


def _to_late_stage(s: CycleSignals) -> list[str] | None:
    """UPTREND/REACCELERATION -> LATE_STAGE. 가격 HH인데 RSI LH 누적 + ADX peak 하락,
    MA5 급이격은 가중(단독 트리거 아님, 명시적 default에 준해 필수 조건 2개만 게이트)."""
    if s.price_new_hh and s.rsi_lh_accumulating and s.adx_peak_declining:
        reasons = ["LATE_BEARISH_DIVERGENCE"]
        if s.ma5_distance_extreme:
            reasons.append("LATE_MA5_ACCELERATION")
        return reasons
    return None


def _late_stage_to_downtrend_transition(s: CycleSignals) -> list[str] | None:
    if s.lh_candidate and s.major_hl_breached:
        return ["CYCLE_LH_CANDIDATE", "CYCLE_HL_BREACHED"]
    return None


def next_cycle_state(current: CycleState, s: CycleSignals) -> tuple[CycleState, list[str]]:
    """현재 상태 + 신호를 받아 다음 상태와 그 근거(reason code)를 반환한다.
    조건을 만족하지 못하면 (현재 상태 그대로, 빈 reasons)를 반환한다 — 미정의 전이 없음."""
    if current == CycleState.DOWNTREND:
        reasons = _downtrend_to_bottoming(s)
        return (CycleState.BOTTOMING, reasons) if reasons else (current, [])

    if current == CycleState.BOTTOMING:
        reasons = _bottoming_to_reversal(s)
        return (CycleState.REVERSAL, reasons) if reasons else (current, [])

    if current == CycleState.REVERSAL:
        reasons = _reversal_to_uptrend(s)
        return (CycleState.UPTREND, reasons) if reasons else (current, [])

    if current == CycleState.UPTREND:
        late = _to_late_stage(s)
        if late:
            return CycleState.LATE_STAGE, late
        pullback = _uptrend_to_pullback(s)
        return (CycleState.PULLBACK, pullback) if pullback else (current, [])

    if current == CycleState.PULLBACK:
        late = _to_late_stage(s)
        if late:
            return CycleState.LATE_STAGE, late
        reaccel = _pullback_to_reacceleration(s)
        return (CycleState.REACCELERATION, reaccel) if reaccel else (current, [])

    if current == CycleState.REACCELERATION:
        late = _to_late_stage(s)
        return (CycleState.LATE_STAGE, late) if late else (current, [])

    if current == CycleState.LATE_STAGE:
        reasons = _late_stage_to_downtrend_transition(s)
        return (CycleState.DOWNTREND_TRANSITION, reasons) if reasons else (current, [])

    if current == CycleState.DOWNTREND_TRANSITION:
        if s.new_ll_confirmed:
            return CycleState.DOWNTREND, ["DOW_DOWNTREND"]
        return current, []

    return current, []  # 명시적 default — 위 어느 상태도 아니면 그대로 유지
