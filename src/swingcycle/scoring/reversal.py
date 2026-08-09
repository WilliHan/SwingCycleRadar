"""Reversal Entry Score. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 12장.

세부 배점(예: Dow 45점 중 15/15/10/5 분해)은 설계서 문구를 그대로 비율로 옮기고,
config의 카테고리 총점(scoring.yml `reversal.weights.*`)에 맞춰 비례 배분한다 —
총점만 config로 조정 가능하고 내부 비율은 설계서 의도를 그대로 보존한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.enums import Action, CycleState, Gate
from .models import ScorePart


@dataclass(frozen=True)
class ReversalDowSignals:
    breaking_downtrend: bool          # 하락추세(LL/LH)에서 벗어나기 시작
    last_lh_broken: bool              # 마지막 확정 LH 고점 종가/고가 돌파
    hl_forming: bool                  # 최근 저점 > 이전 LL → HL 구조 형성/확정
    no_new_low_and_recovering: bool   # 최근 3~5일 저점 갱신 없음 + 종가 회복


@dataclass(frozen=True)
class ReversalMacdSignals:
    above_signal: bool
    slope_3_positive: bool
    cross_up_recent: bool  # 최근 5영업일 이내 상향 cross 또는 histogram 증가


@dataclass(frozen=True)
class ReversalRsiSignals:
    above_25: bool
    turning_up_or_reversing: bool
    higher_low_structure: bool


@dataclass(frozen=True)
class AdxGateSignals:
    mdi_slope_negative: bool
    adx_slope_negative: bool
    adx_flattening: bool
    adx_turn_up: bool
    core_already_bullish: bool  # PASS-C 조건: Dow/MACD/RSI가 이미 강세
    mdi_rising: bool
    adx_rising: bool
    rsi_below_25: bool
    dow_downtrend_no_lh_break: bool


def score_dow_reversal(s: ReversalDowSignals, category_max: float = 45.0) -> ScorePart:
    unit = category_max / 45.0
    points, reasons = 0.0, []
    if s.breaking_downtrend:
        points += 15 * unit
        reasons.append("DOW_REVERSAL_CANDIDATE")
    if s.last_lh_broken:
        points += 15 * unit
        reasons.append("DOW_LAST_LH_BROKEN")
    if s.hl_forming:
        points += 10 * unit
        reasons.append("DOW_HL_CONFIRMED")
    if s.no_new_low_and_recovering:
        points += 5 * unit
        reasons.append("DOW_HL_CONFIRMED")
    return ScorePart(points, category_max, reasons)


def score_macd_reversal(s: ReversalMacdSignals, category_max: float = 30.0) -> ScorePart:
    unit = category_max / 30.0
    points, reasons = 0.0, []
    if s.above_signal:
        points += 20 * unit
        reasons.append("MACD_ABOVE_SIGNAL")
    if s.slope_3_positive:
        points += 5 * unit
    if s.cross_up_recent:
        points += 5 * unit
        reasons.append("MACD_CROSS_UP_RECENT")
    return ScorePart(points, category_max, reasons)


def score_rsi_reversal(s: ReversalRsiSignals, category_max: float = 25.0) -> ScorePart:
    unit = category_max / 25.0
    points, reasons = 0.0, []
    if s.above_25:
        points += 10 * unit
        reasons.append("RSI_ABOVE_25")
    if s.turning_up_or_reversing:
        points += 10 * unit
        reasons.append("RSI_TURN_UP")
    if s.higher_low_structure:
        points += 5 * unit
    return ScorePart(points, category_max, reasons)


def core_reversal_score(
    dow: ReversalDowSignals, macd: ReversalMacdSignals, rsi: ReversalRsiSignals,
    weights: dict[str, float] | None = None,
) -> tuple[float, list[str]]:
    """12.1-12.3 합산. RSI<25면 상한 69로 제한(12.3) — ENTRY(80+) 원천 차단."""
    w = weights or {"dow": 45.0, "macd": 30.0, "rsi": 25.0}
    dow_part = score_dow_reversal(dow, w["dow"])
    macd_part = score_macd_reversal(macd, w["macd"])
    rsi_part = score_rsi_reversal(rsi, w["rsi"])

    total = dow_part.points + macd_part.points + rsi_part.points
    reasons = dow_part.reasons + macd_part.reasons + rsi_part.reasons

    if not rsi.above_25:
        total = min(total, 69.0)
        reasons.append("RSI_BELOW_25_BLOCK")

    return total, reasons


def evaluate_adx_gate(s: AdxGateSignals) -> tuple[Gate, list[str]]:
    """12.4. PASS/BLOCK을 먼저 판정하고, 나머지 전부(미정의 조합 포함)는 CAUTION으로
    귀결시킨다 — v1.1이 명시한 "MDI 상승+ADX 하락" 미정의 케이스도 이 default로 흡수된다."""
    # PASS: A) MDI<0 & ADX<0  B) MDI<0 & ADX flattening  C) MDI<0 & ADX turn_up & core bullish
    if s.mdi_slope_negative and s.adx_slope_negative:
        return Gate.PASS, ["MDI_FALLING", "ADX_FALLING_FROM_HIGH"]
    if s.mdi_slope_negative and s.adx_flattening:
        return Gate.PASS, ["MDI_FALLING", "ADX_FLATTENING"]
    if s.mdi_slope_negative and s.adx_turn_up and s.core_already_bullish:
        return Gate.PASS, ["MDI_FALLING", "ADX_TURN_UP"]

    # BLOCK: MDI 상승+ADX 상승 (하락 방향성 강화) OR RSI<25 OR DOWNTREND 미돌파
    if s.mdi_rising and s.adx_rising:
        return Gate.BLOCK, ["MDI_RISING_BLOCK"]
    if s.rsi_below_25:
        return Gate.BLOCK, ["RSI_BELOW_25_BLOCK"]
    if s.dow_downtrend_no_lh_break:
        return Gate.BLOCK, ["DOW_DOWNTREND"]

    return Gate.CAUTION, []


def resolve_reversal_action(
    core: float, gate: Gate, cycle_state: CycleState,
    ready_score: float = 70.0, entry_score: float = 80.0,
) -> Action:
    """12.5. Reversal 스코어러는 cycle_state가 BOTTOMING/REVERSAL일 때만 관할한다
    (v1.1 신설 게이팅) — 그 외 구간에서는 Pullback 쪽 결과를 따르라는 뜻으로 WAIT."""
    if cycle_state not in (CycleState.BOTTOMING, CycleState.REVERSAL):
        return Action.WAIT
    if core < ready_score:
        return Action.WAIT
    if core < entry_score:
        return Action.WAIT if gate == Gate.BLOCK else Action.READY
    if gate == Gate.PASS:
        return Action.ENTRY
    if gate == Gate.CAUTION:
        return Action.READY
    return Action.WAIT
