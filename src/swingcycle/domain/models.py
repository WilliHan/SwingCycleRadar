from dataclasses import dataclass, field
from datetime import date

from .enums import Action, CycleState, Gate


@dataclass(frozen=True)
class Symbol:
    symbol: str
    name: str
    market: str | None
    sector_group: str | None
    friend_group: str | None
    enabled: bool
    deleted_upstream: bool
    note: str | None


@dataclass(frozen=True)
class DailyBar:
    trade_date: date
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    trade_value: float | None
    market_cap: float | None
    source: str
    source_raw_hash: str | None
    collected_at: str


@dataclass(frozen=True)
class KRXResponse:
    market: str
    trade_date: date
    rows: list[dict]
    raw_hash: str
    endpoint: str
    source_mode: str  # "krx_direct" | "open_api_marketplace"


@dataclass(frozen=True)
class Decision:
    """일일 Decision Engine 산출물. 설계: 17장. 리포트(21장)의 카드 하나가 이 레코드 하나다."""
    symbol: str
    name: str
    friend_group: str | None
    trade_date: date
    cycle_state: CycleState
    reversal_core_score: float
    adx_gate: Gate
    pullback_score: float
    late_stage_score: float
    action: Action
    reasons: list[str] = field(default_factory=list)
    stop_price: float | None = None
