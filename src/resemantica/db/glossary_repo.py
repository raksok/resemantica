from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Sequence

from resemantica.db.sqlite import ensure_schema
from resemantica.glossary.candidate_gen import RawCandidate
from resemantica.glossary.models import (
    AliasCluster,
    GlossaryCandidate,
    GlossaryConflict,
    GlossaryTranslationVote,
    LockedGlossaryEntry,
)


@dataclass(frozen=True, slots=True)
class GlossaryDiscoveryChapterState:
    release_id: str
    run_id: str
    chapter_number: int
    chapter_source_hash: str
    input_hash: str
    status: str
    skip_reason: str | None
    raw_candidates: list[RawCandidate]
    candidate_count: int


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
        pos_tags=(None if row["pos_tags"] is None else str(row["pos_tags"])),
        ner_label=(None if row["ner_label"] is None else str(row["ner_label"])),
        type_prior=(None if row["type_prior"] is None else str(row["type_prior"])),
        source_strategies=(None if row["source_strategies"] is None else str(row["source_strategies"])),
        chapter_coverage=(None if row["chapter_coverage"] is None else int(row["chapter_coverage"])),
        corpus_score=(None if row["corpus_score"] is None else float(row["corpus_score"])),
        context_snippets=(None if row["context_snippets"] is None else str(row["context_snippets"])),
        llm_keep=(None if row["llm_keep"] is None else int(row["llm_keep"])),
        llm_type=(None if row["llm_type"] is None else str(row["llm_type"])),
        llm_reason_code=(None if row["llm_reason_code"] is None else str(row["llm_reason_code"])),
        llm_confidence=(None if row["llm_confidence"] is None else float(row["llm_confidence"])),
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


def _vote_from_row(row: sqlite3.Row) -> GlossaryTranslationVote:
    return GlossaryTranslationVote(
        vote_id=str(row["vote_id"]),
        candidate_id=str(row["candidate_id"]),
        release_id=str(row["release_id"]),
        translation_run_id=str(row["translation_run_id"]),
        model_name=str(row["model_name"]),
        prompt_version=str(row["prompt_version"]),
        raw_output=str(row["raw_output"]),
        cleaned_output=str(row["cleaned_output"]),
        normalized_output=str(row["normalized_output"]),
        resolution_status=str(row["resolution_status"]),
        schema_version=int(row["schema_version"]),
    )


def _vote_id(candidate_id: str, translation_run_id: str, model_name: str) -> str:
    digest = hashlib.sha256(f"{candidate_id}:{translation_run_id}:{model_name}".encode("utf-8")).hexdigest()[:24]
    return f"gtrv_{digest}"


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
                translator_model_name, translator_prompt_version, schema_version,
                pos_tags, ner_label, type_prior, source_strategies, chapter_coverage,
                corpus_score, context_snippets, llm_keep, llm_type, llm_reason_code, llm_confidence,
                updated_at
            )
            VALUES(
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
            )
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
                pos_tags = excluded.pos_tags,
                ner_label = excluded.ner_label,
                type_prior = excluded.type_prior,
                source_strategies = excluded.source_strategies,
                chapter_coverage = excluded.chapter_coverage,
                corpus_score = excluded.corpus_score,
                context_snippets = excluded.context_snippets,
                llm_keep = excluded.llm_keep,
                llm_type = excluded.llm_type,
                llm_reason_code = excluded.llm_reason_code,
                llm_confidence = excluded.llm_confidence,
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
                    candidate.pos_tags,
                    candidate.ner_label,
                    candidate.type_prior,
                    candidate.source_strategies,
                    candidate.chapter_coverage,
                    candidate.corpus_score,
                    candidate.context_snippets,
                    candidate.llm_keep,
                    candidate.llm_type,
                    candidate.llm_reason_code,
                    candidate.llm_confidence,
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
               translator_model_name, translator_prompt_version, schema_version,
               pos_tags, ner_label, type_prior, source_strategies, chapter_coverage,
               corpus_score, context_snippets, llm_keep, llm_type, llm_reason_code, llm_confidence
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
               translator_model_name, translator_prompt_version, schema_version,
               pos_tags, ner_label, type_prior, source_strategies, chapter_coverage,
               corpus_score, context_snippets, llm_keep, llm_type, llm_reason_code, llm_confidence
        FROM glossary_candidates
        WHERE release_id = ?
          AND (candidate_translation_en IS NULL OR candidate_translation_en = '')
          AND llm_keep = 1
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
               translator_model_name, translator_prompt_version, schema_version,
               pos_tags, ner_label, type_prior, source_strategies, chapter_coverage,
               corpus_score, context_snippets, llm_keep, llm_type, llm_reason_code, llm_confidence
        FROM glossary_candidates
        WHERE release_id = ?
          AND candidate_translation_en IS NOT NULL
          AND candidate_translation_en != ''
          AND candidate_status != 'promoted'
          AND llm_keep = 1
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
               translator_model_name, translator_prompt_version, schema_version,
               pos_tags, ner_label, type_prior, source_strategies, chapter_coverage,
               corpus_score, context_snippets, llm_keep, llm_type, llm_reason_code, llm_confidence
        FROM glossary_candidates
        WHERE release_id = ?
          AND (
            candidate_status = 'translated'
            OR EXISTS (
                SELECT 1 FROM glossary_translation_votes v
                WHERE v.candidate_id = glossary_candidates.candidate_id
            )
          )
        ORDER BY first_seen_chapter, normalized_source_term, category
        """,
        (release_id,),
    ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def upsert_translation_vote(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    release_id: str,
    translation_run_id: str,
    model_name: str,
    prompt_version: str,
    raw_output: str,
    cleaned_output: str,
    normalized_output: str,
    resolution_status: str = "pending",
) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO glossary_translation_votes(
                vote_id, candidate_id, release_id, translation_run_id,
                model_name, prompt_version, raw_output, cleaned_output,
                normalized_output, resolution_status, schema_version, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(candidate_id, translation_run_id, model_name)
            DO UPDATE SET
                raw_output = excluded.raw_output,
                cleaned_output = excluded.cleaned_output,
                normalized_output = excluded.normalized_output,
                resolution_status = excluded.resolution_status,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                _vote_id(candidate_id, translation_run_id, model_name),
                candidate_id,
                release_id,
                translation_run_id,
                model_name,
                prompt_version,
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
    resolution_status: str,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE glossary_translation_votes
            SET resolution_status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE candidate_id = ?
              AND translation_run_id = ?
            """,
            (resolution_status, candidate_id, translation_run_id),
        )


