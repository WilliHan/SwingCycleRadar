-- Supabase 프로젝트에 직접 실행하는 DDL (로컬 SQLite migrations/001_init.sql과는 별개).
-- 대상: SwingCycle Radar가 쓰는 Supabase 프로젝트의 SQL Editor에서 실행.
-- 출처: docs/SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md 6.1
--
-- PostgREST(REST API)로는 DDL을 실행할 수 없어 SUPABASE_URL/SUPABASE_SERVICE_KEY만으로는
-- 이 테이블을 만들 수 없다 — Supabase 대시보드의 SQL Editor에서 이 파일 내용을 직접 실행할 것.

CREATE TABLE IF NOT EXISTS swingcycle_symbols (
    symbol        TEXT PRIMARY KEY,       -- 6자리 종목코드, zero-padded
    name          TEXT NOT NULL,
    market        TEXT,                   -- KOSPI/KOSDAQ, 시드 시점엔 nullable 허용
    friend_group  TEXT,                   -- config/friend_universe.yml의 group과 동일 의미
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    note          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by    TEXT                    -- Hub 이메일 (X-Hub-User-Email 헤더에서 획득)
);
