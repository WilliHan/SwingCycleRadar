"""MFTS의 @RUN/cache/parquet/{symbol}.parquet 을 daily_bars로 1회성 임포트.

**현재는 수동/1회성 도구다** — Oracle 서버로부터의 주기적 rsync/scp pull, 액면분할/배당
조정 검증은 의도적으로 아직 안 한다(사용자 지시: 기본 기능 동작 확인 먼저, 그 다음
자동화). 이 스크립트는 이미 로컬에 scp로 내려받은 parquet 파일들이 있는 디렉토리를
읽어서 daily_bars에 upsert만 한다 — 원격 접속/자동 pull은 하지 않는다.

parquet 스키마(MFTS 쪽): index="날짜", 컬럼 open/high/low/close/volume/amount_krw.
daily_bars 매핑: amount_krw -> trade_value, market_cap은 이 소스에 없어 NULL.

사용법:
    python scripts/import_mfts_parquet.py <parquet_dir>
    (파일명 자체가 종목코드다: 005930.parquet -> symbol="005930")
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swingcycle.domain.enums import DataSource  # noqa: E402
from swingcycle.repositories import daily_bar_repo  # noqa: E402
from swingcycle.repositories.db import get_connection, run_migrations  # noqa: E402


def _load_symbol_parquet(path: Path) -> pd.DataFrame:
    symbol = path.stem
    raw = pd.read_parquet(path)
    raw = raw.reset_index()
    date_col = raw.columns[0]  # 인덱스가 "날짜"였던 컬럼 — reset_index 후 첫 컬럼
    raw = raw.rename(columns={date_col: "trade_date", "amount_krw": "trade_value"})
    raw["trade_date"] = pd.to_datetime(raw["trade_date"]).dt.strftime("%Y-%m-%d")
    raw["symbol"] = symbol
    raw["market_cap"] = None
    raw["source"] = DataSource.MFTS_PARQUET.value
    raw["source_raw_hash"] = None
    return raw[[
        "trade_date", "symbol", "open", "high", "low", "close", "volume",
        "trade_value", "market_cap", "source", "source_raw_hash",
    ]]


def main(parquet_dir: str) -> None:
    run_migrations()
    conn = get_connection()
    try:
        files = sorted(Path(parquet_dir).glob("*.parquet"))
        if not files:
            print(f"parquet 파일 없음: {parquet_dir}")
            return

        total_rows = 0
        for path in files:
            df = _load_symbol_parquet(path)
            n = daily_bar_repo.upsert_daily_bars(conn, df)
            conn.commit()
            total_rows += n
            print(f"{path.stem}: {n}행 (기간 {df['trade_date'].min()} ~ {df['trade_date'].max()})")

        print(f"완료 — {len(files)}종목, 총 {total_rows}행 upsert")
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용법: python scripts/import_mfts_parquet.py <parquet_dir>")
        sys.exit(1)
    main(sys.argv[1])
