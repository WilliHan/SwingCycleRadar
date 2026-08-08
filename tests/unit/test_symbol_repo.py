import os

import pytest

from swingcycle.repositories import symbol_repo
from swingcycle.repositories.db import get_connection, run_migrations
from swingcycle.settings import settings


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    run_migrations()
    c = get_connection()
    yield c
    c.close()


def test_sync_from_supabase_preserves_local_market(conn):
    symbol_repo.sync_from_supabase(conn, [{"symbol": "005930", "name": "삼성전자", "friend_group": "semiconductor", "enabled": True}])
    symbol_repo.backfill_market_if_missing(conn, "005930", "KOSPI")

    symbol_repo.sync_from_supabase(conn, [{"symbol": "005930", "name": "삼성전자", "friend_group": "semiconductor", "enabled": True}])

    row = conn.execute("SELECT market FROM symbols WHERE symbol='005930'").fetchone()
    assert row["market"] == "KOSPI"


def test_sync_from_supabase_hard_delete_is_soft_locally(conn):
    symbol_repo.sync_from_supabase(conn, [{"symbol": "000660", "name": "SK하이닉스", "friend_group": "semiconductor", "enabled": True}])
    symbol_repo.sync_from_supabase(conn, [])  # 000660이 Supabase에서 사라짐 (하드 삭제 시뮬레이션)

    row = conn.execute("SELECT enabled, deleted_upstream FROM symbols WHERE symbol='000660'").fetchone()
    assert row is not None, "로컬 row가 하드 삭제되면 안 된다"
    assert row["enabled"] == 0
    assert row["deleted_upstream"] == 1


def test_backfill_market_does_not_override_manual_value(conn):
    symbol_repo.sync_from_supabase(conn, [{"symbol": "005930", "name": "삼성전자", "friend_group": "semiconductor", "enabled": True}])
    symbol_repo.backfill_market_if_missing(conn, "005930", "KOSPI")
    symbol_repo.backfill_market_if_missing(conn, "005930", "KOSDAQ")  # 이미 값 있음 -> 무시돼야 함

    row = conn.execute("SELECT market FROM symbols WHERE symbol='005930'").fetchone()
    assert row["market"] == "KOSPI"
