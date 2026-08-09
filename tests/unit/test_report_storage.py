"""reports/storage.py 저장 경로/보존 정책 테스트."""
from __future__ import annotations

from datetime import date

from swingcycle.domain.enums import Action, CycleState, Gate
from swingcycle.domain.models import Decision
from swingcycle.reports.daily_report import ReportCard
from swingcycle.reports.storage import cleanup_old_reports, report_dir, save_report


def _card(symbol="005930") -> ReportCard:
    decision = Decision(
        symbol=symbol, name="삼성전자", friend_group="semiconductor", trade_date=date(2026, 1, 10),
        cycle_state=CycleState.REVERSAL, reversal_core_score=80.0, adx_gate=Gate.PASS,
        pullback_score=0.0, late_stage_score=0.0, action=Action.ENTRY,
        reasons=["DOW_REVERSAL_CANDIDATE"], stop_price=95.0,
    )
    return ReportCard(
        decision=decision, dow_state="REVERSAL_CANDIDATE", macd=1.0, macd_signal=0.5,
        macd_above_zero=True, rsi14=55.0, rsi_above_25=True, rsi_above_50=True, adx=28.0, mdi=15.0,
    )


class TestSaveReport:
    def test_writes_three_files_in_date_directory(self, tmp_path):
        trade_date = date(2026, 1, 10)
        paths = save_report([_card()], trade_date, base_dir=tmp_path)

        expected_dir = tmp_path / "2026-01-10"
        assert report_dir(trade_date, tmp_path) == expected_dir
        assert paths["html"] == expected_dir / "report.html"
        assert paths["html"].exists()
        assert paths["csv"].exists()
        assert paths["json"].exists()
        assert "005930" in paths["html"].read_text(encoding="utf-8")

    def test_rerun_overwrites_without_creating_duplicates(self, tmp_path):
        trade_date = date(2026, 1, 10)
        save_report([_card("005930")], trade_date, base_dir=tmp_path)
        save_report([_card("005930"), _card("000660")], trade_date, base_dir=tmp_path)  # 재실행, 카드 2개로

        out_dir = tmp_path / "2026-01-10"
        assert sorted(p.name for p in out_dir.iterdir()) == ["report.csv", "report.html", "report.json"]
        assert "000660" in (out_dir / "report.html").read_text(encoding="utf-8")


class TestCleanupOldReports:
    def test_removes_directories_older_than_retention(self, tmp_path):
        (tmp_path / "2025-01-01").mkdir()
        (tmp_path / "2026-01-01").mkdir()
        today = date(2026, 1, 10)

        removed = cleanup_old_reports(base_dir=tmp_path, retention_days=90, today=today)

        assert (tmp_path / "2025-01-01") in removed
        assert not (tmp_path / "2025-01-01").exists()
        assert (tmp_path / "2026-01-01").exists()  # 90일 이내라 유지

    def test_ignores_non_date_directories(self, tmp_path):
        (tmp_path / "not-a-date").mkdir()
        removed = cleanup_old_reports(base_dir=tmp_path, retention_days=1, today=date(2026, 1, 10))
        assert removed == []
        assert (tmp_path / "not-a-date").exists()

    def test_idempotent_second_call_removes_nothing_new(self, tmp_path):
        (tmp_path / "2025-01-01").mkdir()
        today = date(2026, 1, 10)
        first = cleanup_old_reports(base_dir=tmp_path, retention_days=90, today=today)
        second = cleanup_old_reports(base_dir=tmp_path, retention_days=90, today=today)
        assert len(first) == 1
        assert second == []

    def test_missing_base_dir_returns_empty(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        assert cleanup_old_reports(base_dir=missing) == []
