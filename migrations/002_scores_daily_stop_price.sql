-- scores_daily에 stop_price/entry_type이 애초에 없어서 DecisionEngine.evaluate()가
-- 계산한 값이 저장 단계에서 그냥 버려지고 있었다(대시보드가 항상 "제안 Stop: None"을
-- 보여준 원인). ALTER TABLE ADD COLUMN은 재실행 시 "duplicate column name" 에러가 나므로
-- db.py의 run_migrations()가 그 에러를 무시하도록 같이 고쳤다 — 이 파일은 몇 번을
-- 재실행해도 안전하다.
ALTER TABLE scores_daily ADD COLUMN stop_price REAL;
ALTER TABLE scores_daily ADD COLUMN entry_type TEXT;
