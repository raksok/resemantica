from __future__ import annotations

import sqlite3
from typing import Sequence

from resemantica.db.sqlite import ensure_schema
from resemantica.glossary.models import GlossaryCandidate, GlossaryConflict, LockedGlossaryEntry


def ensure_glossary_schema(conn: sqlite3.Connection) -> None:
    ensure_schema(conn, "glossary")


def _candidate_from_row(row: sqlite3.Row) -> GlossaryCandidate:
    raw_critic = row["critic_score"]
    return GlossaryCandidate(
        candidate_id=str(row["candidate_id"]),
        release_id=str(row["release_id"]),
        source_term=str(row["source_term"]),
        normalized_source_term=str(row["normalized_source_term"]),
        category=str(row["category"]),
        source_language=str(row["source_language"]),
        first_seen_chapter=int(row["first_seen_chapter"]),
        last_seen_chapter=int(row["last_seen_chapter"]),
        appearance_count=int(row["appearance_count"]),
        evidence_snippet=str(row["evidence_snippet"]),
        candidate_translation_en=(
            None if row["candidate_translation_en"] is None else str(row["candidate_translation_en"])
        ),
        normalized_target_term=(
            None if row["normalized_target_term"] is None else str(row["normalized_target_term"])
        ),
        discovery_run_id=str(row["discovery_run_id"]),
        translation_run_id=(None if row["translation_run_id"] is None else str(row["translation_run_id"])),
        candidate_status=str(row["candidate_status"]),
        validation_status=str(row["validation_status"]),
        conflict_reason=(None if row["conflict_reason"] is None else str(row["conflict_reason"])),
        critic_score=(float(raw_critic) if raw_critic is not None else None),
        analyst_model_name=(
            None if row["analyst_model_name"] is None else str(row["analyst_model_name"])
        ),
        analyst_prompt_version=(
            None if row["analyst_prompt_version"] is None else str(row["analyst_prompt_version"])
        ),
        translator_model_name=(
            None if row["translator_model_name"] is None else str(row["translator_model_name"])
        ),
        translator_prompt_version=(
            None
            if row["translator_prompt_version"] is None
            else str(row["translator_prompt_version"])
        ),
        schema_version=int(row["schema_version"]),
    )


def _locked_from_row(row: sqlite3.Row) -> LockedGlossaryEntry:
    return LockedGlossaryEntry(
        glossary_entry_id=str(row["glossary_entry_id"]),
        release_id=str(row["release_id"]),
        source_term=str(row["source_term"]),
        normalized_source_term=str(row["normalized_source_term"]),
        target_term=str(row["target_term"]),
        normalized_target_term=str(row["normalized_target_term"]),
        category=str(row["category"]),
        status=str(row["status"]),
        approved_at=str(row["approved_at"]),
        approval_run_id=str(row["approval_run_id"]),
        source_candidate_id=str(row["source_candidate_id"]),
        schema_version=int(row["schema_version"]),
    )


def _conflict_from_row(row: sqlite3.Row) -> GlossaryConflict:
    return GlossaryConflict(
        conflict_id=str(row["conflict_id"]),
        release_id=str(row["release_id"]),
        candidate_id=str(row["candidate_id"]),
        conflict_type=str(row["conflict_type"]),
        conflict_reason=str(row["conflict_reason"]),
        existing_glossary_id=(
            None if row["existing_glossary_id"] is None else str(row["existing_glossary_id"])
        ),
        schema_version=int(row["schema_version"]),
    )


