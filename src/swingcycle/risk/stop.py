"""Stop 가격 산정 + 체결 시뮬레이션. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 16.1/16.3."""
from __future__ import annotations


def suggest_stop_price(pivot_low_price: float, buffer_pct: float = 1.0) -> float:
    """16.1 — 최근 의미 있는 pivot low 저가 대비 buffer_pct%만큼 낮춘 가격."""
    return pivot_low_price * (1 - buffer_pct / 100.0)


def simulated_stop_fill(open_: float, low: float, stop: float) -> float | None:
    """16.3 — EOD 백테스트용 stop 체결가 시뮬레이션.
    갭다운으로 시가부터 stop 아래면 시가 체결, 장중에만 터치했으면 stop가 체결,
    stop을 건드리지 않았으면 미체결(None)."""
    if open_ <= stop:
        return open_
    if low <= stop:
        return stop
    return None