def list_translation_votes(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    candidate_id: str | None = None,
) -> list[GlossaryTranslationVote]:
    params: tuple[str, ...]
    where = "WHERE release_id = ?"
    params = (release_id,)
    if candidate_id is not None:
        where += " AND candidate_id = ?"
        params = (release_id, candidate_id)
    rows = conn.execute(
        f"""
        SELECT vote_id, candidate_id, release_id, translation_run_id,
               model_name, prompt_version, raw_output, cleaned_output,
               normalized_output, resolution_status, schema_version
        FROM glossary_translation_votes
        {where}
        ORDER BY candidate_id, created_at, model_name
        """,
        params,
    ).fetchall()
    return [_vote_from_row(row) for row in rows]


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


def _cluster_id(release_id: str, canonical_id: str) -> str:
    digest = hashlib.sha256(f"{release_id}:{canonical_id}".encode("utf-8")).hexdigest()[:24]
    return f"gclus_{digest}"


def upsert_alias_clusters(
    conn: sqlite3.Connection,
    *,
    clusters: Sequence[AliasCluster],
    release_id: str,
    discovery_run_id: str,
) -> None:
    if not clusters:
        return
    with conn:
        conn.executemany(
            """
            INSERT INTO glossary_alias_clusters(
                cluster_id, release_id, canonical_candidate_id, canonical_term,
                aliases_json, member_ids_json, similarity_score, existing_glossary_match,
                discovery_run_id, schema_version
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(release_id, canonical_candidate_id)
            DO UPDATE SET
                canonical_term = excluded.canonical_term,
                aliases_json = excluded.aliases_json,
                member_ids_json = excluded.member_ids_json,
                similarity_score = excluded.similarity_score,
                existing_glossary_match = excluded.existing_glossary_match,
                discovery_run_id = excluded.discovery_run_id
            """,
            [
                (
                    _cluster_id(release_id, c.canonical_id),
                    release_id,
                    c.canonical_id,
                    c.canonical_term,
                    json.dumps(c.aliases, ensure_ascii=False),
                    json.dumps(c.member_ids, ensure_ascii=False),
                    c.similarity_score,
                    c.existing_glossary_match,
                    discovery_run_id,
                    1,
                )
                for c in clusters
            ]
        )


def clear_alias_clusters_for_run(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    discovery_run_id: str,
) -> None:
    conn.execute(
        "DELETE FROM glossary_alias_clusters WHERE release_id = ? AND discovery_run_id = ?",
        (release_id, discovery_run_id),
    )


