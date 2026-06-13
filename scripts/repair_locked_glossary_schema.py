from __future__ import annotations

import argparse
import importlib
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

_settings = importlib.import_module("resemantica.settings")
derive_paths = _settings.derive_paths
load_config = _settings.load_config


LOCKED_GLOSSARY_COLUMNS = (
    "glossary_entry_id",
    "release_id",
    "source_term",
    "normalized_source_term",
    "target_term",
    "normalized_target_term",
    "category",
    "status",
    "approved_at",
    "approval_run_id",
    "source_candidate_id",
    "schema_version",
)


@dataclass(frozen=True)
class RepairResult:
    db_path: Path
    backup_path: Path | None
    locked_count_before: int
    locked_count_after: int
    had_target_unique_constraint: bool
    rebuilt_locked_glossary: bool
    conflicts_deleted: int
    candidates_reset: int


def _connect_existing_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _require_locked_glossary(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "locked_glossary"):
        raise RuntimeError("locked_glossary table not found; this helper only repairs existing release DBs")


def _unique_index_columns(conn: sqlite3.Connection, table_name: str) -> set[tuple[str, ...]]:
    unique_columns: set[tuple[str, ...]] = set()
    for index in conn.execute(f"PRAGMA index_list({table_name})").fetchall():
        if int(index["unique"]) != 1:
            continue
        rows = conn.execute(f"PRAGMA index_info({index['name']})").fetchall()
        unique_columns.add(tuple(str(row["name"]) for row in rows))
    return unique_columns


def has_target_unique_constraint(conn: sqlite3.Connection) -> bool:
    return (
        "release_id",
        "normalized_target_term",
        "category",
    ) in _unique_index_columns(conn, "locked_glossary")


def _count_rows(conn: sqlite3.Connection, table_name: str, release_id: str | None = None) -> int:
    if release_id is None:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
    else:
        row = conn.execute(
            f"SELECT COUNT(*) AS count FROM {table_name} WHERE release_id = ?",
            (release_id,),
        ).fetchone()
    return int(row["count"])


