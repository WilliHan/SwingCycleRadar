"""SwingCycle Radar Streamlit 앱 골격.

설계: docs/SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md 3장(런타임 결정), 8장(종목 관리), 9장(UI)

Hub 게이트만으로 인증(MFTS 패턴, 4.3) — 앱 내부 로그인 폼 없음.
단, 종목 CRUD의 updated_by 기록을 위해 신원 확인 브리지(4.4)만 별도로 둔다.
"""
from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.hub_bridge import resolve_hub_identity  # noqa: E402
from swingcycle.data.supabase_client import get_supabase_client  # noqa: E402
from swingcycle.data.supabase_daily_sync import reconcile_recent_history  # noqa: E402
from swingcycle.jobs.daily_report_job import get_report_cards  # noqa: E402
from swingcycle.jobs.update_latest import run_update_latest  # noqa: E402
from swingcycle.reports.daily_report import ReportCard, sort_decisions_for_report  # noqa: E402
from swingcycle.repositories import decision_repo  # noqa: E402
from swingcycle.repositories.db import get_connection, run_migrations  # noqa: E402
from swingcycle.repositories.symbol_repo import has_active_trade_plan  # noqa: E402
from swingcycle.settings import settings  # noqa: E402

st.set_page_config(page_title="SwingCycle Radar", page_icon="🧭", layout="wide")

# cli.py(배치 진입점)와 달리 `streamlit run`은 별도 프로세스라 그쪽 basicConfig를
# 안 탄다 — logging.info가 로그 파일에 안 찍히는 동일 부류 문제(세션 초반 cli.py에서도
# 겪음)를 여기서도 막기 위해 직접 설정한다.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("webapp")

_ACTION_COLOR = {
    # 한국 증시 관례(빨강=상승/매수, 파랑=하락/매도)를 그대로 따른다 — 매수쪽 행동
    # 제안(ENTRY/ADD/TAKE_PROFIT_PARTIAL)은 빨강, 매도/위험관리쪽(STOP/EXIT)은 파랑.
    "STOP": "blue", "EXIT": "blue",
    "ENTRY": "red",
    "ADD": "red",
    "TAKE_PROFIT_PARTIAL": "red",
    "READY": "orange",
    "WAIT": "gray",
    "RESET": "gray",
}
_ACTION_EMOJI = {"red": "🔴", "blue": "🔵", "orange": "🟠", "gray": "⚪"}
# 표 셀 색상은 pandas Styler로 시도했다가 되돌렸다 — Styler를 st.dataframe(on_select="rerun")에
# 넘기면 리런마다 위젯이 다른 데이터로 인식돼 행 선택 상태가 깨지는 문제가 실사용에서
# 확인됐다(사용자 캡처: 체크박스는 선택됐는데 상세 패널이 안 뜸). 그래서 색상 대신
# 이모지 원(_ACTION_EMOJI)을 텍스트에 붙이는 방식으로 바꿨다 — TextColumn/선택 기능과
# 충돌 없이 동일한 시각적 구분을 준다.

_ACTION_HELP = {
    "STOP": "손절 체결됨 — 16.4에 따라 플랜 자동 종료",
    "EXIT": "청산",
    "ENTRY": "신규 진입 제안",
    "ADD": "비중 확대 제안 (13장 — 시스템이 자동 주문하지 않음, 제안만)",
    "TAKE_PROFIT_PARTIAL": "분할 익절 제안",
    "READY": "관찰 — 조건 근접, 아직 진입 기준 미달",
    "WAIT": "대기 — 뚜렷한 신호 없음",
    "RESET": "손절 후 플랜 초기화(재진입 가능 상태)",
}

_CYCLE_STATE_HELP = {
    "DOWNTREND": "하락추세", "BOTTOMING": "바닥 형성 중", "REVERSAL": "반전 국면",
    "UPTREND": "상승추세", "PULLBACK": "상승 중 조정", "REACCELERATION": "조정 후 재가속",
    "LATE_STAGE": "상승 후반부(분할익절 검토 구간)", "DOWNTREND_TRANSITION": "하락 전환 중",
}
_DOW_STATE_HELP = {
    "DOWNTREND": "LH/LL 하락 구조 (직전 2개 고점·저점 모두 LH/LL)",
    "REVERSAL_CANDIDATE": (
        "하락추세 이탈 시작 — 아직 상승추세 확정(HH+HL) 전 단계. 둘 중 하나만 걸려도 해당: "
        "① 오늘 종가가 직전 LH(하락고점)를 상향 돌파, ② 확정 전 최근 저점이 직전 LL(하락저점)보다 "
        "높게 형성 중 (②만 걸리면 아직 가격 반등 없이 저점만 다지는 중일 수 있음 — '반등'과는 다름)"
    ),
    "UPTREND": "HH/HL 상승 구조 (가장 최근 고점·저점이 HH/HL로 확정)",
    "RANGE": "박스권/구조 불명확 (위 조건 어디에도 안 걸림)",
}
_ADX_GATE_HELP = {
    "PASS": (
        "추세 강도 조건 통과 — 진입에 우호적. 아래 3가지 중 하나만 맞아도 PASS: "
        "① MDI 하락 + ADX 고점에서 하락, ② MDI 하락 + ADX 기울기 완만(횡보), "
        "③ MDI 하락 + ADX 저점 대비 상승전환 + 반전 핵심점수(Reversal) 이미 강세"
    ),
    "CAUTION": "애매함 — 진입 자체는 막지 않되 신중히 (PASS/BLOCK 어느 조건에도 안 걸리면 기본값)",
    "BLOCK": "추세 강도가 진입에 불리 — 신규 진입 차단. MDI+ADX 동반 상승 또는 RSI 25 이하 또는 다우 하락추세에서 LH 미돌파 중 하나면 BLOCK",
}