def replace_candidates(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    discovery_run_id: str,
    candidates: Sequence[GlossaryCandidate],
) -> None:
    """Replace ALL candidates for a release/run (used for checkpoint writes).
    Deletes existing entries first to avoid double-counting appearance_count."""
    with conn:
        conn.execute(
            "DELETE FROM glossary_candidates WHERE release_id = ? AND discovery_run_id = ?",
            (release_id, discovery_run_id),
        )
        if not candidates:
            return
        conn.executemany(
            """
            INSERT OR REPLACE INTO glossary_candidates(
                candidate_id, release_id, source_term, normalized_source_term,
                category, source_language, first_seen_chapter, last_seen_chapter,
                appearance_count, evidence_snippet, candidate_translation_en,
                normalized_target_term, discovery_run_id, translation_run_id,
                candidate_status, validation_status, conflict_reason, critic_score,
                analyst_model_name, analyst_prompt_version,
                translator_model_name, translator_prompt_version, schema_version,
                pos_tags, ner_label, type_prior, source_strategies, chapter_coverage,
                corpus_score, context_snippets, llm_keep, llm_type, llm_reason_code, llm_confidence,
                updated_at
            )
            VALUES(
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
            )
            """,
            [
                (
                    c.candidate_id, c.release_id, c.source_term, c.normalized_source_term,
                    c.category, c.source_language, c.first_seen_chapter, c.last_seen_chapter,
                    c.appearance_count, c.evidence_snippet, c.candidate_translation_en,
                    c.normalized_target_term, c.discovery_run_id, c.translation_run_id,
                    c.candidate_status, c.validation_status, c.conflict_reason, c.critic_score,
                    c.analyst_model_name, c.analyst_prompt_version,
                    c.translator_model_name, c.translator_prompt_version, c.schema_version,
                    c.pos_tags, c.ner_label, c.type_prior, c.source_strategies, c.chapter_coverage,
                    c.corpus_score, c.context_snippets, c.llm_keep, c.llm_type, c.llm_reason_code, c.llm_confidence,
                )
                for c in candidates
            ],
        )


def update_candidate_llm_fields(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    llm_keep: bool,
    llm_type: str,
    llm_reason_code: str,
    llm_confidence: float,
    candidate_status: str | None = None,
) -> None:
    """Update LLM evaluation fields for a single candidate."""
    if candidate_status is None:
        conn.execute(
            """
            UPDATE glossary_candidates
            SET llm_keep = ?, llm_type = ?, llm_reason_code = ?, llm_confidence = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE candidate_id = ?
            """,
            (1 if llm_keep else 0, llm_type, llm_reason_code, llm_confidence, candidate_id),
        )
        return
    conn.execute(
        """
        UPDATE glossary_candidates
        SET llm_keep = ?, llm_type = ?, llm_reason_code = ?, llm_confidence = ?,
            candidate_status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE candidate_id = ?
        """,
        (
            1 if llm_keep else 0,
            llm_type,
            llm_reason_code,
            llm_confidence,
            candidate_status,
            candidate_id,
        ),
    )


