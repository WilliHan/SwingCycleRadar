import sqlite3
from pathlib import Path

from ..settings import PROJECT_ROOT, settings

MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


def get_connection() -> sqlite3.Connection:
    db_path = settings.db_path_resolved
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def run_migrations(conn: sqlite3.Connection | None = None) -> None:
    """마이그레이션 적용 이력 테이블이 따로 없다 — 매번 모든 .sql 파일을 다시 실행하고,
    CREATE TABLE/INDEX는 IF NOT EXISTS로 스스로 idempotent하다. 다만 SQLite는
    "ALTER TABLE ... ADD COLUMN IF NOT EXISTS"를 지원하지 않아서(스키마 변경 마이그레이션에
    필요), 문장 단위로 실행하며 "duplicate column name" 에러만 이미 적용된 것으로 보고
    무시한다 — 그 외 에러는 그대로 올린다."""
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            for statement in Path(path).read_text(encoding="utf-8").split(";"):
                statement = statement.strip()
                if not statement:
                    continue
                try:
                    conn.execute(statement)
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc):
                        raise
        conn.commit()
    finally:
        if owns_conn:
            conn.close()