_REASON_CODE_HELP: dict[str, str] = {
    "DOW_DOWNTREND": "다우 구조 하락추세 확인",
    "DOW_REVERSAL_CANDIDATE": "하락추세 이탈 시작(다우 반전 후보)",
    "DOW_LAST_LH_BROKEN": "직전 LH(하락고점) 돌파",
    "DOW_HL_CONFIRMED": "HL(상승저점) 구조 형성/유지",
    "DOW_HH_CONFIRMED": "HH(상승고점) 구조 확정",
    "MACD_ABOVE_SIGNAL": "MACD가 시그널선 상회",
    "MACD_ABOVE_ZERO": "MACD가 0선 상회",
    "MACD_CROSS_UP_RECENT": "최근 MACD 골든크로스 발생",
    "RSI_ABOVE_25": "RSI 25 초과(진입 최소 조건)",
    "RSI_BELOW_25_BLOCK": "RSI 25 미만 — 점수 상한 제한/진입 차단",
    "RSI_ABOVE_50": "RSI 50 초과(상승 모멘텀 우위)",
    "RSI_TURN_UP": "RSI 상승 전환",
    "ADX_ABOVE_30": "ADX 30 이상(강한 추세)",
    "ADX_FALLING_FROM_HIGH": "ADX가 고점에서 하락 중(추세 약화)",
    "ADX_FLATTENING": "ADX 기울기 완만해짐",
    "ADX_TURN_UP": "ADX 저점 대비 상승 전환",
    "MDI_FALLING": "-DI(하락압력) 하락 중",
    "MDI_RISING_BLOCK": "-DI 상승 + ADX 상승 — 하락 방향성 강화(진입 차단)",
    "PULLBACK_HL_HOLD": "눌림 저점이 기존 HL 미훼손",
    "LATE_BEARISH_DIVERGENCE": "가격 HH인데 RSI는 LH — 약세 다이버전스",
    "LATE_MA5_ACCELERATION": "5일선 이격 급팽창(고점권 과열 신호)",
    "CYCLE_HH_HL_CONFIRMED": "HH+HL 확정 — 상승추세 진입",
    "CYCLE_PULLBACK_STARTED": "고점 이후 조정 시작",
    "CYCLE_LH_CANDIDATE": "LH(하락고점) 후보 발생",
    "CYCLE_HL_BREACHED": "주요 HL(상승저점) 훼손",
}

_REASON_CODE_SHORT: dict[str, str] = {
    "DOW_DOWNTREND": "하락구조", "DOW_REVERSAL_CANDIDATE": "반전후보",
    "DOW_LAST_LH_BROKEN": "LH돌파", "DOW_HL_CONFIRMED": "HL형성", "DOW_HH_CONFIRMED": "HH확정",
    "MACD_ABOVE_SIGNAL": "MACD+", "MACD_ABOVE_ZERO": "MACD0선+", "MACD_CROSS_UP_RECENT": "MACD GC",
    "RSI_ABOVE_25": "RSI25+", "RSI_BELOW_25_BLOCK": "RSI25↓차단", "RSI_ABOVE_50": "RSI50+", "RSI_TURN_UP": "RSI반등",
    "ADX_ABOVE_30": "ADX30+", "ADX_FALLING_FROM_HIGH": "ADX하락", "ADX_FLATTENING": "ADX완만", "ADX_TURN_UP": "ADX반등",
    "MDI_FALLING": "MDI하락", "MDI_RISING_BLOCK": "MDI↑차단",
    "PULLBACK_HL_HOLD": "HL유지",
    "LATE_BEARISH_DIVERGENCE": "약세다이버전스", "LATE_MA5_ACCELERATION": "MA5과열",
    "CYCLE_HH_HL_CONFIRMED": "HH+HL확정", "CYCLE_PULLBACK_STARTED": "조정시작",
    "CYCLE_LH_CANDIDATE": "LH후보", "CYCLE_HL_BREACHED": "HL훼손",
}


def _summarize_reasons(reasons: list[str], max_items: int = 2) -> str:
    """표 보조 컬럼용 — reason code 전체 목록(상세 패널에서 봄) 대신 앞 2개만 짧은
    라벨로 요약. 그 이상은 "+N"으로 남은 개수만 표시(표 셀 가독성 우선)."""
    if not reasons:
        return "-"
    labels = [_REASON_CODE_SHORT.get(r, r) for r in reasons[:max_items]]
    text = " · ".join(labels)
    remaining = len(reasons) - max_items
    if remaining > 0:
        text += f" 외 {remaining}"
    return text


