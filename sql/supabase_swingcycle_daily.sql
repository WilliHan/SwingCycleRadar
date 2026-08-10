-- Supabase 프로젝트에 직접 실행하는 DDL (로컬 SQLite migrations/001_init.sql과는 별개).
-- 대상: SwingCycle Radar가 쓰는 Supabase 프로젝트의 SQL Editor에서 실행.
--
-- PostgREST(REST API)로는 DDL을 실행할 수 없어 SUPABASE_URL/SUPABASE_SERVICE_KEY만으로는
-- 이 테이블을 만들 수 없다 — Supabase 대시보드의 SQL Editor에서 이 파일 내용을 직접 실행할 것.
--
-- 용도: 대시보드는 계속 로컬 SQLite(migrations/001_init.sql)를 읽는다. 여기 4개 테이블은
-- 배치(swingcycle decide)가 끝날 때마다 그날 결과를 "기록"해두는 용도이고, 반대로 로컬에
-- 없는 최근 이력을 당겨와 채우는 데도 쓰인다(data/supabase_daily_sync.py). 컬럼은 로컬
-- SQLite의 indicators_daily/cycle_daily/scores_daily/pivots를 그대로 미러링한다.

CREATE TABLE IF NOT EXISTS swingcycle_indicators_daily (
    trade_date        DATE NOT NULL,
    symbol            TEXT NOT NULL,
    sma5              DOUBLE PRECISION,
    sma20             DOUBLE PRECISION,
    sma60             DOUBLE PRECISION,
    sma120            DOUBLE PRECISION,
    sma240            DOUBLE PRECISION,
    ema12             DOUBLE PRECISION,
    ema26             DOUBLE PRECISION,
    macd              DOUBLE PRECISION,
    macd_signal       DOUBLE PRECISION,
    macd_hist         DOUBLE PRECISION,
    rsi14             DOUBLE PRECISION,
    rsi_signal        DOUBLE PRECISION,
    pdi14             DOUBLE PRECISION,
    mdi14             DOUBLE PRECISION,
    adx14             DOUBLE PRECISION,
    vo10_20           DOUBLE PRECISION,
    ma5_distance_pct  DOUBLE PRECISION,
    PRIMARY KEY (trade_date, symbol)
);

CREATE TABLE IF NOT EXISTS swingcycle_cycle_daily (
    trade_date            DATE NOT NULL,
    symbol                TEXT NOT NULL,
    cycle_state           TEXT NOT NULL,
    dow_state             TEXT NOT NULL,
    last_pivot_high_date  DATE,
    last_pivot_high       DOUBLE PRECISION,
    last_pivot_low_date   DATE,
    last_pivot_low        DOUBLE PRECISION,
    PRIMARY KEY (trade_date, symbol)
);

CREATE TABLE IF NOT EXISTS swingcycle_scores_daily (
    trade_date            DATE NOT NULL,
    symbol                TEXT NOT NULL,
    reversal_core_score   DOUBLE PRECISION,
    adx_gate              TEXT,             -- PASS/CAUTION/BLOCK
    pullback_score        DOUBLE PRECISION,
    late_stage_score      DOUBLE PRECISION,
    action                TEXT,             -- WAIT/READY/ENTRY/ADD/TAKE_PROFIT/EXIT/RESET/STOP
    reasons_json          TEXT NOT NULL,
    stop_price            DOUBLE PRECISION,
    entry_type            TEXT,
    PRIMARY KEY (trade_date, symbol)
);

CREATE TABLE IF NOT EXISTS swingcycle_pivots (
    symbol         TEXT NOT NULL,
    pivot_date     DATE NOT NULL,
    confirm_date   DATE NOT NULL,
    pivot_type     TEXT NOT NULL,           -- HIGH / LOW
    price          DOUBLE PRECISION NOT NULL,
    left_bars      INTEGER NOT NULL,
    right_bars     INTEGER NOT NULL,
    dow_label      TEXT,                    -- HH/HL/LH/LL
    PRIMARY KEY (symbol, pivot_date, pivot_type)
);

CREATE INDEX IF NOT EXISTS idx_swingcycle_pivots_confirm_date ON swingcycle_pivots(confirm_date);
