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


def render_dashboard() -> None:
    st.subheader("대시보드")

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

    counts = Counter(c.decision.action.value for c in cards)
    summary = " · ".join(f"{action} {n}" for action, n in counts.items())
    st.caption(f"{selected.isoformat()} 기준 {len(cards)}개 종목 — {summary}")

    for card in cards:
        _render_dashboard_card(card)


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
