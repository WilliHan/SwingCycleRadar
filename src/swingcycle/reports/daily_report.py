"""일일 HTML/CSV/JSON 리포트. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 21장.

`Decision`(17장, DecisionEngine의 최소 출력)만으로는 21장 카드가 요구하는 MACD/RSI/ADX
원시값·최근 pivot 라벨을 표시할 수 없어, 이 모듈은 Decision을 감싸는 `ReportCard`를
별도로 정의한다 — DecisionEngine의 계약을 리포트 전용 필드로 오염시키지 않기 위함이다.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field

from jinja2 import Template

from ..domain.enums import Action
from ..domain.models import Decision

# 21장 표시 순서 — 17.1(액션 우선순위 판단용)과는 의도적으로 다르다.
# 17.1은 "충돌하는 신호 중 뭘 최종 행동으로 택할지"이고, 이건 "리포트에서 뭘 먼저 보여줄지"다
# (ENTRY가 TAKE_PROFIT_PARTIAL/ADD보다 먼저 오는 등 순서가 다르므로 반드시 분리 유지한다).
_REPORT_ORDER: dict[Action, int] = {
    Action.STOP: 6,
    Action.EXIT: 6,
    Action.ENTRY: 5,
    Action.ADD: 4,
    Action.TAKE_PROFIT_PARTIAL: 3,
    Action.READY: 2,
    Action.WAIT: 1,
    Action.RESET: 0,  # 순간 이벤트 — 카드로 상시 노출되지 않음(발생 시 맨 뒤)
}


@dataclass(frozen=True)
class ReportCard:
    decision: Decision
    dow_state: str
    macd: float
    macd_signal: float
    macd_above_zero: bool
    rsi14: float
    rsi_above_25: bool
    rsi_above_50: bool
    adx: float
    mdi: float
    last_pivot_labels: dict[str, float] = field(default_factory=dict)  # {"HH":.., "HL":.., ...}
    # 대시보드 상세 패널 표시 전용 보조 필드 — DecisionEngine/스코어링 어디서도 안 쓴다.
    pdi: float | None = None
    rsi_signal: float | None = None
    close_price: float | None = None
    rsi_rising: bool | None = None  # 전일 대비 RSI 상승 여부(None=전일 데이터 없음)
    adx_rising: bool | None = None  # 전일 대비 ADX 상승 여부
    macd_rising: bool | None = None  # 전일 대비 MACD 상승 여부
    mdi_rising: bool | None = None  # 전일 대비 MDI(-DI) 상승 여부
    pdi_rising: bool | None = None  # 전일 대비 PDI(+DI) 상승 여부


def sort_decisions_for_report(cards: list[ReportCard]) -> list[ReportCard]:
    """21장 순서: STOP/EXIT -> ENTRY -> ADD -> TAKE_PROFIT_PARTIAL -> READY -> WAIT.
    동일 그룹 내에서는 reversal_core_score 내림차순 -> symbol 오름차순으로 결정적 정렬."""
    return sorted(
        cards,
        key=lambda c: (
            -_REPORT_ORDER.get(c.decision.action, 0),
            -c.decision.reversal_core_score,
            c.decision.symbol,
        ),
    )


_HTML_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>SwingCycle Radar — {{ generated_at }}</title>
<style>
  body { font-family: -apple-system, sans-serif; background:#f5f6f8; margin:0; padding:24px; }
  h1 { font-size:1.2rem; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(280px,1fr)); gap:12px; }
  .card { background:#fff; border-radius:8px; padding:14px; box-shadow:0 1px 3px rgba(0,0,0,.1); }
  .card h2 { margin:0 0 4px; font-size:1rem; }
  .badge { display:inline-block; padding:2px 8px; border-radius:4px; font-size:.75rem; font-weight:600; color:#fff; }
  .badge-STOP, .badge-EXIT { background:#c0392b; }
  .badge-ENTRY { background:#27ae60; }
  .badge-ADD { background:#2980b9; }
  .badge-TAKE_PROFIT_PARTIAL { background:#8e44ad; }
  .badge-READY { background:#f39c12; }
  .badge-WAIT { background:#95a5a6; }
  .row { font-size:.82rem; color:#333; margin:2px 0; }
  .reasons { margin-top:6px; font-size:.72rem; color:#666; }
  .reasons span { display:inline-block; background:#eee; border-radius:3px; padding:1px 5px; margin:1px; }
</style>
</head>
<body>
<h1>SwingCycle Radar 일일 리포트 — {{ generated_at }}</h1>
<div class="grid">
{% for c in cards %}
  <div class="card">
    <h2>{{ c.decision.name }} ({{ c.decision.symbol }})
      <span class="badge badge-{{ c.decision.action.value }}">{{ c.decision.action.value }}</span>
    </h2>
    <div class="row">그룹: {{ c.decision.friend_group or '-' }}</div>
    <div class="row">Cycle: {{ c.decision.cycle_state.value }} / Dow: {{ c.dow_state }}</div>
    <div class="row">Reversal {{ '%.1f'|format(c.decision.reversal_core_score) }} / Gate {{ c.decision.adx_gate.value }}</div>
    <div class="row">Pullback {{ '%.1f'|format(c.decision.pullback_score) }} / LateStage {{ '%.1f'|format(c.decision.late_stage_score) }}</div>
    <div class="row">MACD {{ '%.2f'|format(c.macd) }} / Signal {{ '%.2f'|format(c.macd_signal) }} ({{ 'above 0' if c.macd_above_zero else 'below 0' }})</div>
    <div class="row">RSI {{ '%.1f'|format(c.rsi14) }} (25:{{ 'Y' if c.rsi_above_25 else 'N' }} / 50:{{ 'Y' if c.rsi_above_50 else 'N' }})</div>
    <div class="row">ADX {{ '%.1f'|format(c.adx) }} / MDI {{ '%.1f'|format(c.mdi) }}</div>
    <div class="row">Pivots: {% for label, price in c.last_pivot_labels.items() %}{{ label }}={{ '%.0f'|format(price) }} {% endfor %}</div>
    <div class="row">제안 Stop: {{ '%.0f'|format(c.decision.stop_price) if c.decision.stop_price else '-' }}</div>
    <div class="reasons">{% for r in c.decision.reasons %}<span>{{ r }}</span>{% endfor %}</div>
  </div>
{% endfor %}
</div>
</body>
</html>
""")


