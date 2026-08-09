"""17장 Decision Engine — 순수 조립 계층. DB I/O 없음(테스트에 DB 픽스처 불필요).

STOP 감지(활성 플랜의 체결 여부)는 여기 포함하지 않는다 — 그건 "오늘 이미 보유한
포지션이 손절됐는가"라는 별개 관심사로, 17.1이 최우선 순위로 두는 이유도 "신규 스코어링과
무관하게 항상 이긴다"는 것이다. orchestrator(jobs/daily_decide.py)가 evaluate() 호출
*전에* stop 체결 여부를 먼저 확인하지만, evaluate() 자체는 그와 무관하게 항상 정상
호출된다 — STOP이 감지된 날도 그날의 indicators/pivots/cycle_daily/scores_daily가
있어야 21장 리포트가 STOP 카드를 보여줄 수 있기 때문이다(스코어링을 생략하면 그
기록 자체가 안 남는 버그가 있었음). 대신 orchestrator가 evaluate()의 반환값을 받은
뒤 stop_triggered면 `action`만 STOP으로 덮어쓴다 — "STOP이 항상 이긴다"는 17.1
원칙은 이 override 한 줄로 보장된다(우선순위 합성 로직에 stop 조건을 추가로
끼워넣을 필요가 없어짐).
"""
from __future__ import annotations

from ..domain.enums import Action, CycleState, EntryType
from ..domain.models import Decision
from ..risk.stop import suggest_stop_price
from .action_resolver import add_signal_to_action, late_stage_action_to_action, resolve_action
from .add_signal import detect_add_confirmation
from .context import DailyContext
from .late_stage import resolve_late_stage_action, score_late_stage
from .pullback import resolve_pullback_action, total_pullback_score
from .reversal import core_reversal_score, evaluate_adx_gate, resolve_reversal_action
from .signal_derivation import (
    DerivationConfig,
    derive_add_signals,
    derive_adx_gate_signals,
    derive_cycle_signals,
    derive_divergence,
    derive_dow_state,
    derive_late_stage_signals,
    derive_pullback_signals,
    derive_reversal_dow_signals,
    derive_reversal_macd_signals,
    derive_reversal_rsi_signals,
)
from ..cycle.state_machine import next_cycle_state


def evaluate(
    ctx: DailyContext,
    *,
    name: str,
    friend_group: str | None,
    prior_cycle_state: CycleState,
    has_active_plan: bool,
    cfg: DerivationConfig = DerivationConfig(),
    stop_buffer_pct: float = 1.0,
) -> Decision:
    dow_state = derive_dow_state(ctx, cfg)
    divergence = derive_divergence(ctx)
    cycle_signals = derive_cycle_signals(ctx, dow_state, divergence, cfg)
    next_state, _cycle_reasons = next_cycle_state(prior_cycle_state, cycle_signals)

    reversal_dow = derive_reversal_dow_signals(ctx, dow_state, cfg)
    reversal_macd = derive_reversal_macd_signals(ctx)
    reversal_rsi = derive_reversal_rsi_signals(ctx)
    core_score, core_reasons = core_reversal_score(reversal_dow, reversal_macd, reversal_rsi)
    gate_signals = derive_adx_gate_signals(ctx, dow_state, reversal_dow, reversal_macd, reversal_rsi)
    gate, gate_reasons = evaluate_adx_gate(gate_signals)
    reversal_action = resolve_reversal_action(core_score, gate, next_state)

    pdow, pmacd, prsi, padx, pquality = derive_pullback_signals(ctx, cycle_signals, cfg)
    pullback_score, pullback_reasons = total_pullback_score(pdow, pmacd, prsi, padx, pquality)
    pullback_action = resolve_pullback_action(pullback_score, next_state)

    add_signals = derive_add_signals(ctx, cycle_signals, has_active_plan)
    add_signal, add_reasons = detect_add_confirmation(add_signals)
    add_action = add_signal_to_action(add_signal)

    late_signals = derive_late_stage_signals(ctx, divergence, cfg)
    late_part = score_late_stage(late_signals)
    late_action = late_stage_action_to_action(resolve_late_stage_action(late_part.points))

    action = resolve_action([reversal_action, pullback_action, add_action, late_action])

    reasons = list(dict.fromkeys(core_reasons + gate_reasons + pullback_reasons + add_reasons + late_part.reasons))

    stop_price = None
    entry_type = None
    if action == Action.ENTRY:
        # cycle_state 게이팅상 reversal_action/pullback_action 중 하나만 ENTRY일 수 있다
        # (12.5는 BOTTOMING/REVERSAL, 14.2는 PULLBACK/REACCELERATION에서만 ENTRY를 낸다).
        entry_type = EntryType.REVERSAL if reversal_action == Action.ENTRY else EntryType.PULLBACK
        # 16.2: 두 경우 모두 "가장 최근 confirmed pivot low"가 stop 기준이다 —
        # REVERSAL은 진입 직전 마지막 pivot low, PULLBACK은 해당 눌림의 confirmed HL이
        # 곧 가장 최근 confirmed low이므로(그렇지 않으면애초에 hl_intact 게이팅을 못 지났다) 동일하다.
        if ctx.confirmed_lows:
            stop_price = suggest_stop_price(ctx.confirmed_lows[-1].price, stop_buffer_pct)

    return Decision(
        symbol=ctx.symbol, name=name, friend_group=friend_group, trade_date=ctx.trade_date,
        cycle_state=next_state, reversal_core_score=core_score, adx_gate=gate,
        pullback_score=pullback_score, late_stage_score=late_part.points,
        action=action, reasons=reasons, stop_price=stop_price, entry_type=entry_type,
    )
