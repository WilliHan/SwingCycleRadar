-- 종목관리 탭에서 사용자가 직접 지정하는 표시 순서. NULL이면 정렬 시 맨 뒤로 밀린다.
-- ALTER TABLE ADD COLUMN은 재실행 시 "duplicate column name" 에러가 나지만
-- db.py의 run_migrations()가 그 에러를 무시하므로 이 파일은 몇 번을 재실행해도 안전하다.
ALTER TABLE symbols ADD COLUMN sort_order INTEGER;