def _render_legend() -> None:
    with st.expander("📖 용어/범례 설명"):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Action (행동 제안)** — 빨강=매수쪽(신규진입/추가/분할익절), 파랑=매도/위험관리쪽(손절/청산)")
            for k, v in _ACTION_HELP.items():
                color = _ACTION_COLOR.get(k, "gray")
                st.markdown(f"- :{color}[**`{k}`**] — {v}")
            st.markdown("**Cycle State (사이클 단계)**")
            for k, v in _CYCLE_STATE_HELP.items():
                st.markdown(f"- `{k}` — {v}")
            st.markdown("**Dow State (다우 구조)**")
            for k, v in _DOW_STATE_HELP.items():
                st.markdown(f"- `{k}` — {v}")
            st.markdown("**ADX Gate (추세 강도 필터)**")
            for k, v in _ADX_GATE_HELP.items():
                st.markdown(f"- `{k}` — {v}")
        with col2:
            st.markdown("**점수 (0~100) — 각각 무엇을 재고, 어떻게 산정하는가**")
            st.markdown(
                "- `Reversal(진입검토)` — 하락추세 이탈 후 반전 진입 신호 종합점수. "
                "다우 구조 45점 + MACD 30점 + RSI 25점 = 100점 만점 합산. "
                "단, RSI가 25 이하면 총점을 69점으로 강제 제한(ENTRY 80점 원천 차단). "
                "70 이상=READY, 80 이상=ENTRY.\n"
                "- `Pullback(재진입검토)` — 이미 확정된 상승추세(HH-HL) 내부 눌림목 재진입 신호 종합점수. "
                "다우 35점 + MACD 20점 + RSI 20점 + ADX 15점 + 눌림목 품질 10점 = 100점 만점 합산. "
                "65 이상=READY, 75 이상=ENTRY.\n"
                "- `Late Stage(분할매도검토)` — 상승 후반부 과열/약세 다이버전스 감지 점수(분할익절 타이밍용, "
                "전량매도 신호 아님). 약세 다이버전스 35점 + RSI 고점 연속 하락(2회 이상) 20점 + "
                "가격 신고점인데 ADX는 고점에서 하락 15점 + MA5 이격 급팽창 20점 + 전고점/박스상단 근접 10점 = "
                "최대 100점. 60 이상=분할익절 준비, 75 이상=분할익절 제안(TAKE_PROFIT_PARTIAL)."
            )
            st.markdown(
                "**MACD/RSI/ADX 원시값은 어디서 보나** — 표는 요약 점수만 보여준다. "
                "표 왼쪽 체크박스를 선택하면 아래 상세 패널에 MACD/Signal/0선 여부·RSI·ADX/MDI 실제 수치와 "
                "최근 pivot, 전체 판단 근거(Reason Codes)가 표시된다."
            )
            st.markdown("**Reason Codes (판단 근거)**")
            for k, v in _REASON_CODE_HELP.items():
                st.markdown(f"- `{k}` — {v}")
            st.caption("최근 pivot: HH=상승고점, HL=상승저점, LH=하락고점, LL=하락저점, EH/EL=직전과 동일가(중립)")


def _signed_value(value: float) -> str:
    """0선 기준 색상 — 한국 증시 관례(0선 위=빨강/상승, 0선 아래=파랑/하락)를 그대로 따른다."""
    color = "red" if value > 0 else "blue"
    return f":{color}[{value:,.2f}]"


def _trend_arrow(rising: bool | None) -> str:
    """전일 대비 상승/하락 화살표 — Action 색상과 같은 관례(빨강=상승, 파랑=하락)."""
    if rising is None:
        return ""
    return " :red[↑]" if rising else " :blue[↓]"


def _render_dashboard_card(card: ReportCard) -> None:
    d = card.decision
    color = _ACTION_COLOR.get(d.action.value, "gray")

    with st.container(border=True):
        header_col, badge_col = st.columns([4, 1])
        with header_col:
            group = f" · {d.friend_group}" if d.friend_group else ""
            st.markdown(f"**{d.name}** ({d.symbol}){group}")
        with badge_col:
            st.markdown(f":{color}[**{d.action.value}**]")

        cycle_help = _CYCLE_STATE_HELP.get(d.cycle_state.value, "")
        dow_help = _DOW_STATE_HELP.get(card.dow_state, "")
        st.caption(f"Cycle: {d.cycle_state.value}({cycle_help}) · Dow: {card.dow_state}({dow_help})")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Reversal(진입검토)", f"{d.reversal_core_score:.0f}")
        m2.metric("ADX Gate", d.adx_gate.value)
        m3.metric("Pullback(재진입검토)", f"{d.pullback_score:.0f}")
        m4.metric("Late Stage(분할매도검토)", f"{d.late_stage_score:.0f}")

        macd_cmp = ">" if card.macd > card.macd_signal else "<"
        st.markdown(
            f"MACD({_signed_value(card.macd)}) {macd_cmp} Signal({_signed_value(card.macd_signal)})"
            f"{_trend_arrow(card.macd_rising)}"
        )

        rsi_line = f"RSI ({card.rsi14:.1f})"
        if card.rsi_signal is not None:
            rsi_cmp = ">" if card.rsi14 > card.rsi_signal else "<"
            rsi_line += f" {rsi_cmp} Signal({card.rsi_signal:.1f})"
        rsi_line += _trend_arrow(card.rsi_rising)
        st.markdown(rsi_line)

        mdi_pdi_cmp = ">" if card.mdi > (card.pdi or 0.0) else "<"
        st.markdown(
            f"ADX ({card.adx:.1f}){_trend_arrow(card.adx_rising)} "
            f"(MDI {card.mdi:.1f}{_trend_arrow(card.mdi_rising)} {mdi_pdi_cmp} "
            f"PDI {(card.pdi or 0.0):.1f}{_trend_arrow(card.pdi_rising)})"
        )

        if card.last_pivot_labels:
            pivots_str = "  ".join(f"{label}={price:,.0f}" for label, price in card.last_pivot_labels.items())
            price_prefix = f"(현재가 {card.close_price:,.0f}) " if card.close_price else ""
            st.caption(f"{price_prefix}최근 pivot: {pivots_str}")

        if d.stop_price:
            st.caption(f"제안 Stop: {d.stop_price:,.0f}")

        if d.reasons:
            reason_parts = [f"{r}({_REASON_CODE_HELP.get(r, '-')})" for r in d.reasons]
            st.caption(" · ".join(reason_parts))


