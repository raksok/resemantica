from __future__ import annotations

import sqlite3
from typing import Sequence

from resemantica.db.sqlite import ensure_schema
from resemantica.idioms.models import IdiomCandidate, IdiomConflict, IdiomPolicy


def ensure_idiom_schema(conn: sqlite3.Connection) -> None:
    ensure_schema(conn, "idioms")


def _candidate_from_row(row: sqlite3.Row) -> IdiomCandidate:
    return IdiomCandidate(
        candidate_id=str(row["candidate_id"]),
        release_id=str(row["release_id"]),
        source_text=str(row["source_text"]),
        normalized_source_text=str(row["normalized_source_text"]),
        meaning_zh=str(row["meaning_zh"]),
        preferred_rendering_en=str(row["preferred_rendering_en"]),
        usage_notes=None if row["usage_notes"] is None else str(row["usage_notes"]),
        first_seen_chapter=int(row["first_seen_chapter"]),
        last_seen_chapter=int(row["last_seen_chapter"]),
        appearance_count=int(row["appearance_count"]),
        evidence_snippet=str(row["evidence_snippet"]),
        detection_run_id=str(row["detection_run_id"]),
        candidate_status=str(row["candidate_status"]),
        validation_status=str(row["validation_status"]),
        conflict_reason=None if row["conflict_reason"] is None else str(row["conflict_reason"]),
        analyst_model_name=str(row["analyst_model_name"]),
        analyst_prompt_version=str(row["analyst_prompt_version"]),
        translation_run_id=None if row["translation_run_id"] is None else str(row["translation_run_id"]),
        translator_model_name=None if row["translator_model_name"] is None else str(row["translator_model_name"]),
        translator_prompt_version=None if row["translator_prompt_version"] is None else str(row["translator_prompt_version"]),
        schema_version=int(row["schema_version"]),
    )


def _policy_from_row(row: sqlite3.Row) -> IdiomPolicy:
    return IdiomPolicy(
        idiom_id=str(row["idiom_id"]),
        release_id=str(row["release_id"]),
        source_text=str(row["source_text"]),
        normalized_source_text=str(row["normalized_source_text"]),
        meaning_zh=str(row["meaning_zh"]),
        preferred_rendering_en=str(row["preferred_rendering_en"]),
        usage_notes=None if row["usage_notes"] is None else str(row["usage_notes"]),
        policy_status=str(row["policy_status"]),
        first_seen_chapter=int(row["first_seen_chapter"]),
        last_seen_chapter=int(row["last_seen_chapter"]),
        appearance_count=int(row["appearance_count"]),
        promoted_from_candidate_id=str(row["promoted_from_candidate_id"]),
        approval_run_id=str(row["approval_run_id"]),
        schema_version=int(row["schema_version"]),
    )


def _conflict_from_row(row: sqlite3.Row) -> IdiomConflict:
    return IdiomConflict(
        conflict_id=str(row["conflict_id"]),
        release_id=str(row["release_id"]),
        candidate_id=str(row["candidate_id"]),
        conflict_type=str(row["conflict_type"]),
        conflict_reason=str(row["conflict_reason"]),
        existing_idiom_id=None if row["existing_idiom_id"] is None else str(row["existing_idiom_id"]),
        schema_version=int(row["schema_version"]),
    )


