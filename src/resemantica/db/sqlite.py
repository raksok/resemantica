from __future__ import annotations

import sqlite3
from pathlib import Path

from loguru import logger


def open_connection(db_path: str | Path) -> sqlite3.Connection:
    if isinstance(db_path, Path):
        resolved = db_path.resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        target = str(resolved)
    else:
        target = db_path

    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row

    if target != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL;")

    return conn


def apply_migrations(conn: sqlite3.Connection, migrations_dir: str | Path) -> None:
    directory = Path(migrations_dir)
    if not directory.exists():
        return

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()

    applied_versions = {
        int(row["version"]) for row in conn.execute("SELECT version FROM schema_migrations")
    }

    logger.debug("apply_migrations called, migrations_dir={}", directory)
    logger.debug("applied_versions={}", applied_versions)

    for migration_file in sorted(directory.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(migration_file.name.split("_", 1)[0])
        logger.debug("checking migration {}, version={}", migration_file.name, version)
        if version in applied_versions:
            logger.debug("migration {} already applied, skipping", version)
            continue

        logger.debug("applying migration {}", migration_file.name)
        sql = migration_file.read_text(encoding="utf-8")
        with conn:
            conn.executescript(sql)
            if version == 4:
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='summary_drafts'")
                table_exists = cursor.fetchone() is not None
                logger.debug("After migration 4, summary_drafts exists: {}", table_exists)
            conn.execute(
                "INSERT INTO schema_migrations(version, filename) VALUES(?, ?)",
                (version, migration_file.name),
            )
            logger.debug("migration {} applied successfully", version)


def ensure_schema(conn: sqlite3.Connection, name: str) -> None:
    migrations_dir = Path(__file__).resolve().parent / "migrations"
    apply_migrations(conn, migrations_dir)

