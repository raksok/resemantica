from __future__ import annotations

from pathlib import Path
import sqlite3


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

    print(f"DEBUG: apply_migrations called, migrations_dir={directory}")
    print(f"DEBUG: applied_versions={applied_versions}")

    for migration_file in sorted(directory.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(migration_file.name.split("_", 1)[0])
        print(f"DEBUG: checking migration {migration_file.name}, version={version}")
        if version in applied_versions:
            print(f"DEBUG: migration {version} already applied, skipping")
            continue

        print(f"DEBUG: applying migration {migration_file.name}")
        sql = migration_file.read_text(encoding="utf-8")
        with conn:
            conn.executescript(sql)
            # Check if summary_drafts exists after migration 4
            if version == 4:
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='summary_drafts'")
                table_exists = cursor.fetchone() is not None
                print(f"DEBUG: After migration 4, summary_drafts exists: {table_exists}")
            conn.execute(
                "INSERT INTO schema_migrations(version, filename) VALUES(?, ?)",
                (version, migration_file.name),
            )
            print(f"DEBUG: migration {version} applied successfully")


def get_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations").fetchone()
    if row is None:
        return 0
    return int(row["version"])

