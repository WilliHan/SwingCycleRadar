from dataclasses import dataclass
from datetime import date


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
