"""Pullback Entry Score. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 14장.

12.4 ADX/MDI Gate는 재사용하지 않는다(14.2 명시) — ADX 강도가 이미 이 스코어 안(15점)에
직접 반영돼 있고, Pullback은 이미 확정된 HH-HL 상승추세 내부 재진입이라 초기 반전용
안전장치를 이중으로 걸 이유가 없기 때문이다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.enums import Action, CycleState
from .models import ScorePart


@dataclass(frozen=True)
class PullbackDowSignals:
    uptrend_hh_hl: bool         # 기존 HH-HL 상승추세 (+20)
    hl_intact: bool             # 눌림 저점이 기존 HL 미훼손 (+10)
    bounced_or_broke_recent_high: bool  # 눌림 이후 양봉/직전 단기고점 돌파 (+5)


@dataclass(frozen=True)
class PullbackMacdSignals:
    above_zero: bool            # +15
    above_signal_or_hist_rising: bool  # +5


@dataclass(frozen=True)
class PullbackRsiSignals:
    above_50: bool               # +15
    support_then_rebound: bool   # 50 부근 지지 후 재상승 +5


@dataclass(frozen=True)
class PullbackAdxSignals:
    strong: bool                 # ADX >= 30, +10
    stopped_falling_or_rising: bool  # ADX 하락 멈춤/재상승, +5


@dataclass(frozen=True)
class PullbackQualitySignals:
    near_support: bool           # 20일선/주요 지지선 부근, +5
    volume_recovered_after_dry_up: bool  # 조정 거래량 감소 후 반등 거래량 회복, +5


def score_dow_pullback(s: PullbackDowSignals, category_max: float = 35.0) -> ScorePart:
    unit = category_max / 35.0
    points, reasons = 0.0, []
    if s.uptrend_hh_hl:
        points += 20 * unit
        reasons.append("DOW_HH_CONFIRMED")
    if s.hl_intact:
        points += 10 * unit
        reasons.append("PULLBACK_HL_HOLD")
    if s.bounced_or_broke_recent_high:
        points += 5 * unit
    return ScorePart(points, category_max, reasons)


def score_macd_pullback(s: PullbackMacdSignals, category_max: float = 20.0) -> ScorePart:
    unit = category_max / 20.0
    points, reasons = 0.0, []
    if s.above_zero:
        points += 15 * unit
        reasons.append("MACD_ABOVE_ZERO")
    if s.above_signal_or_hist_rising:
        points += 5 * unit
        reasons.append("MACD_ABOVE_SIGNAL")
    return ScorePart(points, category_max, reasons)


def score_rsi_pullback(s: PullbackRsiSignals, category_max: float = 20.0) -> ScorePart:
    unit = category_max / 20.0
    points, reasons = 0.0, []
    if s.above_50:
        points += 15 * unit
        reasons.append("RSI_ABOVE_50")
    if s.support_then_rebound:
        points += 5 * unit
    return ScorePart(points, category_max, reasons)


def score_adx_pullback(s: PullbackAdxSignals, category_max: float = 15.0) -> ScorePart:
    unit = category_max / 15.0
    points, reasons = 0.0, []
    if s.strong:
        points += 10 * unit
        reasons.append("ADX_ABOVE_30")
    if s.stopped_falling_or_rising:
        points += 5 * unit
        reasons.append("ADX_TURN_UP")
    return ScorePart(points, category_max, reasons)


def score_pullback_quality(s: PullbackQualitySignals, category_max: float = 10.0) -> ScorePart:
    unit = category_max / 10.0
    points = 0.0
    if s.near_support:
        points += 5 * unit
    if s.volume_recovered_after_dry_up:
        points += 5 * unit
    return ScorePart(points, category_max, [])


def total_pullback_score(
    dow: PullbackDowSignals, macd: PullbackMacdSignals, rsi: PullbackRsiSignals,
    adx: PullbackAdxSignals, quality: PullbackQualitySignals,
    weights: dict[str, float] | None = None,
) -> tuple[float, list[str]]:
    w = weights or {"dow": 35.0, "macd": 20.0, "rsi": 20.0, "adx": 15.0, "quality": 10.0}
    parts = [
        score_dow_pullback(dow, w["dow"]),
        score_macd_pullback(macd, w["macd"]),
        score_rsi_pullback(rsi, w["rsi"]),
        score_adx_pullback(adx, w["adx"]),
        score_pullback_quality(quality, w["quality"]),
    ]
    total = sum(p.points for p in parts)
    reasons: list[str] = []
    for p in parts:
        reasons.extend(p.reasons)
    return total, reasons


def resolve_pullback_action(
    pullback_score: float, cycle_state: CycleState,
    ready_score: float = 65.0, entry_score: float = 75.0,
) -> Action:
    """14.2. cycle_state가 PULLBACK/REACCELERATION일 때만 이 스코어러가 관할한다."""
    if cycle_state not in (CycleState.PULLBACK, CycleState.REACCELERATION):
        return Action.WAIT
    if pullback_score < ready_score:
        return Action.WAIT
    if pullback_score < entry_score:
        return Action.READY
    return Action.ENTRY
