from datetime import date, datetime

import typer

from .jobs.daily_collect import run_collect
from .jobs.daily_decide import run_decide
from .jobs.daily_report_job import run_report

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
