"""21장 일일 리포트(HTML/CSV/JSON) 테스트."""
from __future__ import annotations

from datetime import date

import pytest

from swingcycle.domain.enums import Action, CycleState, Gate
from swingcycle.domain.models import Decision
from swingcycle.reports.daily_report import ReportCard, export_csv, export_json, render_html_report, sort_decisions_for_report


def _decision(symbol: str, action: Action, score: float = 50.0) -> Decision:
    return Decision(
        symbol=symbol, name=f"종목{symbol}", friend_group="semiconductor",
        trade_date=date(2026, 1, 1), cycle_state=CycleState.REVERSAL,
        reversal_core_score=score, adx_gate=Gate.PASS, pullback_score=0.0, late_stage_score=0.0,
        action=action, reasons=["DOW_REVERSAL_CANDIDATE"], stop_price=95.0,
    )


def _card(symbol: str, action: Action, score: float = 50.0) -> ReportCard:
    return ReportCard(
        decision=_decision(symbol, action, score),
        dow_state="REVERSAL_CANDIDATE", macd=1.2, macd_signal=0.8, macd_above_zero=True,
        rsi14=55.0, rsi_above_25=True, rsi_above_50=True, adx=28.0, mdi=15.0,
        last_pivot_labels={"HH": 105.0, "HL": 98.0},
    )


class TestSortOrder:
    def test_stop_first_wait_last(self):
        cards = [_card("A", Action.WAIT), _card("B", Action.STOP), _card("C", Action.READY)]
        sorted_cards = sort_decisions_for_report(cards)
        assert [c.decision.symbol for c in sorted_cards] == ["B", "C", "A"]

    def test_entry_before_add_before_take_profit(self):
        cards = [
            _card("A", Action.TAKE_PROFIT_PARTIAL),
            _card("B", Action.ADD),
            _card("C", Action.ENTRY),
        ]
        sorted_cards = sort_decisions_for_report(cards)
        assert [c.decision.symbol for c in sorted_cards] == ["C", "B", "A"]

    def test_same_action_group_sorted_by_score_desc(self):
        cards = [_card("A", Action.READY, score=60.0), _card("B", Action.READY, score=90.0)]
        sorted_cards = sort_decisions_for_report(cards)
        assert [c.decision.symbol for c in sorted_cards] == ["B", "A"]


class TestExports:
    def test_html_contains_symbol_and_action_badge(self):
        html = render_html_report([_card("005930", Action.ENTRY)], generated_at="2026-01-01")
        assert "005930" in html
        assert "badge-ENTRY" in html
        assert "DOW_REVERSAL_CANDIDATE" in html

    def test_html_sorted_stop_appears_before_wait(self):
        html = render_html_report([_card("W", Action.WAIT), _card("S", Action.STOP)], generated_at="2026-01-01")
        assert html.index("종목S") < html.index("종목W")

    def test_csv_has_header_and_row_per_card(self):
        csv_text = export_csv([_card("005930", Action.ENTRY), _card("000660", Action.WAIT)])
        lines = csv_text.strip().splitlines()
        assert lines[0].startswith("symbol,")
        assert len(lines) == 3  # header + 2 rows

    def test_csv_empty_when_no_cards(self):
        assert export_csv([]) == ""

    def test_json_round_trips_basic_fields(self):
        import json
        json_text = export_json([_card("005930", Action.ENTRY)])
        rows = json.loads(json_text)
        assert rows[0]["symbol"] == "005930"
        assert rows[0]["action"] == "ENTRY"
        assert rows[0]["reasons"] == "DOW_REVERSAL_CANDIDATE"