def upsert_discovered_candidates(
    conn: sqlite3.Connection,
    *,
    candidates: Sequence[GlossaryCandidate],
) -> None:
    if not candidates:
        return
    with conn:
        conn.executemany(
            """
            INSERT INTO glossary_candidates(
                candidate_id, release_id, source_term, normalized_source_term,
                category, source_language, first_seen_chapter, last_seen_chapter,
                appearance_count, evidence_snippet, candidate_translation_en,
                normalized_target_term, discovery_run_id, translation_run_id,
                candidate_status, validation_status, conflict_reason, critic_score,
                analyst_model_name, analyst_prompt_version,
                translator_model_name, translator_prompt_version, schema_version, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(release_id, normalized_source_term, category)
            DO UPDATE SET
                source_term = excluded.source_term,
                first_seen_chapter = MIN(excluded.first_seen_chapter, first_seen_chapter),
                last_seen_chapter = MAX(excluded.last_seen_chapter, last_seen_chapter),
                appearance_count = appearance_count + excluded.appearance_count,
                evidence_snippet = excluded.evidence_snippet,
                candidate_status = excluded.candidate_status,
                validation_status = excluded.validation_status,
                conflict_reason = excluded.conflict_reason,
                critic_score = excluded.critic_score,
                discovery_run_id = excluded.discovery_run_id,
                analyst_model_name = excluded.analyst_model_name,
                analyst_prompt_version = excluded.analyst_prompt_version,
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    candidate.candidate_id,
                    candidate.release_id,
                    candidate.source_term,
                    candidate.normalized_source_term,
                    candidate.category,
                    candidate.source_language,
                    candidate.first_seen_chapter,
                    candidate.last_seen_chapter,
                    candidate.appearance_count,
                    candidate.evidence_snippet,
                    candidate.candidate_translation_en,
                    candidate.normalized_target_term,
                    candidate.discovery_run_id,
                    candidate.translation_run_id,
                    candidate.candidate_status,
                    candidate.validation_status,
                    candidate.conflict_reason,
                    candidate.critic_score,
                    candidate.analyst_model_name,
                    candidate.analyst_prompt_version,
                    candidate.translator_model_name,
                    candidate.translator_prompt_version,
                    candidate.schema_version,
                )
                for candidate in candidates
            ],
        )


def list_candidates(conn: sqlite3.Connection, *, release_id: str) -> list[GlossaryCandidate]:
    rows = conn.execute(
        """
        SELECT candidate_id, release_id, source_term, normalized_source_term, category,
               source_language, first_seen_chapter, last_seen_chapter, appearance_count,
               evidence_snippet, candidate_translation_en, normalized_target_term,
               discovery_run_id, translation_run_id, candidate_status, validation_status,
               conflict_reason, critic_score, analyst_model_name, analyst_prompt_version,
               translator_model_name, translator_prompt_version, schema_version
        FROM glossary_candidates
        WHERE release_id = ?
        ORDER BY first_seen_chapter, normalized_source_term, category
        """,
        (release_id,),
    ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def list_candidates_for_translation(
    conn: sqlite3.Connection,
    *,
    release_id: str,
) -> list[GlossaryCandidate]:
    rows = conn.execute(
        """
        SELECT candidate_id, release_id, source_term, normalized_source_term, category,
               source_language, first_seen_chapter, last_seen_chapter, appearance_count,
               evidence_snippet, candidate_translation_en, normalized_target_term,
               discovery_run_id, translation_run_id, candidate_status, validation_status,
               conflict_reason, critic_score, analyst_model_name, analyst_prompt_version,
               translator_model_name, translator_prompt_version, schema_version
        FROM glossary_candidates
        WHERE release_id = ?
          AND (candidate_translation_en IS NULL OR candidate_translation_en = '')
        ORDER BY first_seen_chapter, normalized_source_term, category
        """,
        (release_id,),
    ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def list_candidates_for_promotion(
    conn: sqlite3.Connection,
    *,
    release_id: str,
) -> list[GlossaryCandidate]:
    rows = conn.execute(
        """
        SELECT candidate_id, release_id, source_term, normalized_source_term, category,
               source_language, first_seen_chapter, last_seen_chapter, appearance_count,
               evidence_snippet, candidate_translation_en, normalized_target_term,
               discovery_run_id, translation_run_id, candidate_status, validation_status,
               conflict_reason, critic_score, analyst_model_name, analyst_prompt_version,
               translator_model_name, translator_prompt_version, schema_version
        FROM glossary_candidates
        WHERE release_id = ?
          AND candidate_translation_en IS NOT NULL
          AND candidate_translation_en != ''
          AND candidate_status != 'promoted'
        ORDER BY first_seen_chapter, normalized_source_term, category
        """,
        (release_id,),
    ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def list_candidates_for_review(
    conn: sqlite3.Connection,
    *,
    release_id: str,
) -> list[GlossaryCandidate]:
    rows = conn.execute(
        """
        SELECT candidate_id, release_id, source_term, normalized_source_term, category,
               source_language, first_seen_chapter, last_seen_chapter, appearance_count,
               evidence_snippet, candidate_translation_en, normalized_target_term,
               discovery_run_id, translation_run_id, candidate_status, validation_status,
               conflict_reason, critic_score, analyst_model_name, analyst_prompt_version,
               translator_model_name, translator_prompt_version, schema_version
        FROM glossary_candidates
        WHERE release_id = ?
          AND candidate_status = 'translated'
        ORDER BY first_seen_chapter, normalized_source_term, category
        """,
        (release_id,),
    ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def save_candidate_translation(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    translation_run_id: str,
    target_term: str,
    normalized_target_term: str,
    translator_model_name: str,
    translator_prompt_version: str,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE glossary_candidates
            SET candidate_translation_en = ?,
                normalized_target_term = ?,
                translation_run_id = ?,
                translator_model_name = ?,
                translator_prompt_version = ?,
                candidate_status = 'translated',
                validation_status = 'pending',
                conflict_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE candidate_id = ?
            """,
            (
                target_term,
                normalized_target_term,
                translation_run_id,
                translator_model_name,
                translator_prompt_version,
                candidate_id,
            ),
        )


