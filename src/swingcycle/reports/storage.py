"""리포트 파일 저장 규약. 설계서엔 경로/보존 정책이 없어 이번에 확정한다.

**경로**: `data/exports/{trade_date}/` — Sprint 1 스캐폴딩 때 이미
`.gitignore`(`data/exports/*` + `!data/exports/.gitkeep`)로 이 위치가 산출물
디렉토리로 예약돼 있었다(코드로는 아직 아무것도 안 쓰고 있었음). 날짜별 하위
디렉토리로 나누는 이유: 하루 재실행(force) 시 그날 파일만 덮어쓰면 되고,
보존 정책(retention)도 디렉토리 단위 삭제로 간단해진다.

**형식**: `report.html`(21장 카드 뷰) + `report.csv` + `report.json`(둘 다 CSV/JSON
export, Sprint 6) 세 개를 항상 같이 저장한다 — 어떤 소비자(사람이 HTML 보기 vs
스프레드시트/다른 프로그램이 CSV/JSON 읽기)든 같은 디렉토리 하나만 보면 된다.

**보존**: 기본 90일(config/app.yml `reports.retention_days`) — 그보다 오래된
날짜 디렉토리는 `cleanup_old_reports()`가 통째로 삭제한다. 이 함수는 daily_report_job
실행 끝에 매번 호출돼도 안전하다(이미 지워진 디렉토리를 다시 지우려 하지 않음 —
glob으로 실제 존재하는 디렉토리만 순회하므로 idempotent).
"""
from __future__ import annotations

import shutil
from datetime import date, timedelta
from pathlib import Path

from ..reports.daily_report import ReportCard, export_csv, export_json, render_html_report
from ..settings import PROJECT_ROOT

DEFAULT_EXPORTS_DIR = PROJECT_ROOT / "data" / "exports"


def report_dir(trade_date: date, base_dir: Path | None = None) -> Path:
    base = base_dir or DEFAULT_EXPORTS_DIR
    return base / trade_date.isoformat()


def save_report(cards: list[ReportCard], trade_date: date, base_dir: Path | None = None) -> dict[str, Path]:
    """report.html/csv/json을 `data/exports/{trade_date}/`에 쓴다. 같은 날짜를 다시
    호출하면 파일을 덮어쓸 뿐 새 디렉토리/중복 파일을 만들지 않는다(idempotent)."""
    out_dir = report_dir(trade_date, base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    generated_at = trade_date.isoformat()
    paths = {
        "html": out_dir / "report.html",
        "csv": out_dir / "report.csv",
        "json": out_dir / "report.json",
    }
    paths["html"].write_text(render_html_report(cards, generated_at), encoding="utf-8")
    paths["csv"].write_text(export_csv(cards), encoding="utf-8")
    paths["json"].write_text(export_json(cards), encoding="utf-8")
    return paths


def cleanup_old_reports(base_dir: Path | None = None, retention_days: int = 90, today: date | None = None) -> list[Path]:
    """`retention_days`보다 오래된 날짜 디렉토리를 통째로 삭제한다.
    디렉토리명이 YYYY-MM-DD 형식이 아닌 것(사람이 실수로 만든 파일 등)은 건드리지 않는다."""
    base = base_dir or DEFAULT_EXPORTS_DIR
    if not base.exists():
        return []
    cutoff = (today or date.today()) - timedelta(days=retention_days)

    removed: list[Path] = []
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        try:
            entry_date = date.fromisoformat(entry.name)
        except ValueError:
            continue
        if entry_date < cutoff:
            shutil.rmtree(entry)
            removed.append(entry)
    return removed
