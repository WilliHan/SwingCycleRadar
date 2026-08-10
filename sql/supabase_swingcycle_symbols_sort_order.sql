-- Supabase 프로젝트 SQL Editor에서 수동 실행 (PostgREST로는 DDL 불가).
-- 종목관리 탭에서 사용자가 직접 지정하는 표시 순서. NULL이면 정렬 시 맨 뒤로 밀린다.
ALTER TABLE swingcycle_symbols ADD COLUMN IF NOT EXISTS sort_order INTEGER;
