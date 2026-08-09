"""17.1 액션 우선순위 합성 테스트."""
from __future__ import annotations

from swingcycle.domain.enums import Action, AddSignal, LateStageAction
from swingcycle.scoring.action_resolver import (
    add_signal_to_action,
    late_stage_action_to_action,
    resolve_action,
)


def test_stop_beats_entry_when_both_present():
    action = resolve_action([Action.ENTRY, Action.STOP, Action.READY])
    assert action == Action.STOP


def test_reset_beats_take_profit():
    action = resolve_action([Action.TAKE_PROFIT_PARTIAL, Action.RESET])
    assert action == Action.RESET


def test_take_profit_beats_add():
    action = resolve_action([Action.ADD, Action.TAKE_PROFIT_PARTIAL])
    assert action == Action.TAKE_PROFIT_PARTIAL


def test_add_beats_entry():
    action = resolve_action([Action.ENTRY, Action.ADD])
    assert action == Action.ADD


def test_entry_beats_ready():
    action = resolve_action([Action.READY, Action.ENTRY])
    assert action == Action.ENTRY


def test_ready_beats_wait():
    action = resolve_action([Action.WAIT, Action.READY])
    assert action == Action.READY


def test_empty_candidates_is_wait():
    assert resolve_action([]) == Action.WAIT


def test_all_wait_is_wait():
    assert resolve_action([Action.WAIT, Action.WAIT]) == Action.WAIT


def test_late_stage_prepare_does_not_become_actionable():
    assert late_stage_action_to_action(LateStageAction.PREPARE_TAKE_PROFIT) == Action.WAIT


def test_late_stage_partial_becomes_take_profit_partial():
    assert late_stage_action_to_action(LateStageAction.TAKE_PROFIT_PARTIAL) == Action.TAKE_PROFIT_PARTIAL


def test_add_signal_none_is_wait():
    assert add_signal_to_action(AddSignal.NONE) == Action.WAIT


def test_add_signal_confirm_is_add():
    assert add_signal_to_action(AddSignal.ADD_CONFIRM) == Action.ADD
