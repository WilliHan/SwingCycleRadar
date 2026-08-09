import logging
from datetime import date, datetime

import typer

from .jobs.daily_collect import run_collect
from .jobs.daily_decide import run_decide
from .jobs.daily_report_job import run_report
from .settings import settings

# 각 jobs/*.py는 logging.getLogger(...)만 만들고 basicConfig는 안 부른다 — 여기(실제
# 프로세스 진입점)에서 한 번만 설정해야 한다. 안 하면 root logger 유효 레벨이 기본
# WARNING으로 남아 logger.info()가 전부 조용히 씹힌다(MFGR hub_verify에서 실제로
# 겪은 문제와 동일 패턴 — 2026-07-09 세션에서 발견/수정된 바 있음).
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = typer.Typer(help="SwingCycle Radar CLI")


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


@app.command()
def collect(date_: str = typer.Option(..., "--date", help="YYYY-MM-DD")) -> None:
    """설계서 20.1 1단계: KRX/pykrx 수집."""
    result = run_collect(_parse_date(date_))
    typer.echo(result)


@app.command()
def decide(
    date_: str = typer.Option(..., "--date", help="YYYY-MM-DD"),
    force: bool = typer.Option(False, "--force", help="이미 처리된 (날짜,종목)도 재처리"),
) -> None:
    """설계서 17장/20장 2단계: DecisionEngine 실행(collect 다음 단계)."""
    result = run_decide(_parse_date(date_), force=force)
    typer.echo(result)


@app.command()
def report(date_: str = typer.Option(..., "--date", help="YYYY-MM-DD")) -> None:
    """설계서 21장/20장 3단계: data/exports/{date}/에 html/csv/json 리포트 저장(decide 다음 단계)."""
    result = run_report(_parse_date(date_))
    typer.echo(result)


if __name__ == "__main__":
    app()
