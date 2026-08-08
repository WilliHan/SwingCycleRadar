#!/usr/bin/env python3
"""절친종목 초기 시드 — 최초 1회 전용.

설계: docs/SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md 7.2

이후 종목 추가/삭제/그룹 변경은 Streamlit 종목 관리 탭(Supabase 직접 반영)으로 한다.
이 스크립트를 --force 없이 재실행하면, 이미 Supabase에 존재하는 row는 덮어쓰지 않는다
(CRUD로 이미 바뀐 내용을 시드가 되돌리지 않도록 하는 가드).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import typer
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swingcycle.data.supabase_client import get_supabase_client  # noqa: E402
from swingcycle.settings import PROJECT_ROOT  # noqa: E402

app = typer.Typer()


@app.command()
def main(force: bool = typer.Option(False, help="이미 Supabase에 있는 row도 덮어쓴다")) -> None:
    csv_path = PROJECT_ROOT / "docs" / "절친종목.csv"
    yaml_path = PROJECT_ROOT / "config" / "friend_universe.yml"

    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype={"종목코드": str})
    df["종목코드"] = df["종목코드"].str.zfill(6)

    with open(yaml_path, encoding="utf-8") as f:
        universe_seed = yaml.safe_load(f)["symbols"]
    group_map = {row["symbol"]: row["group"] for row in universe_seed}

    csv_symbols = set(df["종목코드"])
    yaml_symbols = set(group_map)
    if csv_symbols != yaml_symbols:
        raise typer.BadParameter(
            f"CSV/YAML 종목코드 불일치: CSV-only={csv_symbols - yaml_symbols}, "
            f"YAML-only={yaml_symbols - csv_symbols}"
        )

    client = get_supabase_client()
    existing = {row["symbol"] for row in client.table("swingcycle_symbols").select("symbol").execute().data or []}

    rows = []
    skipped = 0
    for _, row in df.iterrows():
        symbol = row["종목코드"]
        if symbol in existing and not force:
            skipped += 1
            continue
        rows.append({
            "symbol": symbol,
            "name": row["종목명"],
            "friend_group": group_map[symbol],
            "enabled": True,
        })

    if rows:
        client.table("swingcycle_symbols").upsert(rows).execute()
    typer.echo(f"시드 완료: upsert {len(rows)}건, 건너뜀(이미 존재) {skipped}건")


if __name__ == "__main__":
    app()
