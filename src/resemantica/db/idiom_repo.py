from __future__ import annotations

import hashlib
import sqlite3
from typing import Sequence

from resemantica.db.sqlite import ensure_schema
from resemantica.idioms.models import IdiomCandidate, IdiomConflict, IdiomPolicy, IdiomTranslationVote

_IDIOM_UPSERT_SQL = """
INSERT INTO idiom_candidates(
    candidate_id, release_id, source_text, normalized_source_text,
    meaning_zh, meaning_en, preferred_rendering_en, usage_notes,
    first_seen_chapter, last_seen_chapter, appearance_count,
    evidence_snippet, detection_run_id, candidate_status,
    validation_status, conflict_reason, analyst_model_name,
    analyst_prompt_version, translation_run_id, translator_model_name,
    translator_prompt_version, schema_version, dictionary_match,
    source_strategies, chapter_coverage, corpus_score, context_snippets,
    literal_meaning_zh, idiomatic_meaning_zh, llm_is_idiom,
    llm_usage_type, llm_translation_strategy, llm_reason_code,
    llm_confidence, cluster_id, canonical_source_text, existing_policy_id,
    updated_at
)
VALUES(
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
)
ON CONFLICT(release_id, normalized_source_text)
DO UPDATE SET
    source_text = excluded.source_text,
    meaning_zh = idiom_candidates.meaning_zh,
    meaning_en = idiom_candidates.meaning_en,
    preferred_rendering_en = excluded.preferred_rendering_en,
    usage_notes = excluded.usage_notes,
    first_seen_chapter = MIN(idiom_candidates.first_seen_chapter, excluded.first_seen_chapter),
    last_seen_chapter = MAX(idiom_candidates.last_seen_chapter, excluded.last_seen_chapter),
    appearance_count = idiom_candidates.appearance_count + excluded.appearance_count,
    evidence_snippet = excluded.evidence_snippet,
    detection_run_id = excluded.detection_run_id,
    candidate_status = excluded.candidate_status,
    validation_status = excluded.validation_status,
    conflict_reason = excluded.conflict_reason,
    analyst_model_name = excluded.analyst_model_name,
    analyst_prompt_version = excluded.analyst_prompt_version,
    dictionary_match = excluded.dictionary_match,
    source_strategies = excluded.source_strategies,
    chapter_coverage = excluded.chapter_coverage,
    corpus_score = excluded.corpus_score,
    context_snippets = excluded.context_snippets,
    literal_meaning_zh = excluded.literal_meaning_zh,
    idiomatic_meaning_zh = excluded.idiomatic_meaning_zh,
    llm_is_idiom = excluded.llm_is_idiom,
    llm_usage_type = excluded.llm_usage_type,
    llm_translation_strategy = excluded.llm_translation_strategy,
    llm_reason_code = excluded.llm_reason_code,
    llm_confidence = excluded.llm_confidence,
    cluster_id = excluded.cluster_id,
    canonical_source_text = excluded.canonical_source_text,
    existing_policy_id = excluded.existing_policy_id,
    updated_at = CURRENT_TIMESTAMP
"""

_CANDIDATE_ROW_COLUMNS = """
    candidate_id, release_id, source_text, normalized_source_text,
    meaning_zh, meaning_en, preferred_rendering_en, usage_notes,
    first_seen_chapter, last_seen_chapter, appearance_count,
    evidence_snippet, detection_run_id,
    translation_run_id, candidate_status, validation_status, conflict_reason,
    analyst_model_name, analyst_prompt_version, translator_model_name,
    translator_prompt_version, schema_version,
    dictionary_match, source_strategies, chapter_coverage, corpus_score,
    context_snippets, literal_meaning_zh, idiomatic_meaning_zh,
    llm_is_idiom, llm_usage_type, llm_translation_strategy,
    llm_reason_code, llm_confidence, cluster_id, canonical_source_text,
    existing_policy_id
"""


def ensure_idiom_schema(conn: sqlite3.Connection) -> None:
    ensure_schema(conn, "idioms")