def render_html_report(cards: list[ReportCard], generated_at: str) -> str:
    return _HTML_TEMPLATE.render(cards=sort_decisions_for_report(cards), generated_at=generated_at)


def _decision_to_flat_dict(card: ReportCard) -> dict:
    d = card.decision
    return {
        "symbol": d.symbol, "name": d.name, "friend_group": d.friend_group,
        "trade_date": d.trade_date.isoformat(), "cycle_state": d.cycle_state.value,
        "dow_state": card.dow_state,
        "reversal_core_score": d.reversal_core_score, "adx_gate": d.adx_gate.value,
        "pullback_score": d.pullback_score, "late_stage_score": d.late_stage_score,
        "action": d.action.value, "stop_price": d.stop_price,
        "macd": card.macd, "macd_signal": card.macd_signal, "rsi14": card.rsi14, "adx": card.adx, "mdi": card.mdi,
        "reasons": "|".join(d.reasons),
    }


def export_csv(cards: list[ReportCard]) -> str:
    rows = [_decision_to_flat_dict(c) for c in sort_decisions_for_report(cards)]
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def export_json(cards: list[ReportCard]) -> str:
    rows = [_decision_to_flat_dict(c) for c in sort_decisions_for_report(cards)]
    return json.dumps(rows, ensure_ascii=False, indent=2)
