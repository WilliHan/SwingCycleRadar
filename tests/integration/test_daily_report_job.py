"""jobs/daily_report_job.py 통합 테스트 — decide가 DB에 남긴 결과를 실제로 리포트 파일로
조립하는지 확인한다(20장 3단계, decide 다음 단계)."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from swingcycle.jobs.daily_decide import run_decide
from swingcycle.jobs.daily_report_job import run_report
from swingcycle.repositories import daily_bar_repo
from swingcycle.repositories.db import get_connection, run_migrations
from swingcycle.settings import settings


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    run_migrations()
    c = get_connection()
    yield c
    c.close()


def _seed_symbol_and_bars(conn, symbol: str, n_days: int) -> date:
    conn.execute(
        "INSERT INTO symbols (symbol, name, market, sector_group, friend_group, enabled, deleted_upstream, note, created_at, updated_at) "
        "VALUES (?, ?, 'KOSPI', NULL, 'semiconductor', 1, 0, NULL, '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
        (symbol, f"테스트종목{symbol}"),
    )
    conn.commit()
    rng = np.random.default_rng(11)
    # cleanup_old_reports가 실제 오늘(date.today()) 기준으로 보존기간을 계산하므로,
    # 시드 데이터의 마지막 날짜가 과거로 너무 멀면(기본 90일 초과) 방금 쓴 리포트가
    # 곧바로 정리 대상이 된다 — 오늘 근처로 데이터를 잡는다.
    dates = []
    d = date.today() - timedelta(days=n_days * 2)
    while len(dates) < n_days:
        if d.weekday() < 5 and d < date.today():
            dates.append(d)
        d += timedelta(days=1)
    close = 100 + np.cumsum(rng.normal(0.2, 1.0, n_days))
    high = close + rng.uniform(0.5, 1.5, n_days)
    low = close - rng.uniform(0.5, 1.5, n_days)
    df = pd.DataFrame({
        "trade_date": [d.isoformat() for d in dates], "symbol": [symbol] * n_days,
        "open": close, "high": high, "low": low, "close": close,
        "volume": rng.uniform(1000, 5000, n_days),
        "trade_value": [None] * n_days, "market_cap": [None] * n_days,
        "source": ["krx_direct"] * n_days, "source_raw_hash": [None] * n_days,
    })
    daily_bar_repo.upsert_daily_bars(conn, df)
    return dates[-1]


def test_report_reads_decide_output_and_writes_files(conn, tmp_path):
    last_date = _seed_symbol_and_bars(conn, "005930", n_days=60)
    run_decide(last_date)

    report_out = tmp_path / "exports"
    result = run_report(last_date, base_dir=report_out)

    assert result["status"] == "OK"
    assert result["card_count"] == 1
    html_path = report_out / last_date.isoformat() / "report.html"
    assert html_path.exists()
    assert "005930" in html_path.read_text(encoding="utf-8")


def test_report_before_decide_has_no_decisions(conn, tmp_path):
    last_date = _seed_symbol_and_bars(conn, "005930", n_days=60)
    result = run_report(last_date, base_dir=tmp_path / "exports")
    assert result["status"] == "NO_DECISIONS"


def test_report_rerun_does_not_duplicate_cards(conn, tmp_path):
    last_date = _seed_symbol_and_bars(conn, "005930", n_days=60)
    run_decide(last_date)
    report_out = tmp_path / "exports"

    run_report(last_date, base_dir=report_out)
    result = run_report(last_date, base_dir=report_out)  # 재실행

    assert result["card_count"] == 1
    files = list((report_out / last_date.isoformat()).iterdir())
    assert len(files) == 3  # html/csv/json, 늘지 않음
