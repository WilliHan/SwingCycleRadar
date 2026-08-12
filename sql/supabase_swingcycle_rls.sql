-- SwingCycle 일별 테이블 4종 RLS 활성화
-- Supabase Dashboard > SQL Editor 에서 실행 (supabase_swingcycle_daily.sql 이후)
-- 생성일: 2026-08-12
--
-- 배경: Supabase 보안 경고(rls_disabled_in_public) 대응.
--
-- 근거: src/swingcycle/data/supabase_client.py는 SUPABASE_SERVICE_KEY가 없으면
-- 폴백 없이 예외를 던진다(라인 17-19) — anon 키로 접근할 코드 경로 자체가 없으므로
-- RLS를 켜도 기존 배치 동작에 영향이 없다.

ALTER TABLE public.swingcycle_indicators_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.swingcycle_cycle_daily      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.swingcycle_scores_daily     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.swingcycle_pivots           ENABLE ROW LEVEL SECURITY;