def _raw_candidate_to_dict(candidate: RawCandidate) -> dict[str, object]:
    return {
        "surface_form": candidate.surface_form,
        "normalized_form": candidate.normalized_form,
        "pos_tags": list(candidate.pos_tags),
        "ner_label": candidate.ner_label,
        "type_prior": candidate.type_prior,
        "strategies": sorted(candidate.strategies),
        "appearances": candidate.appearances,
        "context_snippets": list(candidate.context_snippets),
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _raw_candidate_from_dict(data: dict[str, object]) -> RawCandidate:
    appearances_raw = data.get("appearances", 1)
    return RawCandidate(
        surface_form=str(data["surface_form"]),
        normalized_form=str(data["normalized_form"]),
        pos_tags=_string_list(data.get("pos_tags", [])),
        ner_label=(None if data.get("ner_label") is None else str(data["ner_label"])),
        type_prior=str(data["type_prior"]),
        strategies=set(_string_list(data.get("strategies", []))),
        appearances=int(appearances_raw) if isinstance(appearances_raw, int | str | float) else 1,
        context_snippets=_string_list(data.get("context_snippets", [])),
    )


def serialize_raw_candidates(candidates: Sequence[RawCandidate]) -> str:
    return json.dumps(
        [_raw_candidate_to_dict(candidate) for candidate in candidates],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def deserialize_raw_candidates(raw_candidates_json: str) -> list[RawCandidate]:
    raw_rows = json.loads(raw_candidates_json)
    if not isinstance(raw_rows, list):
        raise ValueError("raw candidate state must be a list")
    return [_raw_candidate_from_dict(row) for row in raw_rows if isinstance(row, dict)]


def save_discovery_chapter_state(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    chapter_number: int,
    chapter_source_hash: str,
    input_hash: str,
    status: str,
    raw_candidates: Sequence[RawCandidate],
    skip_reason: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO glossary_discovery_chapter_state(
            release_id, run_id, chapter_number, chapter_source_hash, input_hash,
            status, skip_reason, raw_candidates_json, candidate_count, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(release_id, run_id, chapter_number)
        DO UPDATE SET
            chapter_source_hash = excluded.chapter_source_hash,
            input_hash = excluded.input_hash,
            status = excluded.status,
            skip_reason = excluded.skip_reason,
            raw_candidates_json = excluded.raw_candidates_json,
            candidate_count = excluded.candidate_count,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            release_id,
            run_id,
            chapter_number,
            chapter_source_hash,
            input_hash,
            status,
            skip_reason,
            serialize_raw_candidates(raw_candidates),
            len(raw_candidates),
        ),
    )


def load_valid_discovery_chapter_state(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    chapter_number: int,
    chapter_source_hash: str,
    input_hash: str,
) -> GlossaryDiscoveryChapterState | None:
    row = conn.execute(
        """
        SELECT release_id, run_id, chapter_number, chapter_source_hash, input_hash,
               status, skip_reason, raw_candidates_json, candidate_count
        FROM glossary_discovery_chapter_state
        WHERE release_id = ?
          AND run_id = ?
          AND chapter_number = ?
          AND chapter_source_hash = ?
          AND input_hash = ?
          AND status IN ('completed', 'skipped')
        """,
        (release_id, run_id, chapter_number, chapter_source_hash, input_hash),
    ).fetchone()
    if row is None:
        return None
    return GlossaryDiscoveryChapterState(
        release_id=str(row["release_id"]),
        run_id=str(row["run_id"]),
        chapter_number=int(row["chapter_number"]),
        chapter_source_hash=str(row["chapter_source_hash"]),
        input_hash=str(row["input_hash"]),
        status=str(row["status"]),
        skip_reason=(None if row["skip_reason"] is None else str(row["skip_reason"])),
        raw_candidates=deserialize_raw_candidates(str(row["raw_candidates_json"])),
        candidate_count=int(row["candidate_count"]),
    )


def list_reusable_discovery_chapter_states(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
) -> list[GlossaryDiscoveryChapterState]:
    rows = conn.execute(
        """
        SELECT release_id, run_id, chapter_number, chapter_source_hash, input_hash,
               status, skip_reason, raw_candidates_json, candidate_count
        FROM glossary_discovery_chapter_state
        WHERE release_id = ?
          AND run_id = ?
          AND status IN ('completed', 'skipped')
        ORDER BY chapter_number
        """,
        (release_id, run_id),
    ).fetchall()
    return [
        GlossaryDiscoveryChapterState(
            release_id=str(row["release_id"]),
            run_id=str(row["run_id"]),
            chapter_number=int(row["chapter_number"]),
            chapter_source_hash=str(row["chapter_source_hash"]),
            input_hash=str(row["input_hash"]),
            status=str(row["status"]),
            skip_reason=(None if row["skip_reason"] is None else str(row["skip_reason"])),
            raw_candidates=deserialize_raw_candidates(str(row["raw_candidates_json"])),
            candidate_count=int(row["candidate_count"]),
        )
        for row in rows
    ]


def clear_discovery_chapter_state(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
) -> None:
    conn.execute(
        "DELETE FROM glossary_discovery_chapter_state WHERE release_id = ? AND run_id = ?",
        (release_id, run_id),
    )


def set_checkpoint(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    stage_name: str,
    input_hash: str = "",
) -> None:
    """Record that a stage completed successfully."""
    conn.execute(
        """
        INSERT INTO glossary_checkpoints(release_id, run_id, stage_name, input_hash, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(release_id, run_id) DO UPDATE SET
            stage_name = excluded.stage_name,
            input_hash = excluded.input_hash,
            updated_at = CURRENT_TIMESTAMP
        """,
        (release_id, run_id, stage_name, input_hash),
    )


def get_checkpoint(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    input_hash: str | None = None,
) -> str | None:
    """Return the last completed stage name, or None if no checkpoint."""
    row = conn.execute(
        "SELECT stage_name, input_hash FROM glossary_checkpoints WHERE release_id = ? AND run_id = ?",
        (release_id, run_id),
    ).fetchone()
    if row is None:
        return None
    if input_hash is not None and str(row["input_hash"]) != input_hash:
        return None
    return str(row["stage_name"])


def list_alias_clusters(
    conn: sqlite3.Connection,
    *,
    release_id: str,
) -> list[AliasCluster]:
    rows = conn.execute(
        """
        SELECT canonical_candidate_id, canonical_term, aliases_json,
               member_ids_json, similarity_score, existing_glossary_match
        FROM glossary_alias_clusters
        WHERE release_id = ?
        ORDER BY similarity_score DESC
        """,
        (release_id,),
    ).fetchall()

    return [
        AliasCluster(
            canonical_id=str(row["canonical_candidate_id"]),
            canonical_term=str(row["canonical_term"]),
            aliases=json.loads(row["aliases_json"]),
            member_ids=json.loads(row["member_ids_json"]),
            similarity_score=float(row["similarity_score"]),
            existing_glossary_match=(
                None if row["existing_glossary_match"] is None else str(row["existing_glossary_match"])
            ),
        )
        for row in rows
    ]

