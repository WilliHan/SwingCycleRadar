"""SwingCycle Radar Streamlit 앱 골격.

설계: docs/SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md 3장(런타임 결정), 8장(종목 관리), 9장(UI)

Hub 게이트만으로 인증(MFTS 패턴, 4.3) — 앱 내부 로그인 폼 없음.
단, 종목 CRUD의 updated_by 기록을 위해 신원 확인 브리지(4.4)만 별도로 둔다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.hub_bridge import resolve_hub_identity  # noqa: E402
from swingcycle.data.supabase_client import get_supabase_client  # noqa: E402

st.set_page_config(page_title="SwingCycle Radar", page_icon="🧭", layout="wide")


def render_dashboard() -> None:
    st.subheader("대시보드")
    st.info(
        "일일 Decision Engine(scores_daily) 연동 예정 — 원 설계서 21장 카드 정렬"
        "(STOP/EXIT → ENTRY → ADD → TAKE_PROFIT → READY → WAIT). "
        "Sprint 4(Cycle/Scoring) 완료 후 이 탭에 실제 데이터를 연결한다."
    )


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

    edited = st.data_editor(
        df,
        num_rows="dynamic",
        disabled=identity is None,
        use_container_width=True,
        key="universe_editor",
    )

    if st.button("저장", disabled=identity is None):
        _save_universe_diff(client, df, edited, identity)


def _save_universe_diff(client, original: pd.DataFrame, edited: pd.DataFrame, identity) -> None:
    original_symbols = set(original["symbol"]) if not original.empty else set()
    edited_symbols = set(edited["symbol"].dropna())

    deleted = original_symbols - edited_symbols
    for symbol in deleted:
        client.table("swingcycle_symbols").delete().eq("symbol", symbol).execute()

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
    if upsert_rows:
        client.table("swingcycle_symbols").upsert(upsert_rows).execute()

    st.success(f"저장 완료: upsert {len(upsert_rows)}건, 삭제 {len(deleted)}건")
    st.rerun()


def render_backtest_placeholder() -> None:
    st.subheader("백테스트/검증")
    st.info("원 설계서 22장 A/B/C 비교 결과 열람(읽기 전용) — Sprint 7 완료 후 연동 예정.")


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