def upsert_discovered_candidates(
    conn: sqlite3.Connection,
    *,
    candidates: Sequence[IdiomCandidate],
) -> None:
    if not candidates:
        return
    with conn:
        conn.executemany(
            """
            INSERT INTO idiom_candidates(
                candidate_id, release_id, source_text, normalized_source_text,
                meaning_zh, preferred_rendering_en, usage_notes,
                first_seen_chapter, last_seen_chapter, appearance_count,
                evidence_snippet, detection_run_id, candidate_status,
                validation_status, conflict_reason, analyst_model_name,
                analyst_prompt_version, translation_run_id, translator_model_name,
                translator_prompt_version, schema_version, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(candidate_id)
            DO UPDATE SET
                source_text = excluded.source_text,
                normalized_source_text = excluded.normalized_source_text,
                meaning_zh = excluded.meaning_zh,
                preferred_rendering_en = excluded.preferred_rendering_en,
                usage_notes = excluded.usage_notes,
                first_seen_chapter = excluded.first_seen_chapter,
                last_seen_chapter = excluded.last_seen_chapter,
                appearance_count = excluded.appearance_count,
                evidence_snippet = excluded.evidence_snippet,
                detection_run_id = excluded.detection_run_id,
                candidate_status = excluded.candidate_status,
                validation_status = excluded.validation_status,
                conflict_reason = excluded.conflict_reason,
                analyst_model_name = excluded.analyst_model_name,
                analyst_prompt_version = excluded.analyst_prompt_version,
                translation_run_id = excluded.translation_run_id,
                translator_model_name = excluded.translator_model_name,
                translator_prompt_version = excluded.translator_prompt_version,
                schema_version = excluded.schema_version,
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    candidate.candidate_id,
                    candidate.release_id,
                    candidate.source_text,
                    candidate.normalized_source_text,
                    candidate.meaning_zh,
                    candidate.preferred_rendering_en,
                    candidate.usage_notes,
                    candidate.first_seen_chapter,
                    candidate.last_seen_chapter,
                    candidate.appearance_count,
                    candidate.evidence_snippet,
                    candidate.detection_run_id,
                    candidate.candidate_status,
                    candidate.validation_status,
                    candidate.conflict_reason,
                    candidate.analyst_model_name,
                    candidate.analyst_prompt_version,
                    candidate.translation_run_id,
                    candidate.translator_model_name,
                    candidate.translator_prompt_version,
                    candidate.schema_version,
                )
                for candidate in candidates
            ],
        )


def list_candidates(conn: sqlite3.Connection, *, release_id: str) -> list[IdiomCandidate]:
    rows = conn.execute(
        """
        SELECT candidate_id, release_id, source_text, normalized_source_text,
               meaning_zh, preferred_rendering_en, usage_notes, first_seen_chapter,
               last_seen_chapter, appearance_count, evidence_snippet, detection_run_id,
               translation_run_id, candidate_status, validation_status, conflict_reason,
               analyst_model_name, analyst_prompt_version, translator_model_name,
               translator_prompt_version, schema_version
        FROM idiom_candidates
        WHERE release_id = ?
        ORDER BY first_seen_chapter, candidate_id
        """,
        (release_id,),
    ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def list_candidates_for_translation(
    conn: sqlite3.Connection,
    *,
    release_id: str,
) -> list[IdiomCandidate]:
    rows = conn.execute(
        """
        SELECT candidate_id, release_id, source_text, normalized_source_text,
               meaning_zh, preferred_rendering_en, usage_notes, first_seen_chapter,
               last_seen_chapter, appearance_count, evidence_snippet, detection_run_id,
               translation_run_id, candidate_status, validation_status, conflict_reason,
                analyst_model_name, analyst_prompt_version, translator_model_name,
                translator_prompt_version, schema_version
        FROM idiom_candidates
        WHERE release_id = ?
          AND candidate_status = 'discovered'
          AND (preferred_rendering_en IS NULL OR preferred_rendering_en = '')
        ORDER BY first_seen_chapter, candidate_id
        """,
        (release_id,),
    ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def save_idiom_translation(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    translation_run_id: str,
    target_term: str,
    translator_model_name: str,
    translator_prompt_version: str,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE idiom_candidates
            SET preferred_rendering_en = ?,
                translation_run_id = ?,
                translator_model_name = ?,
                translator_prompt_version = ?,
                candidate_status = 'translated',
                updated_at = CURRENT_TIMESTAMP
            WHERE candidate_id = ?
            """,
            (target_term, translation_run_id, translator_model_name, translator_prompt_version, candidate_id),
        )


def list_candidates_for_promotion(
    conn: sqlite3.Connection,
    *,
    release_id: str,
) -> list[IdiomCandidate]:
    rows = conn.execute(
        """
        SELECT candidate_id, release_id, source_text, normalized_source_text,
               meaning_zh, preferred_rendering_en, usage_notes, first_seen_chapter,
               last_seen_chapter, appearance_count, evidence_snippet, detection_run_id,
               translation_run_id, candidate_status, validation_status, conflict_reason,
                analyst_model_name, analyst_prompt_version, translator_model_name,
                translator_prompt_version, schema_version
        FROM idiom_candidates
        WHERE release_id = ?
          AND candidate_status = 'translated'
        ORDER BY first_seen_chapter, candidate_id
        """,
        (release_id,),
    ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def mark_candidate_conflict(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    conflict_reason: str,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE idiom_candidates
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
            UPDATE idiom_candidates
            SET candidate_status = 'approved',
                validation_status = 'approved',
                conflict_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE candidate_id = ?
            """,
            (candidate_id,),
        )


def insert_conflicts(conn: sqlite3.Connection, *, conflicts: Sequence[IdiomConflict]) -> None:
    if not conflicts:
        return
    with conn:
        conn.executemany(
            """
            INSERT INTO idiom_conflicts(
                conflict_id, release_id, candidate_id, conflict_type,
                conflict_reason, existing_idiom_id, schema_version, detected_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(conflict_id)
            DO UPDATE SET
                conflict_reason = excluded.conflict_reason,
                existing_idiom_id = excluded.existing_idiom_id,
                detected_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    conflict.conflict_id,
                    conflict.release_id,
                    conflict.candidate_id,
                    conflict.conflict_type,
                    conflict.conflict_reason,
                    conflict.existing_idiom_id,
                    conflict.schema_version,
                )
                for conflict in conflicts
            ],
        )


