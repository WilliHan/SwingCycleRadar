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


def test_collectable_symbols_keeps_disabled_symbol_with_active_plan(conn):
    """전문가 리뷰 회귀 테스트: enabled=false여도 ACTIVE trade_plan이 있으면 수집 대상 유지."""
    import uuid
    from datetime import datetime

    symbol_repo.sync_from_supabase(conn, [
        {"symbol": "005930", "name": "삼성전자", "friend_group": "semiconductor", "enabled": True},
        {"symbol": "000660", "name": "SK하이닉스", "friend_group": "semiconductor", "enabled": True},
    ])
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO trade_plans (plan_id, symbol, created_date, entry_type, stop_price, status) "
        "VALUES (?, '005930', ?, 'REVERSAL', 100.0, 'ACTIVE')",
        (str(uuid.uuid4()), now),
    )
    conn.commit()

    # 005930을 비활성화(신규 진입 금지) — 하지만 ACTIVE 플랜이 있으므로 계속 수집돼야 한다
    symbol_repo.sync_from_supabase(conn, [
        {"symbol": "005930", "name": "삼성전자", "friend_group": "semiconductor", "enabled": False},
        {"symbol": "000660", "name": "SK하이닉스", "friend_group": "semiconductor", "enabled": True},
    ])

    collectable = set(symbol_repo.collectable_symbols(conn))
    assert collectable == {"005930", "000660"}, "ACTIVE 플랜 보유 종목은 비활성화돼도 수집 대상에서 빠지면 안 된다"
    assert set(symbol_repo.active_symbols(conn)) == {"000660"}, "active_symbols는 여전히 enabled=1만 반환해야 한다"


def test_collectable_symbols_survives_missing_symbols_row(conn):
    """전문가 리뷰 2차 지적 회귀 테스트: symbols row 자체가 없어도(비정상 복구 상황)
    trade_plans에 ACTIVE가 있으면 수집 대상에 들어와야 한다."""
    import uuid
    from datetime import datetime

    now = datetime.now().isoformat()
    # symbols에는 아예 없는 종목코드로 ACTIVE trade_plan만 존재하는 비정상 상태를 재현
    conn.execute(
        "INSERT INTO trade_plans (plan_id, symbol, created_date, entry_type, stop_price, status) "
        "VALUES (?, '999999', ?, 'REVERSAL', 100.0, 'ACTIVE')",
        (str(uuid.uuid4()), now),
    )
    conn.commit()

    assert conn.execute("SELECT 1 FROM symbols WHERE symbol='999999'").fetchone() is None

    assert "999999" in symbol_repo.collectable_symbols(conn)


def test_backfill_market_does_not_override_manual_value(conn):
    symbol_repo.sync_from_supabase(conn, [{"symbol": "005930", "name": "삼성전자", "friend_group": "semiconductor", "enabled": True}])
    symbol_repo.backfill_market_if_missing(conn, "005930", "KOSPI")
    symbol_repo.backfill_market_if_missing(conn, "005930", "KOSDAQ")  # 이미 값 있음 -> 무시돼야 함

    row = conn.execute("SELECT market FROM symbols WHERE symbol='005930'").fetchone()
    assert row["market"] == "KOSPI"


def test_sync_from_supabase_pulls_market_when_local_missing(conn):
    """KRX 직접수집이 없는 배포(예: parquet 전용 Oracle)에서도 Supabase에 이미 채워진
    market을 로컬 캐시로 끌어와야 한다."""
    symbol_repo.sync_from_supabase(conn, [
        {"symbol": "005930", "name": "삼성전자", "friend_group": "semiconductor", "enabled": True, "market": "KOSPI"},
    ])

    row = conn.execute("SELECT market FROM symbols WHERE symbol='005930'").fetchone()
    assert row["market"] == "KOSPI"


def test_sync_from_supabase_local_market_wins_over_supabase(conn):
    symbol_repo.sync_from_supabase(conn, [{"symbol": "005930", "name": "삼성전자", "friend_group": "semiconductor", "enabled": True}])
    symbol_repo.backfill_market_if_missing(conn, "005930", "KOSPI")

    # Supabase 쪽 값이 다르더라도(오탈자 등) 로컬이 이미 확정한 값을 덮어쓰지 않는다
    symbol_repo.sync_from_supabase(conn, [
        {"symbol": "005930", "name": "삼성전자", "friend_group": "semiconductor", "enabled": True, "market": "KOSDAQ"},
    ])

    row = conn.execute("SELECT market FROM symbols WHERE symbol='005930'").fetchone()
    assert row["market"] == "KOSPI"


def test_select_new_market_backfills_skips_when_supabase_already_has_value():
    krx_rows = [{"symbol": "005930", "market": "KOSPI"}]
    updates = symbol_repo.select_new_market_backfills(krx_rows, {"005930": "KOSPI"})
    assert updates == []


def test_select_new_market_backfills_includes_when_supabase_missing():
    krx_rows = [
        {"symbol": "005930", "market": "KOSPI"},
        {"symbol": "005930", "market": "KOSPI"},  # 같은 종목 중복 row(여러 날짜 등) -> 한 번만
        {"symbol": "000660", "market": None},  # market 미상 -> 대상에서 제외
    ]
    updates = symbol_repo.select_new_market_backfills(krx_rows, {"005930": None, "000660": None})
    assert updates == [{"symbol": "005930", "market": "KOSPI"}]