def _candidate_from_row(row: sqlite3.Row) -> IdiomCandidate:
    return IdiomCandidate(
        candidate_id=str(row["candidate_id"]),
        release_id=str(row["release_id"]),
        source_text=str(row["source_text"]),
        normalized_source_text=str(row["normalized_source_text"]),
        meaning_zh=str(row["meaning_zh"]),
        meaning_en=str(row["meaning_en"]),
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
        translator_prompt_version=(
            None if row["translator_prompt_version"] is None else str(row["translator_prompt_version"])
        ),
        schema_version=int(row["schema_version"]),
        dictionary_match=None if row["dictionary_match"] is None else int(row["dictionary_match"]),
        source_strategies=None if row["source_strategies"] is None else str(row["source_strategies"]),
        chapter_coverage=None if row["chapter_coverage"] is None else int(row["chapter_coverage"]),
        corpus_score=None if row["corpus_score"] is None else float(row["corpus_score"]),
        context_snippets=None if row["context_snippets"] is None else str(row["context_snippets"]),
        literal_meaning_zh=None if row["literal_meaning_zh"] is None else str(row["literal_meaning_zh"]),
        idiomatic_meaning_zh=None if row["idiomatic_meaning_zh"] is None else str(row["idiomatic_meaning_zh"]),
        llm_is_idiom=None if row["llm_is_idiom"] is None else int(row["llm_is_idiom"]),
        llm_usage_type=None if row["llm_usage_type"] is None else str(row["llm_usage_type"]),
        llm_translation_strategy=(
            None if row["llm_translation_strategy"] is None else str(row["llm_translation_strategy"])
        ),
        llm_reason_code=None if row["llm_reason_code"] is None else str(row["llm_reason_code"]),
        llm_confidence=None if row["llm_confidence"] is None else float(row["llm_confidence"]),
        cluster_id=None if row["cluster_id"] is None else str(row["cluster_id"]),
        canonical_source_text=None if row["canonical_source_text"] is None else str(row["canonical_source_text"]),
        existing_policy_id=None if row["existing_policy_id"] is None else str(row["existing_policy_id"]),
    )


