"""A/B/C 진입 변형 비교. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 22.3.

목표: ADX를 최종 필터로 쓸 때 초기 진입 손익비와 손절 빈도가 실제 개선되는지 검증한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from .metrics import TradeResult, aggregate_metrics


@dataclass(frozen=True)
class VariantSignals:
    dow_ok: bool             # Dow가 하락추세를 벗어나기 시작(REVERSAL_CANDIDATE 이상)
    macd_above_signal: bool
    rsi_above_25: bool
    adx_gate_pass: bool      # 12.4 Gate == PASS
    adx_turn_up: bool        # ADX 실제 저점 -> 상승전환 확정


def entry_eligible_variant_a(s: VariantSignals) -> bool:
    """A. Dow + MACD>Signal + RSI>25 진입 — ADX 무시."""
    return s.dow_ok and s.macd_above_signal and s.rsi_above_25


def entry_eligible_variant_b(s: VariantSignals) -> bool:
    """B. A + ADX Gate PASS 진입."""
    return entry_eligible_variant_a(s) and s.adx_gate_pass


def entry_eligible_variant_c(s: VariantSignals) -> bool:
    """C. ADX 실제 상승전환까지 기다린 진입(Gate PASS보다 보수적)."""
    return entry_eligible_variant_a(s) and s.adx_turn_up


VARIANT_PREDICATES = {
    "A": entry_eligible_variant_a,
    "B": entry_eligible_variant_b,
    "C": entry_eligible_variant_c,
}


def compare_variants(trades_by_variant: dict[str, list[TradeResult]]) -> dict[str, dict]:
    """각 변형(A/B/C)의 거래 리스트를 받아 나란히 비교 가능한 지표 테이블(회귀 리포트)을 만든다.
    거래 리스트 자체는 이 함수 밖(실제 일별 시뮬레이션 루프)에서 각 변형의 진입 조건으로
    생성해 넘긴다 — 이 함수는 순수 집계/비교만 담당한다."""
    return {variant: aggregate_metrics(trades) for variant, trades in trades_by_variant.items()}
