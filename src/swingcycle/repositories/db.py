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
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            conn.executescript(Path(path).read_text(encoding="utf-8"))
        conn.commit()
    finally:
        if owns_conn:
            conn.close()
