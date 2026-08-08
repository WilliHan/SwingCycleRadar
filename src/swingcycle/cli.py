from datetime import date, datetime

import typer

from .jobs.daily_collect import run_collect

app = typer.Typer(help="SwingCycle Radar CLI")


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


@app.command()
def collect(date_: str = typer.Option(..., "--date", help="YYYY-MM-DD")) -> None:
    """설계서 20.1 1단계: KRX/pykrx 수집."""
    result = run_collect(_parse_date(date_))
    typer.echo(result)


if __name__ == "__main__":
    app()