def mark_candidate_conflict(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    conflict_reason: str,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE glossary_candidates
            SET candidate_status = 'conflict',
                validation_status = 'conflict',
                conflict_reason = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE candidate_id = ?
            """,
            (conflict_reason, candidate_id),
        )


def mark_candidate_promoted(conn: sqlite3.Connection, *, candidate_id: str) -> None:
    with conn:
        conn.execute(
            """
            UPDATE glossary_candidates
            SET candidate_status = 'promoted',
                validation_status = 'approved',
                conflict_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE candidate_id = ?
            """,
            (candidate_id,),
        )


def insert_conflicts(conn: sqlite3.Connection, *, conflicts: Sequence[GlossaryConflict]) -> None:
    if not conflicts:
        return
    with conn:
        conn.executemany(
            """
            INSERT INTO glossary_conflicts(
                conflict_id, release_id, candidate_id, conflict_type,
                conflict_reason, existing_glossary_id, schema_version, detected_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(conflict_id)
            DO UPDATE SET
                conflict_reason = excluded.conflict_reason,
                existing_glossary_id = excluded.existing_glossary_id,
                detected_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    conflict.conflict_id,
                    conflict.release_id,
                    conflict.candidate_id,
                    conflict.conflict_type,
                    conflict.conflict_reason,
                    conflict.existing_glossary_id,
                    conflict.schema_version,
                )
                for conflict in conflicts
            ],
        )


def list_conflicts(conn: sqlite3.Connection, *, release_id: str) -> list[GlossaryConflict]:
    rows = conn.execute(
        """
        SELECT conflict_id, release_id, candidate_id, conflict_type,
               conflict_reason, existing_glossary_id, schema_version
        FROM glossary_conflicts
        WHERE release_id = ?
        ORDER BY detected_at, conflict_id
        """,
        (release_id,),
    ).fetchall()
    return [_conflict_from_row(row) for row in rows]


def list_locked_entries(conn: sqlite3.Connection, *, release_id: str) -> list[LockedGlossaryEntry]:
    rows = conn.execute(
        """
        SELECT glossary_entry_id, release_id, source_term, normalized_source_term,
               target_term, normalized_target_term, category, status, approved_at,
               approval_run_id, source_candidate_id, schema_version
        FROM locked_glossary
        WHERE release_id = ?
        ORDER BY normalized_source_term, category
        """,
        (release_id,),
    ).fetchall()
    return [_locked_from_row(row) for row in rows]


def promote_locked_entries(
    conn: sqlite3.Connection,
    *,
    entries: Sequence[LockedGlossaryEntry],
) -> None:
    if not entries:
        return
    with conn:
        for entry in entries:
            conn.execute(
                """
                INSERT INTO locked_glossary(
                    glossary_entry_id, release_id, source_term, normalized_source_term,
                    target_term, normalized_target_term, category, status, approved_at,
                    approval_run_id, source_candidate_id, schema_version
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(release_id, normalized_source_term, category)
                DO UPDATE SET
                    target_term = excluded.target_term,
                    normalized_target_term = excluded.normalized_target_term,
                    approval_run_id = excluded.approval_run_id,
                    approved_at = excluded.approved_at,
                    source_candidate_id = excluded.source_candidate_id
                """,
                (
                    entry.glossary_entry_id,
                    entry.release_id,
                    entry.source_term,
                    entry.normalized_source_term,
                    entry.target_term,
                    entry.normalized_target_term,
                    entry.category,
                    entry.status,
                    entry.approved_at,
                    entry.approval_run_id,
                    entry.source_candidate_id,
                    entry.schema_version,
                ),
            )


def find_exact_locked_entry(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    normalized_source_term: str,
    category: str,
) -> LockedGlossaryEntry | None:
    row = conn.execute(
        """
        SELECT glossary_entry_id, release_id, source_term, normalized_source_term,
               target_term, normalized_target_term, category, status, approved_at,
               approval_run_id, source_candidate_id, schema_version
        FROM locked_glossary
        WHERE release_id = ?
          AND normalized_source_term = ?
          AND category = ?
        LIMIT 1
        """,
        (release_id, normalized_source_term, category),
    ).fetchone()
    if row is None:
        return None
    return _locked_from_row(row)