def _build_summary_table(cards: list[ReportCard]) -> pd.DataFrame:
    """표 형태 기본 뷰용 — 카드 전부를 한 눈에 스캔/정렬하기 위한 핵심 컬럼만 추림.
    MACD/RSI/ADX 원시값·pivot 같은 상세 정보는 표에 넣으면 오히려 가독성이 떨어져서
    뺐다 — 행 선택 시 아래 상세 패널(_render_dashboard_card)에서 보여준다. Reason code는
    전체 목록 대신 _summarize_reasons()로 요약한 "핵심근거" 보조 컬럼 하나만 둔다."""
    rows = []
    for c in cards:
        d = c.decision
        emoji = _ACTION_EMOJI.get(_ACTION_COLOR.get(d.action.value, "gray"), "")
        rows.append({
            "종목명": d.name, "코드": d.symbol, "그룹": d.friend_group or "-",
            "Action": f"{emoji} {d.action.value}", "Cycle": d.cycle_state.value, "Dow": c.dow_state,
            "Reversal": d.reversal_core_score, "ADX Gate": d.adx_gate.value,
            "Pullback": d.pullback_score, "Late Stage": d.late_stage_score,
            "핵심근거": _summarize_reasons(d.reasons),
            "제안 Stop": d.stop_price,
        })
    return pd.DataFrame(rows)


_TABLE_COLUMN_CONFIG = {
    "종목명": st.column_config.TextColumn(width="small"),
    "코드": st.column_config.TextColumn(width="small"),
    "그룹": st.column_config.TextColumn(width="small"),
    "Action": st.column_config.TextColumn(help="행동 제안 — 위 범례의 Action 항목 참고", width="small"),
    "Cycle": st.column_config.TextColumn(help="사이클 단계 — 위 범례의 Cycle State 항목 참고", width="small"),
    "Dow": st.column_config.TextColumn(help="다우 구조 — 위 범례의 Dow State 항목 참고", width="small"),
    "Reversal": st.column_config.ProgressColumn(help="Reversal Entry 점수(0~100). 70=READY, 80=ENTRY 임계값", min_value=0, max_value=100, format="%.0f"),
    "ADX Gate": st.column_config.TextColumn(help="추세 강도 필터 — 위 범례의 ADX Gate 항목 참고", width="small"),
    "Pullback": st.column_config.ProgressColumn(help="Pullback Entry 점수(0~100). 65=READY, 75=ENTRY 임계값", min_value=0, max_value=100, format="%.0f"),
    "Late Stage": st.column_config.ProgressColumn(help="Late Stage/약세 다이버전스 점수(0~100). 60=준비, 75=분할익절 제안", min_value=0, max_value=100, format="%.0f"),
    "핵심근거": st.column_config.TextColumn(help="주요 판단 근거 최대 2개 요약 — 전체 목록은 행 선택 시 상세 패널에서 확인", width="medium"),
    "제안 Stop": st.column_config.NumberColumn(help="16장 — 최근 confirmed pivot low 기준 제안 손절가", format="%.0f"),
}

_SORT_OPTIONS = {
    "우선순위 (기본: STOP→ENTRY→ADD→익절→READY→WAIT)": None,  # 이미 sort_decisions_for_report로 정렬된 순서 유지
    "Reversal 점수 높은 순": lambda c: -c.decision.reversal_core_score,
    "Pullback 점수 높은 순": lambda c: -c.decision.pullback_score,
    "Late Stage 점수 높은 순": lambda c: -c.decision.late_stage_score,
}


@st.cache_data(ttl=300)
def _reconcile_recent_history_cached() -> dict | None:
    """Supabase에는 있지만 로컬엔 없는 최근 이력만 보완 — 대시보드 rerun마다(필터 클릭 등)
    매번 네트워크를 때리지 않도록 5분에 한 번만 실제로 호출한다. dev/prod가 서로 다른
    로컬 SQLite 이력을 갖고 있어 상승/하락 화살표 등이 환경마다 다르게 보이던 문제(새
    환경 부트스트랩 시 이력 부족)를 자동으로 메운다."""
    conn = get_connection()
    try:
        return reconcile_recent_history(conn, get_supabase_client())
    except Exception as exc:  # noqa: BLE001 — 미설정/네트워크 문제로 대시보드가 죽으면 안 됨
        logger.warning("[dashboard] Supabase 이력 보완 건너뜀: %s", exc)
        return None
    finally:
        conn.close()


