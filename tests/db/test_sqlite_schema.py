from __future__ import annotations

import sqlite3
from pathlib import Path

from resemantica.db.sqlite import ensure_schema, open_connection


def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _unique_index_columns(conn: sqlite3.Connection, table_name: str) -> set[tuple[str, ...]]:
    columns: set[tuple[str, ...]] = set()
    for index in conn.execute(f"PRAGMA index_list({table_name})"):
        if int(index["unique"]) != 1:
            continue
        rows = conn.execute(f"PRAGMA index_info({index['name']})").fetchall()
        columns.add(tuple(str(row["name"]) for row in rows))
    return columns


def test_ensure_schema_creates_absorbed_columns_on_fresh_db() -> None:
    conn = open_connection(":memory:")
    try:
        ensure_schema(conn, "translation")

        assert "packet_version_hash" in _columns(conn, "translation_checkpoints")
        assert {
            "release_id",
            "run_id",
            "stage_name",
            "chunk_index",
            "chapter_start",
            "chapter_end",
            "status",
            "metadata_json",
        } <= _columns(conn, "chunk_checkpoints")
        assert {"pos_tags", "llm_confidence"} <= _columns(conn, "glossary_candidates")
        assert {"input_hash"} <= _columns(conn, "glossary_checkpoints")
        assert {"raw_candidates_json", "candidate_count"} <= _columns(
            conn,
            "glossary_discovery_chapter_state",
        )
        assert {"dictionary_match", "existing_policy_id"} <= _columns(conn, "idiom_candidates")
    finally:
        conn.close()


def test_locked_glossary_fresh_schema_allows_shared_targets() -> None:
    conn = open_connection(":memory:")
    try:
        ensure_schema(conn, "glossary")
        unique_columns = _unique_index_columns(conn, "locked_glossary")

        assert ("release_id", "normalized_source_term", "category") in unique_columns
        assert ("release_id", "normalized_target_term", "category") not in unique_columns
    finally:
        conn.close()


def test_ensure_schema_is_idempotent_for_chunk_checkpoints() -> None:
    conn = open_connection(":memory:")
    try:
        ensure_schema(conn, "translation")
        ensure_schema(conn, "translation")

        assert "chunk_checkpoints" in {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()


def test_active_source_does_not_reintroduce_migration_schema_patterns() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src" / "resemantica"
    forbidden_patterns = ("apply_migrations", "schema_migrations", "ALTER TABLE", "db/migrations")

    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            if pattern in text:
                violations.append(f"{path.relative_to(source_root)}: {pattern}")

    assert violations == []
