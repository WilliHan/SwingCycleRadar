-- SwingCycle Radar initial schema
-- Source: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 7장

CREATE TABLE IF NOT EXISTS symbols (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    market TEXT,
    sector_group TEXT,
    friend_group TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    deleted_upstream INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_bars (
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    trade_value REAL,
    market_cap REAL,
    source TEXT NOT NULL,
    source_raw_hash TEXT,
    collected_at TEXT NOT NULL,
    PRIMARY KEY (trade_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_daily_bars_symbol_date ON daily_bars(symbol, trade_date);

CREATE TABLE IF NOT EXISTS indicators_daily (
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    sma5 REAL,
    sma20 REAL,
    sma60 REAL,
    sma120 REAL,
    sma240 REAL,
    ema12 REAL,
    ema26 REAL,
    macd REAL,
    macd_signal REAL,
    macd_hist REAL,
    rsi14 REAL,
    rsi_signal REAL,
    pdi14 REAL,
    mdi14 REAL,
    adx14 REAL,
    vo10_20 REAL,
    ma5_distance_pct REAL,
    PRIMARY KEY (trade_date, symbol)
);

CREATE TABLE IF NOT EXISTS pivots (
    symbol TEXT NOT NULL,
    pivot_date TEXT NOT NULL,
    confirm_date TEXT NOT NULL,
    pivot_type TEXT NOT NULL,       -- HIGH / LOW
    price REAL NOT NULL,
    left_bars INTEGER NOT NULL,
    right_bars INTEGER NOT NULL,
    dow_label TEXT,                 -- HH/HL/LH/LL after classification
    PRIMARY KEY(symbol, pivot_date, pivot_type)
);

CREATE TABLE IF NOT EXISTS cycle_daily (
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    cycle_state TEXT NOT NULL,
    dow_state TEXT NOT NULL,
    last_pivot_high_date TEXT,
    last_pivot_high REAL,
    last_pivot_low_date TEXT,
    last_pivot_low REAL,
    PRIMARY KEY(trade_date, symbol)
);

CREATE TABLE IF NOT EXISTS scores_daily (
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    reversal_core_score REAL,
    adx_gate TEXT,                  -- PASS/CAUTION/BLOCK
    pullback_score REAL,
    late_stage_score REAL,
    action TEXT,                    -- WAIT/READY/ENTRY/ADD/TAKE_PROFIT/EXIT/RESET
    reasons_json TEXT NOT NULL,
    PRIMARY KEY(trade_date, symbol)
);

CREATE TABLE IF NOT EXISTS trade_plans (
    plan_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    created_date TEXT NOT NULL,
    entry_type TEXT NOT NULL,       -- REVERSAL/PULLBACK
    planned_entry REAL,
    stop_price REAL NOT NULL,
    stop_basis_pivot_date TEXT,
    status TEXT NOT NULL            -- ACTIVE/STOPPED/CLOSED/RESET
);

-- 종목당 ACTIVE 플랜은 최대 1개만 허용 (v1.1 신설, 7.7 참고)
CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_plans_one_active_per_symbol
    ON trade_plans(symbol)
    WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS trade_events (
    event_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    event_type TEXT NOT NULL,       -- ENTRY/ADD/STOP/TAKE_PROFIT/EXIT/RESET
    price REAL,
    qty_weight REAL,
    note TEXT,
    created_at TEXT NOT NULL
);
