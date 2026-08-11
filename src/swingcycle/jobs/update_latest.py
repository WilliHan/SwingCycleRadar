"""collect-parquet + decide를 "지금 로컬에 있는 최신 판정일" 기준으로 한 번에 실행.

webapp/app.py의 "저장+업데이트"/엑셀 업로드 "반영"이 쓰는 핵심 로직. Oracle 자신이
처리할 때(전체 시장 parquet 보유)와, 개발 환경이 SSH로 Oracle에 위임할 때(cli.py의
`update-latest` 커맨드를 통해) 둘 다 이 함수 하나를 쓴다 — 로직을 두 곳에 두지 않는다.

trade_date를 "오늘"이 아니라 로컬에 이미 있는 최신 판정일로 잡는 이유: 대시보드가 보는
날짜와 어긋나지 않게 하기 위해서다. 오늘 날짜를 쓰면 당일 parquet이 아직 안 채워진
시간대(장중/새벽)에는 새 종목까지 skipped_no_data로 빠질 수 있다(2026-08-10 새벽에
실제로 겪은 문제, run_daily_batch_parquet.sh 주석 참고).
"""
from __future__ import annotations

from datetime import date

from ..repositories import decision_repo
from ..repositories.db import get_connection, run_migrations
from ..settings import settings
from .daily_collect_from_parquet import run_collect_from_parquet
from .daily_decide import run_decide


def run_update_latest() -> tuple[date, dict, dict]:
    run_migrations()
    conn = get_connection()
    try:
        trade_date_ = decision_repo.get_latest_trade_date(conn) or date.today()
    finally:
        conn.close()

    collect_result = run_collect_from_parquet(trade_date_, str(settings.mfts_parquet_dir_resolved))
    decide_result = run_decide(trade_date_)
    return trade_date_, collect_result, decide_result
