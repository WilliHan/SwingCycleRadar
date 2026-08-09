"""15장 Late Stage 점수/결정 테스트."""
from __future__ import annotations

from swingcycle.divergence.bearish_divergence import DivergenceResult
from swingcycle.domain.enums import LateStageAction
from swingcycle.scoring.late_stage import LateStageSignals, resolve_late_stage_action, score_late_stage

_FULL_DIVERGENCE = DivergenceResult(
    price_higher_high=True, rsi_lower_high=True, rsi_bearish_divergence=True,
    rsi_lh_streak=2, adx_peak_declining=True,
)
_NO_DIVERGENCE = DivergenceResult(
    price_higher_high=False, rsi_lower_high=False, rsi_bearish_divergence=False,
    rsi_lh_streak=0, adx_peak_declining=False,
)


def test_full_marks_sum_to_100():
    s = LateStageSignals(_FULL_DIVERGENCE, ma5_distance_extreme=True, near_prior_high_or_box_top=True)
    part = score_late_stage(s)
    assert part.points == 100.0


def test_zero_when_nothing_met():
    s = LateStageSignals(_NO_DIVERGENCE, ma5_distance_extreme=False, near_prior_high_or_box_top=False)
    part = score_late_stage(s)
    assert part.points == 0.0


def test_streak_below_2_does_not_award_accumulation_bonus():
    single = DivergenceResult(True, True, True, rsi_lh_streak=1, adx_peak_declining=False)
    s = LateStageSignals(single, ma5_distance_extreme=False, near_prior_high_or_box_top=False)
    part = score_late_stage(s)
    # 35(divergence) 만 받고 20(누적) 은 못 받음
    assert part.points == 35.0


class TestResolveAction:
    def test_none_below_prepare_threshold(self):
        assert resolve_late_stage_action(59.9) == LateStageAction.NONE

    def test_prepare_between_thresholds(self):
        assert resolve_late_stage_action(65.0) == LateStageAction.PREPARE_TAKE_PROFIT

    def test_partial_at_or_above_partial_threshold(self):
        assert resolve_late_stage_action(80.0) == LateStageAction.TAKE_PROFIT_PARTIAL
