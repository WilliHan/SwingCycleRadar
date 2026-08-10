from datetime import date

import pytest

from swingcycle.data.supabase_daily_sync import push_daily_snapshot, reconcile_recent_history
from swingcycle.repositories.db import get_connection, run_migrations
from swingcycle.settings import settings


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    run_migrations()
    c = get_connection()
    yield c
    c.close()


class _FakeQuery:
    """client.table(x).select(...).gte(...).execute() / .upsert(...).execute() 흉내."""

    def __init__(self, store: dict, table: str):
        self._store = store
        self._table = table
        self._filter_col = None
        self._filter_val = None
        self._upsert_rows = None

    def select(self, *_args, **_kwargs):
        return self

    def gte(self, col, val):
        self._filter_col, self._filter_val = col, val
        return self

    def upsert(self, rows):
        self._upsert_rows = rows
        return self

    def execute(self):
        if self._upsert_rows is not None:
            self._store.setdefault(self._table, []).extend(self._upsert_rows)
            return _FakeResponse(self._upsert_rows)
        rows = self._store.get(self._table, [])
        if self._filter_col:
            rows = [r for r in rows if r.get(self._filter_col) is not None and r[self._filter_col] >= self._filter_val]
        return _FakeResponse(rows)


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeSupabaseClient:
    """테이블별 upsert된 행을 그대로 기억해 select().gte()로 되돌려주는 인메모리 fake."""

    def __init__(self):
        self.store: dict[str, list[dict]] = {}

    def table(self, name):
        return _FakeQuery(self.store, name)


def _insert_indicator_row(conn, trade_date_: str, symbol: str, rsi14: float) -> None:
    conn.execute(
        "INSERT INTO indicators_daily (trade_date, symbol, rsi14) VALUES (?, ?, ?)",
        (trade_date_, symbol, rsi14),
    )
    conn.commit()


def _insert_scores_row(conn, trade_date_: str, symbol: str) -> None:
    conn.execute(
        "INSERT INTO scores_daily (trade_date, symbol, reasons_json) VALUES (?, ?, '[]')",
        (trade_date_, symbol),
    )
    conn.commit()


def test_push_daily_snapshot_upserts_each_table_once(conn):
    _insert_indicator_row(conn, "2026-08-07", "005930", 55.0)
    _insert_scores_row(conn, "2026-08-07", "005930")
    client = FakeSupabaseClient()

    counts = push_daily_snapshot(client, date(2026, 8, 7), conn)

    assert counts["swingcycle_indicators_daily"] == 1
    assert counts["swingcycle_scores_daily"] == 1
    assert counts["swingcycle_cycle_daily"] == 0  # 해당 날짜에 로컬 행이 없으면 upsert 자체를 안 함
    assert client.store["swingcycle_indicators_daily"][0]["symbol"] == "005930"
    assert client.store["swingcycle_indicators_daily"][0]["rsi14"] == 55.0


def test_reconcile_fills_missing_date_without_touching_existing(conn):
    """로컬엔 8/7만 있고 Supabase엔 8/6+8/7이 있는 상황 — 8/6만 채워지고 8/7은 그대로."""
    _insert_indicator_row(conn, "2026-08-07", "005930", 55.0)

    client = FakeSupabaseClient()
    client.store["swingcycle_indicators_daily"] = [
        {"trade_date": "2026-08-06", "symbol": "005930", "rsi14": 40.0, "sma5": None, "sma20": None,
         "sma60": None, "sma120": None, "sma240": None, "ema12": None, "ema26": None, "macd": None,
         "macd_signal": None, "macd_hist": None, "rsi_signal": None, "pdi14": None, "mdi14": None,
         "adx14": None, "vo10_20": None, "ma5_distance_pct": None},
        # Supabase에도 8/7이 이미 있지만(예: 다른 환경이 먼저 push) 값이 다르다(90.0) —
        # 로컬에 이미 존재하는 날짜라 절대 덮어써지면 안 된다.
        {"trade_date": "2026-08-07", "symbol": "005930", "rsi14": 90.0, "sma5": None, "sma20": None,
         "sma60": None, "sma120": None, "sma240": None, "ema12": None, "ema26": None, "macd": None,
         "macd_signal": None, "macd_hist": None, "rsi_signal": None, "pdi14": None, "mdi14": None,
         "adx14": None, "vo10_20": None, "ma5_distance_pct": None},
    ]

    counts = reconcile_recent_history(conn, client, lookback_days=15)

    assert counts["swingcycle_indicators_daily"] == 1  # 8/6 하나만 새로 채움
    row_06 = conn.execute("SELECT rsi14 FROM indicators_daily WHERE trade_date='2026-08-06'").fetchone()
    assert row_06["rsi14"] == 40.0
    row_07 = conn.execute("SELECT rsi14 FROM indicators_daily WHERE trade_date='2026-08-07'").fetchone()
    assert row_07["rsi14"] == 55.0  # 로컬 값 유지, Supabase의 90.0으로 덮어써지지 않음


def test_reconcile_no_remote_rows_is_noop(conn):
    client = FakeSupabaseClient()

    counts = reconcile_recent_history(conn, client, lookback_days=15)

    assert all(v == 0 for v in counts.values())