def list_conflicts(conn: sqlite3.Connection, *, release_id: str) -> list[IdiomConflict]:
    rows = conn.execute(
        """
        SELECT conflict_id, release_id, candidate_id, conflict_type,
               conflict_reason, existing_idiom_id, schema_version
        FROM idiom_conflicts
        WHERE release_id = ?
        ORDER BY detected_at, conflict_id
        """,
        (release_id,),
    ).fetchall()
    return [_conflict_from_row(row) for row in rows]


def promote_policies(conn: sqlite3.Connection, *, policies: Sequence[IdiomPolicy]) -> None:
    if not policies:
        return
    with conn:
        for policy in policies:
            conn.execute(
                """
                INSERT INTO idiom_policies(
                    idiom_id, release_id, source_text, normalized_source_text,
                    meaning_zh, preferred_rendering_en, usage_notes, policy_status,
                    first_seen_chapter, last_seen_chapter, appearance_count,
                    promoted_from_candidate_id, approval_run_id, schema_version, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(release_id, normalized_source_text)
                DO UPDATE SET
                    source_text = excluded.source_text,
                    meaning_zh = excluded.meaning_zh,
                    preferred_rendering_en = excluded.preferred_rendering_en,
                    usage_notes = excluded.usage_notes,
                    policy_status = excluded.policy_status,
                    first_seen_chapter = MIN(idiom_policies.first_seen_chapter, excluded.first_seen_chapter),
                    last_seen_chapter = MAX(idiom_policies.last_seen_chapter, excluded.last_seen_chapter),
                    appearance_count = excluded.appearance_count,
                    promoted_from_candidate_id = excluded.promoted_from_candidate_id,
                    approval_run_id = excluded.approval_run_id,
                    schema_version = excluded.schema_version,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    policy.idiom_id,
                    policy.release_id,
                    policy.source_text,
                    policy.normalized_source_text,
                    policy.meaning_zh,
                    policy.preferred_rendering_en,
                    policy.usage_notes,
                    policy.policy_status,
                    policy.first_seen_chapter,
                    policy.last_seen_chapter,
                    policy.appearance_count,
                    policy.promoted_from_candidate_id,
                    policy.approval_run_id,
                    policy.schema_version,
                ),
            )


def list_policies(conn: sqlite3.Connection, *, release_id: str) -> list[IdiomPolicy]:
    rows = conn.execute(
        """
        SELECT idiom_id, release_id, source_text, normalized_source_text, meaning_zh,
               preferred_rendering_en, usage_notes, policy_status, first_seen_chapter,
               last_seen_chapter, appearance_count, promoted_from_candidate_id,
               approval_run_id, schema_version
        FROM idiom_policies
        WHERE release_id = ?
        ORDER BY normalized_source_text
        """,
        (release_id,),
    ).fetchall()
    return [_policy_from_row(row) for row in rows]


def find_exact_policy(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    normalized_source_text: str,
) -> IdiomPolicy | None:
    row = conn.execute(
        """
        SELECT idiom_id, release_id, source_text, normalized_source_text, meaning_zh,
               preferred_rendering_en, usage_notes, policy_status, first_seen_chapter,
               last_seen_chapter, appearance_count, promoted_from_candidate_id,
               approval_run_id, schema_version
        FROM idiom_policies
        WHERE release_id = ?
          AND normalized_source_text = ?
        LIMIT 1
        """,
        (release_id, normalized_source_text),
    ).fetchone()
    if row is None:
        return None
    return _policy_from_row(row)

