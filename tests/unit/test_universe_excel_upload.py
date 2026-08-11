"""webapp/app.py의 _parse_universe_excel 단위 테스트.

실사용자 개인 파일(docs/절친종목_260811.xlsx)에 의존하지 않도록 합성 픽스처를 만든다
— 실제 파일 구조(NO/종목명/종목코드/메모 + 그날의 시세 스냅샷 컬럼들)를 그대로 흉내낸다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "webapp"))

from app import _parse_universe_excel  # noqa: E402


def _write_excel(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "universe.xlsx"
    pd.DataFrame(rows).to_excel(path, index=False)
    return path


def test_parses_required_columns_and_ignores_price_snapshot_columns(tmp_path):
    path = _write_excel(tmp_path, [
        {"NO": 1, "종목명": "삼성전자", "종목코드": 5930, "메모": "#260101 메모", "현재가": 226000, "거래량": 1000},
        {"NO": 2, "종목명": "SK하이닉스", "종목코드": 660, "메모": None, "현재가": 1388000, "거래량": 2000},
    ])
    with open(path, "rb") as f:
        parsed, skipped = _parse_universe_excel(f)

    assert skipped == []
    assert list(parsed.columns) == ["symbol", "name", "note", "sort_order"]
    assert parsed.loc[0, "symbol"] == "005930"  # zero-pad 6자리
    assert parsed.loc[1, "symbol"] == "000660"
    assert parsed.loc[0, "sort_order"] == 1
    assert parsed.loc[0, "note"] == "#260101 메모"
    assert parsed.loc[1, "note"] is None  # 메모 NaN -> None


def test_rows_without_symbol_code_are_skipped(tmp_path):
    path = _write_excel(tmp_path, [
        {"NO": 1, "종목명": "삼성전자", "종목코드": 5930, "메모": None},
        {"NO": 2, "종목명": "RFHIC", "종목코드": None, "메모": None},  # 코드 미확정
    ])
    with open(path, "rb") as f:
        parsed, skipped = _parse_universe_excel(f)

    assert len(parsed) == 1
    assert skipped == ["RFHIC"]


def test_missing_required_column_raises(tmp_path):
    path = _write_excel(tmp_path, [{"종목명": "삼성전자", "종목코드": 5930}])  # NO 컬럼 없음
    with open(path, "rb") as f:
        with pytest.raises(ValueError, match="필수 컬럼"):
            _parse_universe_excel(f)