def render_dashboard() -> None:
    st.subheader("대시보드")
    _render_legend()

    # jobs/*.py는 전부 get_connection() 전에 run_migrations()를 부른다 — 여기서 빠뜨리면
    # 배치를 한 번도 안 돌린 새 배포/새 DB 파일에서 "no such table: scores_daily"로
    # 대시보드 자체가 크래시한다(실제로 이 세션에서 겪은 버그 — SCR을 먼저 띄우고
    # 나중에 CLI로 collect/decide를 처음 돌렸더니 그 사이에 대시보드가 이 예외로 죽었음).
    run_migrations()
    _reconcile_recent_history_cached()
    conn = get_connection()
    try:
        latest = decision_repo.get_latest_trade_date(conn)
        if latest is None:
            st.info(
                "아직 판정 결과가 없습니다 — 배치(`swingcycle decide --date YYYY-MM-DD`)가 "
                "한 번도 실행되지 않았거나 종목 유니버스가 비어 있습니다."
            )
            return

        selected = st.date_input("조회 날짜", value=latest, max_value=date.today())
        cards = get_report_cards(conn, selected)
        symbol_sort_order = dict(conn.execute("SELECT symbol, sort_order FROM symbols").fetchall())
    finally:
        conn.close()

    if not cards:
        st.warning(f"{selected.isoformat()} 판정 결과가 없습니다 (배치 미실행 또는 휴장일).")
        return

    cards = sort_decisions_for_report(cards)  # 21장: STOP/EXIT → ENTRY → ADD → TAKE_PROFIT_PARTIAL → READY → WAIT
    total_count = len(cards)

    # WAIT은 보통 종목 수가 가장 많고 실제 행동이 필요 없는 상태라, 기본 필터에서는
    # 빼서 "지금 봐야 할 종목"만 먼저 보이게 한다 — 전체를 보려면 필터에서 다시 켜면 된다.
    counts_all = Counter(c.decision.action.value for c in cards)
    action_options = [a for a in counts_all if a != "WAIT"] + (["WAIT"] if "WAIT" in counts_all else [])
    default_actions = [a for a in action_options if a != "WAIT"] or action_options

    filter_col, sort_col = st.columns([2, 1])
    with filter_col:
        selected_actions = st.pills(
            "빠른 필터 (Action)",
            options=action_options,
            selection_mode="multi",
            default=default_actions,
            key="dashboard_action_filter",
        )
    sort_options = {
        **_SORT_OPTIONS,
        "테마순": lambda c: (c.decision.friend_group or "", c.decision.symbol),
        "사용자 지정 순서": lambda c: (
            symbol_sort_order.get(c.decision.symbol)
            if symbol_sort_order.get(c.decision.symbol) is not None else 999_999,
            c.decision.symbol,
        ),
    }
    with sort_col:
        sort_label = st.selectbox("정렬 기준", options=list(sort_options), key="dashboard_sort")

    cards = [c for c in cards if c.decision.action.value in selected_actions]
    sort_key = sort_options[sort_label]
    if sort_key is not None:
        cards = sorted(cards, key=sort_key)

    cards_by_symbol = {c.decision.symbol: c for c in cards}

    counts = Counter(c.decision.action.value for c in cards)
    summary = " · ".join(f"{action} {n}" for action, n in counts.items()) if counts else "필터 결과 없음"
    st.caption(f"{selected.isoformat()} 기준 {len(cards)}/{total_count}개 종목 — {summary}")

    if not cards:
        st.info("선택한 필터에 해당하는 종목이 없습니다. 위 '빠른 필터'에서 Action을 추가로 선택해라.")
        return

    table = _build_summary_table(cards)

    excel_buf = io.BytesIO()
    with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
        table.to_excel(writer, index=False, sheet_name="dashboard")
    st.download_button(
        "엑셀 저장",
        data=excel_buf.getvalue(),
        file_name=f"swingcycle_dashboard_{selected.isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dashboard_excel_download",
    )

    event = st.dataframe(
        table,
        column_config=_TABLE_COLUMN_CONFIG,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key="dashboard_table",
    )

    selected_rows = event.selection.rows if event and event.selection else []
    logger.info(
        "[dashboard] date=%s row_count=%d selection_event=%s",
        selected.isoformat(), len(table), dict(event.selection) if event and event.selection else None,
    )
    if selected_rows:
        symbol = table.iloc[selected_rows[0]]["코드"]
        st.markdown("---")
        st.markdown(f"**상세 — {symbol}**")
        _render_dashboard_card(cards_by_symbol[symbol])
    else:
        st.caption("표 왼쪽 체크박스를 선택하면 해당 종목의 상세(MACD/RSI/ADX/pivot/근거)가 아래에 표시됩니다.")


