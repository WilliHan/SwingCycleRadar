"""17.1 Action 우선순위 합성. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 17.1.

각 스코어러(12.5/14.2/13장/15장)가 이미 자기 관할이 아니면 WAIT를 반환하도록
설계돼 있으므로(cycle_state 게이팅), 여기서는 단순히 "가장 급한 후보 하나 선택"만 한다
— "STOP과 ENTRY가 같은 날 동시에 계산돼도 STOP이 이긴다"는 원칙을 한 함수로 닫는다.
"""
from __future__ import annotations

from ..domain.enums import Action, AddSignal, LateStageAction

_ACTION_PRIORITY: dict[Action, int] = {
    Action.STOP: 7,
    Action.EXIT: 7,
    Action.RESET: 6,
    Action.TAKE_PROFIT_PARTIAL: 5,
    Action.ADD: 4,
    Action.ENTRY: 3,
    Action.READY: 2,
    Action.WAIT: 1,
}


def late_stage_action_to_action(signal: LateStageAction) -> Action:
    """PREPARE_TAKE_PROFIT는 준비 신호일 뿐 즉각 행동 우선순위에 넣지 않는다(21장 카드에는
    late_stage_score로 계속 노출됨) — TAKE_PROFIT_PARTIAL만 실제 후보가 된다."""
    if signal == LateStageAction.TAKE_PROFIT_PARTIAL:
        return Action.TAKE_PROFIT_PARTIAL
    return Action.WAIT


def add_signal_to_action(signal: AddSignal) -> Action:
    return Action.ADD if signal == AddSignal.ADD_CONFIRM else Action.WAIT


def resolve_action(candidates: list[Action]) -> Action:
    """candidates가 비어있으면 WAIT. 우선순위 동점(STOP/EXIT)은 먼저 나온 쪽이 유지된다
    (max()는 첫 번째 최댓값을 반환 — 결과적으로 어느 쪽이 나와도 등급은 동일해 무해함)."""
    if not candidates:
        return Action.WAIT
    return max(candidates, key=lambda a: _ACTION_PRIORITY[a])
