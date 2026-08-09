"""22.3 A/B/C 진입 변형 비교 테스트."""
from __future__ import annotations

from dataclasses import replace

from swingcycle.backtest.metrics import TradeResult
from swingcycle.backtest.variants import (
    VariantSignals,
    compare_variants,
    entry_eligible_variant_a,
    entry_eligible_variant_b,
    entry_eligible_variant_c,
)

_BASE = VariantSignals(
    dow_ok=True, macd_above_signal=True, rsi_above_25=True, adx_gate_pass=False, adx_turn_up=False,
)


class TestVariantEligibility:
    def test_variant_a_ignores_adx(self):
        assert entry_eligible_variant_a(_BASE) is True

    def test_variant_b_requires_gate_pass(self):
        assert entry_eligible_variant_b(_BASE) is False
        assert entry_eligible_variant_b(replace(_BASE, adx_gate_pass=True)) is True

    def test_variant_c_requires_actual_turn_up(self):
        assert entry_eligible_variant_c(_BASE) is False
        assert entry_eligible_variant_c(replace(_BASE, adx_turn_up=True)) is True

    def test_all_variants_fail_without_core_conditions(self):
        broken_core = replace(_BASE, dow_ok=False, adx_gate_pass=True, adx_turn_up=True)
        assert entry_eligible_variant_a(broken_core) is False
        assert entry_eligible_variant_b(broken_core) is False
        assert entry_eligible_variant_c(broken_core) is False


def _trade(exit_price: float) -> TradeResult:
    return TradeResult(
        symbol="005930", entry_date="d1", entry_price=100.0, exit_date="d2", exit_price=exit_price,
        holding_days=5, path_high=exit_price, path_low=100.0, stopped=False,
    )


def test_compare_variants_returns_metrics_per_variant():
    trades_by_variant = {
        "A": [_trade(110.0), _trade(90.0)],
        "B": [_trade(115.0)],
        "C": [],
    }
    out = compare_variants(trades_by_variant)
    assert out["A"]["trade_count"] == 2
    assert out["B"]["trade_count"] == 1
    assert out["C"]["trade_count"] == 0
    assert out["C"]["win_rate"] is None
