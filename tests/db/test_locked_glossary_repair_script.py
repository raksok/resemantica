from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_repair_script() -> ModuleType:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "repair_locked_glossary_schema.py"
    spec = importlib.util.spec_from_file_location("repair_locked_glossary_schema", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


repair_script = _load_repair_script()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _create_old_release_db(db_path: Path, release_id: str = "v1") -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS locked_glossary (
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
                UNIQUE (release_id, normalized_source_term, category),
                UNIQUE (release_id, normalized_target_term, category)
            );

            CREATE TABLE IF NOT EXISTS glossary_candidates (
                candidate_id TEXT PRIMARY KEY,
                release_id TEXT NOT NULL,
                source_term TEXT NOT NULL,
                normalized_source_term TEXT NOT NULL,
                category TEXT NOT NULL,
                source_language TEXT NOT NULL,
                first_seen_chapter INTEGER NOT NULL,
                last_seen_chapter INTEGER NOT NULL,
                appearance_count INTEGER NOT NULL,
                evidence_snippet TEXT NOT NULL,
                candidate_translation_en TEXT,
                normalized_target_term TEXT,
                discovery_run_id TEXT NOT NULL,
                translation_run_id TEXT,
                candidate_status TEXT NOT NULL,
                validation_status TEXT NOT NULL,
                conflict_reason TEXT,
                llm_keep INTEGER,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (release_id, normalized_source_term, category)
            );

            CREATE TABLE IF NOT EXISTS glossary_conflicts (
                conflict_id TEXT PRIMARY KEY,
                release_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                conflict_type TEXT NOT NULL,
                conflict_reason TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS glossary_translation_votes (
                vote_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                release_id TEXT NOT NULL,
                translation_run_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                raw_output TEXT NOT NULL,
                cleaned_output TEXT NOT NULL,
                normalized_output TEXT NOT NULL,
                resolution_status TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO locked_glossary(
                glossary_entry_id, release_id, source_term, normalized_source_term,
                target_term, normalized_target_term, category, status, approved_at,
                approval_run_id, source_candidate_id
            )
            VALUES(?, ?, '桂花岛', '桂花岛', 'Osmanthus Island', 'osmanthus island',
                   'place', 'approved', '2026-06-13T00:00:00Z', 'promote-old', ?)
            """,
            (f"{release_id}-lock-1", release_id, f"{release_id}-cand-1"),
        )
        candidate_rows = [
            (
                f"{release_id}-cand-1",
                release_id,
                "桂花岛",
                "桂花岛",
                "promoted",
                "approved",
                None,
                "Osmanthus Island",
            ),
            (f"{release_id}-cand-2", release_id, "大李", "大李", "conflict", "conflict", "old conflict", "Da Li"),
            (f"{release_id}-cand-3", release_id, "空项", "空项", "conflict", "conflict", "empty", None),
        ]
        conn.executemany(
            """
            INSERT INTO glossary_candidates(
                candidate_id, release_id, source_term, normalized_source_term, category,
                source_language, first_seen_chapter, last_seen_chapter, appearance_count,
                evidence_snippet, candidate_translation_en, normalized_target_term,
                discovery_run_id, translation_run_id, candidate_status, validation_status,
                conflict_reason, llm_keep
            )
            VALUES(?, ?, ?, ?, 'place', 'zh', 1, 1, 1, 'snippet', ?, lower(?),
                   'discover-001', 'translate-001', ?, ?, ?, 1)
            """,
            [
                (
                    candidate_id,
                    row_release_id,
                    source_term,
                    normalized_source_term,
                    translation,
                    translation,
                    status,
                    validation_status,
                    conflict_reason,
                )
                for (
                    candidate_id,
                    row_release_id,
                    source_term,
                    normalized_source_term,
                    status,
                    validation_status,
                    conflict_reason,
                    translation,
                ) in candidate_rows
            ],
        )
        conn.execute(
            """
            INSERT INTO glossary_conflicts(
                conflict_id, release_id, candidate_id, conflict_type, conflict_reason
            )
            VALUES(?, ?, ?, 'duplicate_target', 'old target conflict')
            """,
            (f"{release_id}-conflict-1", release_id, f"{release_id}-cand-2"),
        )
        conn.execute(
            """
            INSERT INTO glossary_translation_votes(
                vote_id, candidate_id, release_id, translation_run_id, model_name,
                prompt_version, raw_output, cleaned_output, normalized_output, resolution_status
            )
            VALUES(?, ?, ?, 'translate-001', 'model-a', 'prompt-v1',
                   'raw text', 'Da Li', 'da li', 'accepted')
            """,
            (f"{release_id}-vote-1", f"{release_id}-cand-2", release_id),
        )
        conn.commit()
    finally:
        conn.close()


def _count(conn: sqlite3.Connection, table_name: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()["count"])


def test_dry_run_reports_old_constraint_without_mutating(tmp_path: Path) -> None:
    db_path = tmp_path / "resemantica.db"
    _create_old_release_db(db_path)

    result = repair_script.inspect_locked_glossary(db_path, "v1")

    assert result.locked_count_before == 1
    assert result.locked_count_after == 1
    assert result.had_target_unique_constraint is True
    assert result.rebuilt_locked_glossary is False
    conn = _connect(db_path)
    try:
        assert repair_script.has_target_unique_constraint(conn) is True
        assert _count(conn, "glossary_conflicts") == 1
    finally:
        conn.close()


def test_apply_rebuilds_schema_and_preserves_release_data(tmp_path: Path) -> None:
    db_path = tmp_path / "resemantica.db"
    _create_old_release_db(db_path)

    result = repair_script.repair_locked_glossary(db_path, "v1", backup=True)

    assert result.backup_path is not None
    assert result.backup_path.exists()
    assert result.had_target_unique_constraint is True
    assert result.rebuilt_locked_glossary is True
    assert result.locked_count_before == 1
    assert result.locked_count_after == 1
    assert result.conflicts_deleted == 1
    assert result.candidates_reset == 2

    conn = _connect(db_path)
    try:
        assert repair_script.has_target_unique_constraint(conn) is False
        assert _count(conn, "locked_glossary") == 1
        assert _count(conn, "glossary_translation_votes") == 1
        assert _count(conn, "glossary_conflicts") == 0

        statuses = {
            row["candidate_id"]: (row["candidate_status"], row["validation_status"], row["conflict_reason"])
            for row in conn.execute(
                """
                SELECT candidate_id, candidate_status, validation_status, conflict_reason
                FROM glossary_candidates
                """
            )
        }
        assert statuses["v1-cand-1"] == ("translated", "pending", None)
        assert statuses["v1-cand-2"] == ("translated", "pending", None)
        assert statuses["v1-cand-3"] == ("conflict", "conflict", "empty")

        conn.execute(
            """
            INSERT INTO locked_glossary(
                glossary_entry_id, release_id, source_term, normalized_source_term,
                target_term, normalized_target_term, category, status, approved_at,
                approval_run_id, source_candidate_id
            )
            VALUES('lock-2', 'v1', '木犀岛', '木犀岛', 'Osmanthus Island',
                   'osmanthus island', 'place', 'approved',
                   '2026-06-13T00:00:00Z', 'promote-new', 'cand-4')
            """
        )
    finally:
        conn.close()


def test_apply_clears_only_selected_release_conflicts(tmp_path: Path) -> None:
    db_path = tmp_path / "resemantica.db"
    _create_old_release_db(db_path, release_id="v1")
    _create_old_release_db(db_path, release_id="v2")

    repair_script.repair_locked_glossary(db_path, "v1", backup=False)

    conn = _connect(db_path)
    try:
        remaining_conflicts = [
            row["release_id"]
            for row in conn.execute("SELECT release_id FROM glossary_conflicts ORDER BY release_id")
        ]
        assert remaining_conflicts == ["v2"]
    finally:
        conn.close()


def test_missing_locked_glossary_table_fails_clearly(tmp_path: Path) -> None:
    db_path = tmp_path / "resemantica.db"
    conn = _connect(db_path)
    conn.execute("CREATE TABLE glossary_candidates(candidate_id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="locked_glossary table not found"):
        repair_script.inspect_locked_glossary(db_path, "v1")