def render_universe_management(identity) -> None:
    st.subheader("종목 관리 (절친 Universe)")

    try:
        client = get_supabase_client()
    except RuntimeError as exc:
        st.error(f"Supabase 연결 실패: {exc}")
        return

    rows = client.table("swingcycle_symbols").select("*").order("symbol").execute().data or []
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["symbol", "name", "market", "friend_group", "sort_order", "enabled", "note"]
    )
    if "sort_order" not in df.columns:  # 스키마 반영 전(Supabase ALTER 미실행) 과도기 방어
        df["sort_order"] = None
    if not df.empty:
        df = df.sort_values(["sort_order", "symbol"], na_position="last").reset_index(drop=True)

    if identity is None:
        st.warning("허브 인증 정보를 확인할 수 없습니다 — 읽기 전용으로 표시합니다.")

    st.caption(
        "표에서 행을 지우면 즉시 삭제되지 않고 **비활성화(enabled=false)** 됩니다. "
        "완전 삭제는 아래 '완전 삭제' 섹션에서 별도로 확인 후 진행하세요. "
        "**순번**을 지정하면 이 표와 대시보드('사용자 지정 순서' 정렬)에서 그 순서대로 보입니다."
    )
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        disabled=identity is None,
        use_container_width=True,
        key="universe_editor",
        column_config={
            "symbol": st.column_config.TextColumn("종목코드"),
            "name": st.column_config.TextColumn("종목명"),
            "market": st.column_config.TextColumn("시장"),
            "friend_group": st.column_config.TextColumn("테마"),
            "sort_order": st.column_config.NumberColumn("순번", min_value=0, step=1),
            "enabled": st.column_config.CheckboxColumn("활성화"),
            "note": st.column_config.TextColumn("비고"),
            "created_at": st.column_config.TextColumn("생성일시"),
            "updated_at": st.column_config.TextColumn("수정일시"),
            "updated_by": st.column_config.TextColumn("수정자"),
        },
    )

    save_col, update_col = st.columns(2)
    with save_col:
        if st.button("저장", disabled=identity is None):
            _save_universe_diff(client, df, edited, identity)
    with update_col:
        if st.button("저장 + 업데이트", disabled=identity is None):
            _update_universe_and_batch(client, df, edited, identity)
    st.caption(
        "업데이트: 저장 후 곧바로 MFTS parquet 캐시에서 시세를 읽어 지표/판정을 계산하고 "
        "Supabase에도 기록합니다 — 종목 수에 비례해 수십 초~수 분 걸릴 수 있습니다 "
        "(안 눌러도 매일 밤 배치가 자동으로 처리합니다)."
    )

    _render_universe_excel_upload(client, df, identity)

    if not df.empty:
        _render_hard_delete_section(client, df, identity)


def _upsert_universe_rows(client, original: pd.DataFrame, edited: pd.DataFrame, identity) -> dict:
    """행 삭제는 soft-disable(enabled=false)로만 반영한다 — 완전 삭제는 별도 확인 절차(8장) 필요.

    전문가 리뷰에서 발견된 버그 수정: 이전에는 표에서 행이 사라지면 바로
    client.table(...).delete()를 호출해 즉시 하드 삭제됐다.
    """
    original_symbols = set(original["symbol"]) if not original.empty else set()
    edited_symbols = set(edited["symbol"].dropna())
    removed_from_grid = original_symbols - edited_symbols

    def _sort_order_of(row) -> int | None:
        value = row.get("sort_order")
        return None if value is None or pd.isna(value) else int(value)

    upsert_rows = []
    for _, row in edited.iterrows():
        if not row.get("symbol"):
            continue
        upsert_rows.append({
            "symbol": row["symbol"],
            "name": row.get("name") or "",
            "market": row.get("market") or None,
            "friend_group": row.get("friend_group") or None,
            "sort_order": _sort_order_of(row),
            "enabled": bool(row.get("enabled", True)),
            "note": row.get("note") or None,
            "updated_by": identity.email,
        })
    # 표에서 지워진 종목은 하드 삭제 대신 enabled=false로 upsert (soft-disable 기본값)
    for symbol in removed_from_grid:
        original_row = original.loc[original["symbol"] == symbol].iloc[0]
        upsert_rows.append({
            "symbol": symbol,
            "name": original_row.get("name") or "",
            "market": original_row.get("market") or None,
            "friend_group": original_row.get("friend_group") or None,
            "sort_order": _sort_order_of(original_row),
            "enabled": False,
            "note": original_row.get("note") or None,
            "updated_by": identity.email,
        })

    if upsert_rows:
        client.table("swingcycle_symbols").upsert(upsert_rows).execute()

    return {"upserts": len(upsert_rows), "disabled": len(removed_from_grid)}


def _save_universe_diff(client, original: pd.DataFrame, edited: pd.DataFrame, identity) -> None:
    result = _upsert_universe_rows(client, original, edited, identity)
    st.success(f"저장 완료: upsert {result['upserts']}건 (표에서 지운 {result['disabled']}건은 비활성화 처리)")
    st.rerun()