def _backup_db(db_path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.with_name(f"{db_path.stem}.backup-{timestamp}{db_path.suffix}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def _rebuild_locked_glossary(conn: sqlite3.Connection) -> None:
    columns_sql = ", ".join(LOCKED_GLOSSARY_COLUMNS)
    conn.execute("DROP TABLE IF EXISTS locked_glossary_repaired")
    conn.execute(
        """
        CREATE TABLE locked_glossary_repaired (
            glossary_entry_id TEXT PRIMARY KEY,
            release_id TEXT NOT NULL,
            source_term TEXT NOT NULL,
            normalized_source_term TEXT NOT NULL,
            target_term TEXT NOT NULL,
            normalized_target_term TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT NOT NULL,
            approved_at TEXT NOT NULL,
            approval_run_id TEXT NOT NULL,
            source_candidate_id TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            UNIQUE (release_id, normalized_source_term, category)
        )
        """,
    )
    conn.execute(
        f"""
        INSERT OR IGNORE INTO locked_glossary_repaired({columns_sql})
        SELECT {columns_sql}
        FROM locked_glossary
        """,
    )
    conn.execute("DROP TABLE locked_glossary")
    conn.execute("ALTER TABLE locked_glossary_repaired RENAME TO locked_glossary")


def _reset_promoted_or_conflict_candidates(conn: sqlite3.Connection, release_id: str) -> int:
    if not _table_exists(conn, "glossary_candidates"):
        return 0
    cursor = conn.execute(
        """
        UPDATE glossary_candidates
        SET candidate_status = 'translated',
            validation_status = 'pending',
            conflict_reason = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE release_id = ?
          AND candidate_status IN ('promoted', 'conflict')
          AND candidate_translation_en IS NOT NULL
          AND candidate_translation_en != ''
        """,
        (release_id,),
    )
    return cursor.rowcount if cursor.rowcount is not None else 0


def _delete_conflicts(conn: sqlite3.Connection, release_id: str) -> int:
    if not _table_exists(conn, "glossary_conflicts"):
        return 0
    cursor = conn.execute("DELETE FROM glossary_conflicts WHERE release_id = ?", (release_id,))
    return cursor.rowcount if cursor.rowcount is not None else 0


def inspect_locked_glossary(db_path: Path, release_id: str) -> RepairResult:
    conn = _connect_existing_db(db_path)
    try:
        _require_locked_glossary(conn)
        return RepairResult(
            db_path=db_path,
            backup_path=None,
            locked_count_before=_count_rows(conn, "locked_glossary", release_id),
            locked_count_after=_count_rows(conn, "locked_glossary", release_id),
            had_target_unique_constraint=has_target_unique_constraint(conn),
            rebuilt_locked_glossary=False,
            conflicts_deleted=0,
            candidates_reset=0,
        )
    finally:
        conn.close()


def repair_locked_glossary(db_path: Path, release_id: str, *, backup: bool = True) -> RepairResult:
    backup_path = _backup_db(db_path) if backup else None
    conn = _connect_existing_db(db_path)
    try:
        _require_locked_glossary(conn)
        before = _count_rows(conn, "locked_glossary", release_id)
        had_target_unique = has_target_unique_constraint(conn)
        with conn:
            if had_target_unique:
                _rebuild_locked_glossary(conn)
            conflicts_deleted = _delete_conflicts(conn, release_id)
            candidates_reset = _reset_promoted_or_conflict_candidates(conn, release_id)
        after = _count_rows(conn, "locked_glossary", release_id)
        return RepairResult(
            db_path=db_path,
            backup_path=backup_path,
            locked_count_before=before,
            locked_count_after=after,
            had_target_unique_constraint=had_target_unique,
            rebuilt_locked_glossary=had_target_unique,
            conflicts_deleted=conflicts_deleted,
            candidates_reset=candidates_reset,
        )
    finally:
        conn.close()


def _db_path_for_release(project_root: Path, release_id: str) -> Path:
    config = load_config(project_root / "resemantica.toml")
    return derive_paths(config, release_id=release_id, project_root=project_root).db_path


def _print_result(result: RepairResult, *, applied: bool) -> None:
    mode = "applied" if applied else "dry-run"
    print(f"locked glossary repair {mode}")
    print(f"db_path: {result.db_path}")
    if result.backup_path is not None:
        print(f"backup_path: {result.backup_path}")
    print(f"locked_count_before: {result.locked_count_before}")
    print(f"locked_count_after: {result.locked_count_after}")
    print(f"had_target_unique_constraint: {result.had_target_unique_constraint}")
    print(f"rebuilt_locked_glossary: {result.rebuilt_locked_glossary}")
    print(f"conflicts_deleted: {result.conflicts_deleted}")
    print(f"candidates_reset: {result.candidates_reset}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair an existing release DB after the locked_glossary uniqueness policy changed.",
    )
    parser.add_argument("--release", required=True, help="Release ID to repair.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing resemantica.toml. Defaults to the current directory.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Inspect the DB without modifying it.")
    mode.add_argument("--apply", action="store_true", help="Apply the repair.")
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Apply without creating a timestamped DB backup. Only valid with --apply.",
    )
    args = parser.parse_args(argv)
    if args.no_backup and not args.apply:
        parser.error("--no-backup is only valid with --apply")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = args.project_root.resolve()
    db_path = _db_path_for_release(project_root, args.release)
    try:
        if args.apply:
            result = repair_locked_glossary(db_path, args.release, backup=not args.no_backup)
            _print_result(result, applied=True)
        else:
            result = inspect_locked_glossary(db_path, args.release)
            _print_result(result, applied=False)
    except (FileNotFoundError, RuntimeError, sqlite3.DatabaseError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
