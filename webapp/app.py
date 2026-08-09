"""SwingCycle Radar Streamlit 앱 골격.

설계: docs/SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md 3장(런타임 결정), 8장(종목 관리), 9장(UI)

Hub 게이트만으로 인증(MFTS 패턴, 4.3) — 앱 내부 로그인 폼 없음.
단, 종목 CRUD의 updated_by 기록을 위해 신원 확인 브리지(4.4)만 별도로 둔다.
"""
from __future__ import annotations

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
from swingcycle.jobs.daily_report_job import get_report_cards  # noqa: E402
from swingcycle.reports.daily_report import ReportCard, sort_decisions_for_report  # noqa: E402
from swingcycle.repositories import decision_repo  # noqa: E402
from swingcycle.repositories.db import get_connection, run_migrations  # noqa: E402
from swingcycle.repositories.symbol_repo import has_active_trade_plan  # noqa: E402

st.set_page_config(page_title="SwingCycle Radar", page_icon="🧭", layout="wide")

_ACTION_COLOR = {
    "STOP": "red", "EXIT": "red",
    "ENTRY": "green",
    "ADD": "blue",
    "TAKE_PROFIT_PARTIAL": "violet",
    "READY": "orange",
    "WAIT": "gray",
    "RESET": "gray",
}

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
    "DOWNTREND": "LH/LL 하락 구조", "REVERSAL_CANDIDATE": "하락추세 이탈 시작",
    "UPTREND": "HH/HL 상승 구조", "RANGE": "박스권/구조 불명확",
}
_ADX_GATE_HELP = {
    "PASS": "추세 강도 조건 통과 — 진입에 우호적",
    "CAUTION": "애매함 — 진입 자체는 막지 않되 신중히",
    "BLOCK": "추세 강도가 진입에 불리 — 신규 진입 차단",
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


def _render_legend() -> None:
    with st.expander("📖 용어/범례 설명"):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Action (행동 제안)**")
            for k, v in _ACTION_HELP.items():
                st.markdown(f"- `{k}` — {v}")
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
            st.markdown(
                "**점수 (0~100)** — Reversal은 70(READY)/80(ENTRY), "
                "Pullback은 65(READY)/75(ENTRY) 이상이면 후보. Late Stage는 "
                "60 이상 분할익절 준비, 75 이상 분할익절 제안."
            )
            st.markdown("**Reason Codes (판단 근거)**")
            for k, v in _REASON_CODE_HELP.items():
                st.markdown(f"- `{k}` — {v}")
            st.caption("최근 pivot: HH=상승고점, HL=상승저점, LH=하락고점, LL=하락저점, EH/EL=직전과 동일가(중립)")


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

        st.caption(f"Cycle: {d.cycle_state.value} · Dow: {card.dow_state}")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Reversal", f"{d.reversal_core_score:.0f}")
        m2.metric("ADX Gate", d.adx_gate.value)
        m3.metric("Pullback", f"{d.pullback_score:.0f}")
        m4.metric("Late Stage", f"{d.late_stage_score:.0f}")

        st.caption(
            f"MACD {card.macd:.2f} / Signal {card.macd_signal:.2f} "
            f"({'0선 위' if card.macd_above_zero else '0선 아래'}) · "
            f"RSI {card.rsi14:.1f} (25:{'Y' if card.rsi_above_25 else 'N'} / 50:{'Y' if card.rsi_above_50 else 'N'}) · "
            f"ADX {card.adx:.1f} / MDI {card.mdi:.1f}"
        )

        if card.last_pivot_labels:
            pivots_str = "  ".join(f"{label}={price:,.0f}" for label, price in card.last_pivot_labels.items())
            st.caption(f"최근 pivot: {pivots_str}")

        if d.stop_price:
            st.caption(f"제안 Stop: {d.stop_price:,.0f}")

        if d.reasons:
            st.caption(" · ".join(d.reasons))


def _build_summary_table(cards: list[ReportCard]) -> pd.DataFrame:
    """표 형태 기본 뷰용 — 카드 전부를 한 눈에 스캔/정렬하기 위한 핵심 컬럼만 추림.
    MACD/RSI/ADX 원시값·pivot·reason codes 같은 상세 정보는 표에 넣으면 오히려
    가독성이 떨어져서 뺐다 — 행 선택 시 아래 상세 패널(_render_dashboard_card)에서 보여준다."""
    rows = []
    for c in cards:
        d = c.decision
        rows.append({
            "종목명": d.name, "코드": d.symbol, "그룹": d.friend_group or "-",
            "Action": d.action.value, "Cycle": d.cycle_state.value, "Dow": c.dow_state,
            "Reversal": d.reversal_core_score, "ADX Gate": d.adx_gate.value,
            "Pullback": d.pullback_score, "Late Stage": d.late_stage_score,
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
    "제안 Stop": st.column_config.NumberColumn(help="16장 — 최근 confirmed pivot low 기준 제안 손절가", format="%.0f"),
}


def render_dashboard() -> None:
    st.subheader("대시보드")
    _render_legend()

    # jobs/*.py는 전부 get_connection() 전에 run_migrations()를 부른다 — 여기서 빠뜨리면
    # 배치를 한 번도 안 돌린 새 배포/새 DB 파일에서 "no such table: scores_daily"로
    # 대시보드 자체가 크래시한다(실제로 이 세션에서 겪은 버그 — SCR을 먼저 띄우고
    # 나중에 CLI로 collect/decide를 처음 돌렸더니 그 사이에 대시보드가 이 예외로 죽었음).
    run_migrations()
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
    finally:
        conn.close()

    if not cards:
        st.warning(f"{selected.isoformat()} 판정 결과가 없습니다 (배치 미실행 또는 휴장일).")
        return

    cards = sort_decisions_for_report(cards)  # 21장: STOP/EXIT → ENTRY → ADD → TAKE_PROFIT_PARTIAL → READY → WAIT
    cards_by_symbol = {c.decision.symbol: c for c in cards}

    counts = Counter(c.decision.action.value for c in cards)
    summary = " · ".join(f"{action} {n}" for action, n in counts.items())
    st.caption(f"{selected.isoformat()} 기준 {len(cards)}개 종목 — {summary}")

    table = _build_summary_table(cards)
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
    if selected_rows:
        symbol = table.iloc[selected_rows[0]]["코드"]
        st.markdown("---")
        st.markdown(f"**상세 — {symbol}**")
        _render_dashboard_card(cards_by_symbol[symbol])
    else:
        st.caption("표에서 행을 클릭하면 해당 종목의 상세(MACD/RSI/ADX/pivot/근거)가 아래에 표시됩니다.")


def render_universe_management(identity) -> None:
    st.subheader("종목 관리 (절친 Universe)")

    try:
        client = get_supabase_client()
    except RuntimeError as exc:
        st.error(f"Supabase 연결 실패: {exc}")
        return

    rows = client.table("swingcycle_symbols").select("*").order("symbol").execute().data or []
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["symbol", "name", "market", "friend_group", "enabled", "note"]
    )

    if identity is None:
        st.warning("허브 인증 정보를 확인할 수 없습니다 — 읽기 전용으로 표시합니다.")

    st.caption(
        "표에서 행을 지우면 즉시 삭제되지 않고 **비활성화(enabled=false)** 됩니다. "
        "완전 삭제는 아래 '완전 삭제' 섹션에서 별도로 확인 후 진행하세요."
    )
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        disabled=identity is None,
        use_container_width=True,
        key="universe_editor",
    )

    if st.button("저장", disabled=identity is None):
        _save_universe_diff(client, df, edited, identity)

    if not df.empty:
        _render_hard_delete_section(client, df, identity)


def _save_universe_diff(client, original: pd.DataFrame, edited: pd.DataFrame, identity) -> None:
    """행 삭제는 soft-disable(enabled=false)로만 반영한다 — 완전 삭제는 별도 확인 절차(8장) 필요.

    전문가 리뷰에서 발견된 버그 수정: 이전에는 표에서 행이 사라지면 바로
    client.table(...).delete()를 호출해 즉시 하드 삭제됐다.
    """
    original_symbols = set(original["symbol"]) if not original.empty else set()
    edited_symbols = set(edited["symbol"].dropna())
    removed_from_grid = original_symbols - edited_symbols

    upsert_rows = []
    for _, row in edited.iterrows():
        if not row.get("symbol"):
            continue
        upsert_rows.append({
            "symbol": row["symbol"],
            "name": row.get("name") or "",
            "market": row.get("market") or None,
            "friend_group": row.get("friend_group") or None,
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
            "enabled": False,
            "note": original_row.get("note") or None,
            "updated_by": identity.email,
        })

    if upsert_rows:
        client.table("swingcycle_symbols").upsert(upsert_rows).execute()

    st.success(f"저장 완료: upsert {len(upsert_rows)}건 (표에서 지운 {len(removed_from_grid)}건은 비활성화 처리)")
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