def _policy_from_row(row: sqlite3.Row) -> IdiomPolicy:
    return IdiomPolicy(
        idiom_id=str(row["idiom_id"]),
        release_id=str(row["release_id"]),
        source_text=str(row["source_text"]),
        normalized_source_text=str(row["normalized_source_text"]),
        meaning_zh=str(row["meaning_zh"]),
        meaning_en=str(row["meaning_en"]),
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


def _vote_from_row(row: sqlite3.Row) -> IdiomTranslationVote:
    return IdiomTranslationVote(
        vote_id=str(row["vote_id"]),
        candidate_id=str(row["candidate_id"]),
        release_id=str(row["release_id"]),
        translation_run_id=str(row["translation_run_id"]),
        model_name=str(row["model_name"]),
        prompt_version=str(row["prompt_version"]),
        vote_kind=str(row["vote_kind"]),
        raw_output=str(row["raw_output"]),
        cleaned_output=str(row["cleaned_output"]),
        normalized_output=str(row["normalized_output"]),
        resolution_status=str(row["resolution_status"]),
        schema_version=int(row["schema_version"]),
    )


def _vote_id(candidate_id: str, translation_run_id: str, model_name: str, vote_kind: str) -> str:
    digest = hashlib.sha256(
        f"{candidate_id}:{translation_run_id}:{model_name}:{vote_kind}".encode("utf-8")
    ).hexdigest()[:24]
    return f"itrv_{digest}"


def upsert_discovered_candidates(
    conn: sqlite3.Connection,
    *,
    candidates: Sequence[IdiomCandidate],
) -> None:
    if not candidates:
        return
    with conn:
        conn.executemany(
            _IDIOM_UPSERT_SQL,
            [
                (
                    candidate.candidate_id,
                    candidate.release_id,
                    candidate.source_text,
                    candidate.normalized_source_text,
                    candidate.meaning_zh,
                    candidate.meaning_en,
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
                    candidate.dictionary_match,
                    candidate.source_strategies,
                    candidate.chapter_coverage,
                    candidate.corpus_score,
                    candidate.context_snippets,
                    candidate.literal_meaning_zh,
                    candidate.idiomatic_meaning_zh,
                    candidate.llm_is_idiom,
                    candidate.llm_usage_type,
                    candidate.llm_translation_strategy,
                    candidate.llm_reason_code,
                    candidate.llm_confidence,
                    candidate.cluster_id,
                    candidate.canonical_source_text,
                    candidate.existing_policy_id,
                )
                for candidate in candidates
            ],
        )


def list_candidates(conn: sqlite3.Connection, *, release_id: str) -> list[IdiomCandidate]:
    rows = conn.execute(
        """
        SELECT candidate_id, release_id, source_text, normalized_source_text,
               meaning_zh, meaning_en, preferred_rendering_en, usage_notes,
               first_seen_chapter, last_seen_chapter, appearance_count,
               evidence_snippet, detection_run_id,
               translation_run_id, candidate_status, validation_status, conflict_reason,
               analyst_model_name, analyst_prompt_version, translator_model_name,
               translator_prompt_version, schema_version,
               dictionary_match, source_strategies, chapter_coverage, corpus_score,
               context_snippets, literal_meaning_zh, idiomatic_meaning_zh,
               llm_is_idiom, llm_usage_type, llm_translation_strategy,
               llm_reason_code, llm_confidence, cluster_id, canonical_source_text,
               existing_policy_id
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
               meaning_zh, meaning_en, preferred_rendering_en, usage_notes,
               first_seen_chapter, last_seen_chapter, appearance_count,
               evidence_snippet, detection_run_id,
               translation_run_id, candidate_status, validation_status, conflict_reason,
                 analyst_model_name, analyst_prompt_version, translator_model_name,
                 translator_prompt_version, schema_version,
                 dictionary_match, source_strategies, chapter_coverage, corpus_score,
                 context_snippets, literal_meaning_zh, idiomatic_meaning_zh,
                 llm_is_idiom, llm_usage_type, llm_translation_strategy,
                 llm_reason_code, llm_confidence, cluster_id, canonical_source_text,
                 existing_policy_id
        FROM idiom_candidates
        WHERE release_id = ?
          AND candidate_status = 'discovered'
          AND (preferred_rendering_en IS NULL OR preferred_rendering_en = '')
        ORDER BY first_seen_chapter, candidate_id
        """,
        (release_id,),
    ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def list_translation_resume_candidate_ids(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    translation_run_id: str,
) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT candidate_id
        FROM idiom_translation_votes
        WHERE release_id = ?
          AND translation_run_id = ?
        ORDER BY candidate_id
        """,
        (release_id, translation_run_id),
    ).fetchall()
    return [str(row["candidate_id"]) for row in rows]


def list_translation_vote_candidate_ids(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    translation_run_id: str,
    model_name: str,
    vote_kind: str,
) -> set[str]:
    rows = conn.execute(
        """
        SELECT candidate_id
        FROM idiom_translation_votes
        WHERE release_id = ?
          AND translation_run_id = ?
          AND model_name = ?
          AND vote_kind = ?
        """,
        (release_id, translation_run_id, model_name, vote_kind),
    ).fetchall()
    return {str(row["candidate_id"]) for row in rows}


def list_existing_translation_vote_candidate_ids(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    translation_run_id: str,
    model_name: str,
    vote_kind: str,
) -> set[str]:
    return list_translation_vote_candidate_ids(
        conn,
        release_id=release_id,
        translation_run_id=translation_run_id,
        model_name=model_name,
        vote_kind=vote_kind,
    )


def count_complete_translation_vote_pairs_by_model(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    translation_run_id: str,
) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT model_name, COUNT(*) AS candidate_count
        FROM (
            SELECT model_name, candidate_id
            FROM idiom_translation_votes
            WHERE release_id = ?
              AND translation_run_id = ?
              AND vote_kind IN ('rendering', 'meaning')
            GROUP BY model_name, candidate_id
            HAVING COUNT(DISTINCT vote_kind) = 2
        )
        GROUP BY model_name
        """,
        (release_id, translation_run_id),
    ).fetchall()
    return {str(row["model_name"]): int(row["candidate_count"]) for row in rows}


def list_candidates_by_ids(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    candidate_ids: Sequence[str],
    untranslated_only: bool = False,
    preserve_input_order: bool = True,
) -> list[IdiomCandidate]:
    if not candidate_ids:
        return []
    placeholders = ",".join("?" for _ in candidate_ids)
    untranslated_clause = ""
    if untranslated_only:
        untranslated_clause = "AND (preferred_rendering_en IS NULL OR preferred_rendering_en = '')"
    rows = conn.execute(
        f"""
        SELECT {_CANDIDATE_ROW_COLUMNS}
        FROM idiom_candidates
        WHERE candidate_id IN ({placeholders})
          -- Keep vote_resume hydration on primary-key lookups; large releases can otherwise scan by release_id.
          AND +release_id = ?
          {untranslated_clause}
        """,
        (*candidate_ids, release_id),
    ).fetchall()
    candidates = [_candidate_from_row(row) for row in rows]
    if preserve_input_order:
        order = {candidate_id: index for index, candidate_id in enumerate(candidate_ids)}
        candidates.sort(key=lambda candidate: order.get(candidate.candidate_id, len(order)))
    else:
        candidates.sort(
            key=lambda candidate: (
                candidate.first_seen_chapter,
                candidate.normalized_source_text,
            )
        )
    return candidates


def save_idiom_translation(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    translation_run_id: str,
    target_term: str,
    meaning_en: str,
    translator_model_name: str,
    translator_prompt_version: str,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE idiom_candidates
            SET preferred_rendering_en = ?,
                meaning_en = ?,
                translation_run_id = ?,
                translator_model_name = ?,
                translator_prompt_version = ?,
                candidate_status = 'translated',
                updated_at = CURRENT_TIMESTAMP
            WHERE candidate_id = ?
            """,
            (
                target_term, meaning_en, translation_run_id,
                translator_model_name, translator_prompt_version, candidate_id,
            ),
        )


def upsert_translation_vote(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    release_id: str,
    translation_run_id: str,
    model_name: str,
    prompt_version: str,
    vote_kind: str,
    raw_output: str,
    cleaned_output: str,
    normalized_output: str,
    resolution_status: str = "pending",
) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO idiom_translation_votes(
                vote_id, candidate_id, release_id, translation_run_id,
                model_name, prompt_version, vote_kind, raw_output,
                cleaned_output, normalized_output, resolution_status,
                schema_version, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(candidate_id, translation_run_id, model_name, vote_kind)
            DO UPDATE SET
                raw_output = excluded.raw_output,
                cleaned_output = excluded.cleaned_output,
                normalized_output = excluded.normalized_output,
                resolution_status = excluded.resolution_status,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                _vote_id(candidate_id, translation_run_id, model_name, vote_kind),
                candidate_id,
                release_id,
                translation_run_id,
                model_name,
                prompt_version,
                vote_kind,
                raw_output,
                cleaned_output,
                normalized_output,
                resolution_status,
            ),
        )


def set_translation_vote_resolution(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    translation_run_id: str,
    vote_kind: str,
    resolution_status: str,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE idiom_translation_votes
            SET resolution_status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE candidate_id = ?
              AND translation_run_id = ?
              AND vote_kind = ?
            """,
            (resolution_status, candidate_id, translation_run_id, vote_kind),
        )


def list_translation_votes(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    candidate_id: str | None = None,
) -> list[IdiomTranslationVote]:
    params: tuple[str, ...]
    where = "WHERE release_id = ?"
    params = (release_id,)
    if candidate_id is not None:
        where += " AND candidate_id = ?"
        params = (release_id, candidate_id)
    rows = conn.execute(
        f"""
        SELECT vote_id, candidate_id, release_id, translation_run_id,
               model_name, prompt_version, vote_kind, raw_output,
               cleaned_output, normalized_output, resolution_status,
               schema_version
        FROM idiom_translation_votes
        {where}
        ORDER BY candidate_id, vote_kind, created_at, model_name
        """,
        params,
    ).fetchall()
    return [_vote_from_row(row) for row in rows]


def list_candidates_for_promotion(
    conn: sqlite3.Connection,
    *,
    release_id: str,
) -> list[IdiomCandidate]:
    rows = conn.execute(
        """
        SELECT candidate_id, release_id, source_text, normalized_source_text,
               meaning_zh, meaning_en, preferred_rendering_en, usage_notes,
               first_seen_chapter, last_seen_chapter, appearance_count,
               evidence_snippet, detection_run_id,
               translation_run_id, candidate_status, validation_status, conflict_reason,
                 analyst_model_name, analyst_prompt_version, translator_model_name,
                 translator_prompt_version, schema_version,
                 dictionary_match, source_strategies, chapter_coverage, corpus_score,
                 context_snippets, literal_meaning_zh, idiomatic_meaning_zh,
                 llm_is_idiom, llm_usage_type, llm_translation_strategy,
                 llm_reason_code, llm_confidence, cluster_id, canonical_source_text,
                 existing_policy_id
        FROM idiom_candidates
        WHERE release_id = ?
          AND candidate_status = 'translated'
        ORDER BY first_seen_chapter, candidate_id
        """,
        (release_id,),
    ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def list_candidates_for_review(
    conn: sqlite3.Connection,
    *,
    release_id: str,
) -> list[IdiomCandidate]:
    rows = conn.execute(
        """
        SELECT candidate_id, release_id, source_text, normalized_source_text,
               meaning_zh, meaning_en, preferred_rendering_en, usage_notes,
               first_seen_chapter, last_seen_chapter, appearance_count,
               evidence_snippet, detection_run_id,
               translation_run_id, candidate_status, validation_status, conflict_reason,
                 analyst_model_name, analyst_prompt_version, translator_model_name,
                 translator_prompt_version, schema_version,
                 dictionary_match, source_strategies, chapter_coverage, corpus_score,
                 context_snippets, literal_meaning_zh, idiomatic_meaning_zh,
                 llm_is_idiom, llm_usage_type, llm_translation_strategy,
                 llm_reason_code, llm_confidence, cluster_id, canonical_source_text,
                 existing_policy_id
        FROM idiom_candidates
        WHERE release_id = ?
          AND (
            candidate_status = 'translated'
            OR EXISTS (
                SELECT 1 FROM idiom_translation_votes v
                WHERE v.candidate_id = idiom_candidates.candidate_id
            )
          )
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
                    meaning_zh, meaning_en, preferred_rendering_en, usage_notes,
                    policy_status, first_seen_chapter, last_seen_chapter,
                    appearance_count, promoted_from_candidate_id, approval_run_id,
                    schema_version, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(release_id, normalized_source_text)
                DO UPDATE SET
                    source_text = excluded.source_text,
                    meaning_zh = excluded.meaning_zh,
                    meaning_en = excluded.meaning_en,
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
                    policy.meaning_en,
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
               meaning_en, preferred_rendering_en, usage_notes, policy_status,
               first_seen_chapter, last_seen_chapter, appearance_count,
               promoted_from_candidate_id, approval_run_id, schema_version
        FROM idiom_policies
        WHERE release_id = ?
        ORDER BY normalized_source_text
        """,
        (release_id,),
    ).fetchall()
    return [_policy_from_row(row) for row in rows]


def set_checkpoint(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    stage_name: str,
) -> None:
    conn.execute(
        """
        INSERT INTO idiom_checkpoints(release_id, run_id, stage_name, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(release_id, run_id) DO UPDATE SET
            stage_name = excluded.stage_name,
            updated_at = CURRENT_TIMESTAMP
        """,
        (release_id, run_id, stage_name),
    )


def get_checkpoint(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
) -> str | None:
    row = conn.execute(
        "SELECT stage_name FROM idiom_checkpoints WHERE release_id = ? AND run_id = ?",
        (release_id, run_id),
    ).fetchone()
    return str(row["stage_name"]) if row else None


def find_exact_policy(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    normalized_source_text: str,
) -> IdiomPolicy | None:
    row = conn.execute(
        """
        SELECT idiom_id, release_id, source_text, normalized_source_text, meaning_zh,
               meaning_en, preferred_rendering_en, usage_notes, policy_status,
               first_seen_chapter, last_seen_chapter, appearance_count,
               promoted_from_candidate_id, approval_run_id, schema_version
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

