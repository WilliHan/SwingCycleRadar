"""jobs/daily_collect_from_parquet.py 통합 테스트 — MFTS parquet 캐시를 daily_bars로
가져오는 대안 1단계(daily_collect.py의 KRX 직접수집 대신 로컬 parquet을 읽는 경로)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from swingcycle.jobs.daily_collect_from_parquet import run_collect_from_parquet
from swingcycle.repositories.db import get_connection, run_migrations
from swingcycle.settings import settings


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    run_migrations()
    c = get_connection()
    yield c
    c.close()


def _seed_symbol(conn, symbol: str) -> None:
    conn.execute(
        "INSERT INTO symbols (symbol, name, market, sector_group, friend_group, enabled, "
        "deleted_upstream, note, created_at, updated_at) "
        "VALUES (?, ?, 'KOSPI', NULL, 'semiconductor', 1, 0, NULL, '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
        (symbol, f"테스트종목{symbol}"),
    )
    conn.commit()


def _write_parquet(parquet_dir, symbol: str, dates: list[str]) -> None:
    df = pd.DataFrame({
        "open": [100.0] * len(dates), "high": [105.0] * len(dates),
        "low": [95.0] * len(dates), "close": [102.0] * len(dates),
        "volume": [1000] * len(dates), "amount_krw": [100000] * len(dates),
    }, index=pd.to_datetime(dates))
    df.index.name = "날짜"
    df.to_parquet(parquet_dir / f"{symbol}.parquet")


# 2026-08-06(목)은 실제 평일이라 ensure_trading_day를 통과한다.
_TRADE_DATE = date(2026, 8, 6)


def test_imports_only_universe_symbols(conn, tmp_path, monkeypatch):
    """MFTS 캐시엔 관계없는 종목도 섞여 있을 수 있다 — swingcycle 유니버스에 있는
    종목의 parquet만 골라 읽어야 한다(전체를 다 읽으면 낭비)."""
    monkeypatch.setattr(
        "swingcycle.jobs.daily_collect_from_parquet.fetch_all_symbols",
        lambda: (_ for _ in ()).throw(RuntimeError("no supabase in test")),
    )
    _seed_symbol(conn, "005930")
    parquet_dir = tmp_path / "parquet_cache"
    parquet_dir.mkdir()
    _write_parquet(parquet_dir, "005930", [_TRADE_DATE.isoformat()])
    _write_parquet(parquet_dir, "999999", [_TRADE_DATE.isoformat()])  # 유니버스 밖 종목

    result = run_collect_from_parquet(_TRADE_DATE, str(parquet_dir))

    assert result["status"] == "OK"
    assert result["rows"] == 1
    rows = conn.execute("SELECT symbol FROM daily_bars").fetchall()
    assert [r["symbol"] for r in rows] == ["005930"]


def test_missing_parquet_file_is_reported_not_fatal(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "swingcycle.jobs.daily_collect_from_parquet.fetch_all_symbols",
        lambda: (_ for _ in ()).throw(RuntimeError("no supabase in test")),
    )
    _seed_symbol(conn, "005930")
    parquet_dir = tmp_path / "parquet_cache"
    parquet_dir.mkdir()
    # 005930.parquet을 아예 안 만든다 — MFTS 쪽에서 해당 종목이 아직 없는 상황.

    result = run_collect_from_parquet(_TRADE_DATE, str(parquet_dir))

    assert result["status"] == "OK"
    assert result["rows"] == 0
    assert result["missing_parquet"] == ["005930"]


def test_parquet_without_trade_value_column_does_not_crash(conn, tmp_path, monkeypatch):
    """실제 MFTS 캐시 파일 중 일부는 amount_krw(거래대금) 컬럼 자체가 없다(실사용에서
    발견) — trade_value를 NULL로 채우고 계속 진행해야지, KeyError로 collect 전체가
    죽으면 안 된다."""
    monkeypatch.setattr(
        "swingcycle.jobs.daily_collect_from_parquet.fetch_all_symbols",
        lambda: (_ for _ in ()).throw(RuntimeError("no supabase in test")),
    )
    _seed_symbol(conn, "005930")
    parquet_dir = tmp_path / "parquet_cache"
    parquet_dir.mkdir()
    df = pd.DataFrame({
        "open": [100.0], "high": [105.0], "low": [95.0], "close": [102.0], "volume": [1000],
    }, index=pd.to_datetime([_TRADE_DATE.isoformat()]))
    df.index.name = "날짜"
    df.to_parquet(parquet_dir / "005930.parquet")

    result = run_collect_from_parquet(_TRADE_DATE, str(parquet_dir))

    assert result["status"] == "OK"
    assert result["rows"] == 1
    row = conn.execute("SELECT trade_value FROM daily_bars WHERE symbol='005930'").fetchone()
    assert row["trade_value"] is None


def test_stale_data_flagged_when_parquet_not_updated_to_today(conn, tmp_path, monkeypatch):
    """MFTS 새벽 배치가 지연/장애로 아직 오늘자를 못 채운 경우 — 있는 데이터까진
    반영하되 stale로 표시해서 운영자가 알아챌 수 있게 한다."""
    monkeypatch.setattr(
        "swingcycle.jobs.daily_collect_from_parquet.fetch_all_symbols",
        lambda: (_ for _ in ()).throw(RuntimeError("no supabase in test")),
    )
    _seed_symbol(conn, "005930")
    parquet_dir = tmp_path / "parquet_cache"
    parquet_dir.mkdir()
    _write_parquet(parquet_dir, "005930", ["2026-08-05"])  # 하루 전날까지만 있음

    result = run_collect_from_parquet(_TRADE_DATE, str(parquet_dir))

    assert result["status"] == "OK"
    assert result["rows"] == 1
    assert result["stale"] == ["005930"]