def _run_remote_update_via_ssh() -> tuple[date, dict, dict]:
    """개발 환경의 parquet 캐시는 전체 시장이 아니라 소규모 개인 캐시라, Oracle(전체
    시장 parquet 보유)에 SSH로 위임해서 처리한다. Oracle이 방금 Supabase에 올린 결과를
    reconcile_recent_history로 곧바로 로컬에 당겨온다(대시보드의 5분 캐시를 안 기다림).

    ORACLE_SSH_HOST가 비어있으면(미설정) 조용히 로컬 처리로 폴백한다."""
    if not settings.oracle_ssh_host:
        return run_update_latest()

    cmd = [
        "ssh", "-i", str(Path(settings.oracle_ssh_key_path).expanduser()),
        "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new",
        f"{settings.oracle_ssh_user}@{settings.oracle_ssh_host}",
        f"cd {settings.oracle_project_dir} && .venv/bin/swingcycle update-latest",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    if result.returncode != 0:
        raise RuntimeError(f"Oracle 원격 실행 실패(exit={result.returncode}): {result.stderr[-500:]}")

    payload = json.loads(result.stdout.strip().splitlines()[-1])
    trade_date_ = date.fromisoformat(payload["trade_date"])

    conn = get_connection()
    try:
        reconcile_recent_history(conn, get_supabase_client())
    finally:
        conn.close()

    return trade_date_, payload["collect"], payload["decide"]


def _run_universe_batch() -> tuple[date, dict, dict] | None:
    """collect-parquet -> decide를 재사용해 즉시 실행 — 새로 추가한 종목이 다음 크론을
    기다리지 않고 바로 대시보드에 보이게 한다. 기존 종목은 idempotent라 그냥 스킵된다.

    Oracle 자신(ENV=production)은 이미 전체 시장 parquet을 갖고 있으므로 그대로 로컬
    처리한다. 개발 환경은 자체 캐시가 작으므로 Oracle에 SSH로 위임한다(사용자 요청:
    "로컬에서 새 종목을 추가하면 Oracle에 전달해서 Oracle 전체 parquet으로 처리하고
    Supabase 업데이트 결과를 로컬 화면에 반영").

    실패해도 예외를 올리지 않고 st.error만 띄운다 — 호출부(저장/업로드)는 이미 끝난
    상태라 배치 실패로 화면 전체가 죽으면 안 된다. 실패 시 None을 반환한다."""
    with st.spinner("업데이트 중 — parquet 수집 + 지표 계산 (몇 분 걸릴 수 있습니다)..."):
        try:
            if os.getenv("ENV", "local") == "production":
                trade_date_, collect_result, decide_result = run_update_latest()
            else:
                trade_date_, collect_result, decide_result = _run_remote_update_via_ssh()
        except Exception as exc:  # noqa: BLE001 — 저장은 이미 끝났으니 배치 실패로 화면이 죽으면 안 됨
            logger.exception("[universe] 업데이트 배치 실패")
            st.error(f"저장은 완료됐지만 배치 실행 중 오류가 발생했습니다: {exc}")
            return None

    return trade_date_, collect_result, decide_result


def _update_universe_and_batch(client, original: pd.DataFrame, edited: pd.DataFrame, identity) -> None:
    result = _upsert_universe_rows(client, original, edited, identity)

    batch = _run_universe_batch()
    if batch is None:
        return
    trade_date_, collect_result, decide_result = batch

    st.success(
        f"저장 완료(upsert {result['upserts']}건) + {trade_date_.isoformat()} 업데이트 완료 — "
        f"수집 {collect_result.get('rows', 0)}행, 판정 처리 {decide_result.get('processed', 0)}건 "
        f"(이미 처리됨 {decide_result.get('skipped_already_done', 0)}건)"
    )
    st.rerun()


_EXCEL_REQUIRED_COLUMNS = ("NO", "종목명", "종목코드")


def _parse_universe_excel(uploaded_file) -> tuple[pd.DataFrame, list[str]]:
    """개인 관심종목 스프레드시트(NO/종목명/종목코드/메모 + 그날의 시세 스냅샷 컬럼들)에서
    우리 시스템과 관련있는 4개 컬럼만 뽑는다. 시세 컬럼(현재가/거래량/시가총액 등)은 버린다.

    종목코드가 비어있는 행(코드 미확정 관심종목)은 결과에서 빼고 이름을 별도로 반환한다 —
    symbol이 PK라 코드 없이는 반영할 수 없다."""
    raw = pd.read_excel(uploaded_file)
    missing = [c for c in _EXCEL_REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {missing} (NO/종목명/종목코드는 반드시 있어야 합니다)")

    skipped = raw[raw["종목코드"].isna()]["종목명"].tolist()
    valid = raw.dropna(subset=["종목코드"]).copy()

    parsed = pd.DataFrame({
        "symbol": valid["종목코드"].apply(lambda x: str(int(x)).zfill(6)),
        "name": valid["종목명"],
        "note": valid["메모"] if "메모" in valid.columns else None,
        "sort_order": valid["NO"].astype(int),
    })
    parsed["note"] = parsed["note"].where(parsed["note"].notna(), None)
    return parsed.reset_index(drop=True), skipped


def _upload_universe_excel(client, current_df: pd.DataFrame, parsed: pd.DataFrame, identity) -> dict:
    """market/friend_group은 엑셀에 없는 정보라, 이미 있는 종목이면 현재 값을 그대로
    상속한다(덮어써서 지우면 안 됨 — market 컬럼을 부주의하게 upsert로 날렸던 실수를
    반복하지 않기 위함). 파일에 있다는 것 자체를 "현재 관심종목"으로 보고 enabled=True."""
    existing_by_symbol = (
        current_df.set_index("symbol").to_dict("index") if not current_df.empty else {}
    )
    new_count = 0
    upsert_rows = []
    for _, row in parsed.iterrows():
        existing = existing_by_symbol.get(row["symbol"])
        if existing is None:
            new_count += 1
        upsert_rows.append({
            "symbol": row["symbol"],
            "name": row["name"],
            "market": (existing or {}).get("market") or None,
            "friend_group": (existing or {}).get("friend_group") or None,
            "sort_order": int(row["sort_order"]),
            "enabled": True,
            "note": row["note"],
            "updated_by": identity.email,
        })

    if upsert_rows:
        client.table("swingcycle_symbols").upsert(upsert_rows).execute()

    return {"new": new_count, "updated": len(upsert_rows) - new_count}


def _render_universe_excel_upload(client, current_df: pd.DataFrame, identity) -> None:
    with st.expander("절친종목 엑셀 업로드"):
        st.caption(
            "NO(순번)/종목명/종목코드/메모 컬럼이 있는 엑셀을 업로드하면 이 4개만 반영합니다 "
            "(현재가 등 시세 컬럼은 무시). market/테마는 엑셀에 없으므로 기존 값을 그대로 유지합니다."
        )
        uploaded = st.file_uploader("엑셀 파일(.xlsx)", type=["xlsx"], key="universe_excel_uploader")
        if uploaded is not None:
            try:
                parsed, skipped = _parse_universe_excel(uploaded)
                st.session_state["excel_upload_preview"] = (uploaded.name, parsed, skipped)
            except Exception as exc:  # noqa: BLE001 — 잘못된 파일이어도 화면이 죽으면 안 됨
                st.error(f"엑셀 파싱 실패: {exc}")
                st.session_state.pop("excel_upload_preview", None)

        preview = st.session_state.get("excel_upload_preview")
        if not preview:
            return
        file_name, parsed, skipped = preview
        existing_symbols = set(current_df["symbol"]) if not current_df.empty else set()
        new_count = len(set(parsed["symbol"]) - existing_symbols)
        st.caption(
            f"'{file_name}' — 신규 {new_count}건 / 업데이트 {len(parsed) - new_count}건"
            + (f" / 종목코드 없어 건너뜀 {len(skipped)}건: {', '.join(skipped)}" if skipped else "")
        )
        st.dataframe(parsed, use_container_width=True)

        if st.button("반영", disabled=identity is None, key="excel_upload_apply"):
            result = _upload_universe_excel(client, current_df, parsed, identity)
            batch = _run_universe_batch()
            del st.session_state["excel_upload_preview"]
            if batch is None:
                return
            trade_date_, collect_result, decide_result = batch
            st.success(
                f"업로드 반영 완료(신규 {result['new']}건 / 업데이트 {result['updated']}건) + "
                f"{trade_date_.isoformat()} 업데이트 완료 — 수집 {collect_result.get('rows', 0)}행, "
                f"판정 처리 {decide_result.get('processed', 0)}건"
            )
            st.rerun()


def _render_hard_delete_section(client, df: pd.DataFrame, identity) -> None:
    """완전 삭제 — 8장 "완전 삭제 별도 확인 버튼" + 7.3 "활성 플랜 경고"."""
    with st.expander("⚠️ 완전 삭제 (되돌릴 수 없음)"):
        symbol_options = df["symbol"].dropna().tolist()
        target = st.selectbox("완전 삭제할 종목코드", options=[""] + symbol_options, key="hard_delete_target")
        if not target:
            return

        try:
            conn = get_connection()
            has_active = has_active_trade_plan(conn, target)
            conn.close()
        except Exception:
            has_active = None  # 로컬 DB 조회 실패 시에도 삭제 자체는 차단하지 않음 — 경고만 못 띄움

        if has_active:
            st.error(
                f"'{target}'은(는) 로컬에 ACTIVE 트레이드 플랜이 있습니다. "
                "완전 삭제해도 진행 중인 포지션 기록은 남지만, 신규 진입 판단용 유니버스에서는 사라집니다."
            )
        elif has_active is None:
            st.warning("로컬 DB에서 활성 플랜 여부를 확인하지 못했습니다 (DB 접근 실패).")

        confirm_text = st.text_input(f"확인을 위해 종목코드 '{target}'를 그대로 입력하세요", key="hard_delete_confirm")
        if st.button("완전 삭제 실행", disabled=(identity is None or confirm_text != target)):
            client.table("swingcycle_symbols").delete().eq("symbol", target).execute()
            st.success(f"'{target}' 완전 삭제 완료")
            st.rerun()


def render_backtest_placeholder() -> None:
    st.subheader("백테스트/검증")
    st.info(
        "A/B/C 비교 엔진(backtest/variants.py)은 구현 완료 — 이 탭은 결과 열람(읽기 전용) "
        "UI 연결 예정."
    )


def main() -> None:
    st.title("SwingCycle Radar")

    identity = resolve_hub_identity()
    if identity:
        st.caption(f"로그인: {identity.email} ({identity.source})")

    tab_dashboard, tab_universe, tab_backtest = st.tabs(["대시보드", "종목 관리", "백테스트/검증"])
    with tab_dashboard:
        render_dashboard()
    with tab_universe:
        render_universe_management(identity)
    with tab_backtest:
        render_backtest_placeholder()


if __name__ == "__main__":
    main()
