"""Late Stage / 약세 다이버전스 점수. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 15장.

목적은 전량매도 시점 맞히기가 아니라 분할익절 준비/실행이다(15장 명시) — 그래서
결정 결과가 EXIT가 아니라 PREPARE_TAKE_PROFIT/TAKE_PROFIT_PARTIAL이다. 실제 추세
전환(LH->LL)은 이 모듈이 아니라 별도 EXIT 로직(16장, Sprint 5)이 담당한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.enums import LateStageAction
from ..divergence.bearish_divergence import DivergenceResult
from .models import ScorePart


@dataclass(frozen=True)
class LateStageSignals:
    divergence: DivergenceResult
    ma5_distance_extreme: bool     # ma5_distance_z20 >= threshold (15.2)
    near_prior_high_or_box_top: bool  # 전고점/박스상단 근접


def score_late_stage(s: LateStageSignals, category_max: float = 100.0) -> ScorePart:
    unit = category_max / 100.0
    points, reasons = 0.0, []

    if s.divergence.rsi_bearish_divergence:
        points += 35 * unit
        reasons.append("LATE_BEARISH_DIVERGENCE")
    if s.divergence.rsi_lh_streak >= 2:
        points += 20 * unit
        reasons.append("LATE_BEARISH_DIVERGENCE")
    if s.divergence.price_higher_high and s.divergence.adx_peak_declining:
        points += 15 * unit
    if s.ma5_distance_extreme:
        points += 20 * unit
        reasons.append("LATE_MA5_ACCELERATION")
    if s.near_prior_high_or_box_top:
        points += 10 * unit

    return ScorePart(points, category_max, reasons)


def resolve_late_stage_action(
    score: float, prepare_threshold: float = 60.0, partial_threshold: float = 75.0,
) -> LateStageAction:
    if score >= partial_threshold:
        return LateStageAction.TAKE_PROFIT_PARTIAL
    if score >= prepare_threshold:
        return LateStageAction.PREPARE_TAKE_PROFIT
    return LateStageAction.NONE
