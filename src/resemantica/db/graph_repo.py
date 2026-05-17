from __future__ import annotations

import json
import sqlite3
from hashlib import sha256
from typing import Sequence

from resemantica.db.sqlite import ensure_schema
from resemantica.graph.models import DeferredEntityRecord, GraphExtractionDraftRecord, GraphSnapshotRecord


def ensure_graph_schema(conn: sqlite3.Connection) -> None:
    ensure_schema(conn, "graph")


def _deferred_from_row(row: sqlite3.Row) -> DeferredEntityRecord:
    return DeferredEntityRecord(
        deferred_id=str(row["deferred_id"]),
        release_id=str(row["release_id"]),
        term_text=str(row["term_text"]),
        normalized_term_text=str(row["normalized_term_text"]),
        category=str(row["category"]),
        evidence_snippet=str(row["evidence_snippet"]),
        source_chapter=int(row["source_chapter"]),
        last_seen_chapter=int(row["last_seen_chapter"]),
        appearance_count=int(row["appearance_count"]),
        status=str(row["status"]),
        glossary_entry_id=None if row["glossary_entry_id"] is None else str(row["glossary_entry_id"]),
        discovered_at=str(row["discovered_at"]),
        schema_version=int(row["schema_version"]),
    )


def _snapshot_from_row(row: sqlite3.Row) -> GraphSnapshotRecord:
    return GraphSnapshotRecord(
        snapshot_id=str(row["snapshot_id"]),
        release_id=str(row["release_id"]),
        snapshot_hash=str(row["snapshot_hash"]),
        graph_db_path=str(row["graph_db_path"]),
        entity_count=int(row["entity_count"]),
        alias_count=int(row["alias_count"]),
        appearance_count=int(row["appearance_count"]),
        relationship_count=int(row["relationship_count"]),
        created_at=str(row["created_at"]),
        schema_version=int(row["schema_version"]),
    )


def _draft_id(
    *,
    release_id: str,
    run_id: str,
    chapter_number: int,
    chapter_source_hash: str,
    prompt_version: str,
) -> str:
    digest = sha256(
        f"{release_id}:{run_id}:{chapter_number}:{chapter_source_hash}:{prompt_version}".encode("utf-8")
    ).hexdigest()[:24]
    return f"gdr_{digest}"


def _draft_from_row(row: sqlite3.Row) -> GraphExtractionDraftRecord:
    return GraphExtractionDraftRecord(
        draft_id=str(row["draft_id"]),
        release_id=str(row["release_id"]),
        run_id=str(row["run_id"]),
        chapter_number=int(row["chapter_number"]),
        chapter_source_hash=str(row["chapter_source_hash"]),
        prompt_version=str(row["prompt_version"]),
        payload_json=str(row["payload_json"]),
        schema_version=int(row["schema_version"]),
    )


def upsert_deferred_entities(
    conn: sqlite3.Connection,
    *,
    deferred_entities: Sequence[DeferredEntityRecord],
) -> None:
    if not deferred_entities:
        return
    with conn:
        conn.executemany(
            """
            INSERT INTO deferred_entities(
                deferred_id, release_id, term_text, normalized_term_text, category,
                evidence_snippet, source_chapter, last_seen_chapter, appearance_count,
                status, glossary_entry_id, schema_version, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(release_id, normalized_term_text, category)
            DO UPDATE SET
                term_text = excluded.term_text,
                evidence_snippet = excluded.evidence_snippet,
                source_chapter = MIN(deferred_entities.source_chapter, excluded.source_chapter),
                last_seen_chapter = MAX(deferred_entities.last_seen_chapter, excluded.last_seen_chapter),
                appearance_count = deferred_entities.appearance_count + excluded.appearance_count,
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    row.deferred_id,
                    row.release_id,
                    row.term_text,
                    row.normalized_term_text,
                    row.category,
                    row.evidence_snippet,
                    row.source_chapter,
                    row.last_seen_chapter,
                    row.appearance_count,
                    row.status,
                    row.glossary_entry_id,
                    row.schema_version,
                )
                for row in deferred_entities
            ],
        )


def list_deferred_entities(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    status: str | None = None,
) -> list[DeferredEntityRecord]:
    query = """
        SELECT deferred_id, release_id, term_text, normalized_term_text, category,
               evidence_snippet, source_chapter, last_seen_chapter, appearance_count,
               discovered_at, status, glossary_entry_id, schema_version
        FROM deferred_entities
        WHERE release_id = ?
    """
    params: list[str] = [release_id]
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY source_chapter, deferred_id"
    rows = conn.execute(query, tuple(params)).fetchall()
    return [_deferred_from_row(row) for row in rows]


def mark_deferred_promoted(
    conn: sqlite3.Connection,
    *,
    deferred_id: str,
    glossary_entry_id: str,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE deferred_entities
            SET status = 'promoted',
                glossary_entry_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE deferred_id = ?
            """,
            (glossary_entry_id, deferred_id),
        )


def mark_deferred_graph_created(conn: sqlite3.Connection, *, deferred_id: str) -> None:
    with conn:
        conn.execute(
            """
            UPDATE deferred_entities
            SET status = 'graph_created',
                updated_at = CURRENT_TIMESTAMP
            WHERE deferred_id = ?
            """,
            (deferred_id,),
        )


def save_graph_snapshot(conn: sqlite3.Connection, *, snapshot: GraphSnapshotRecord) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO graph_snapshots(
                snapshot_id, release_id, snapshot_hash, graph_db_path,
                entity_count, alias_count, appearance_count, relationship_count,
                schema_version, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(release_id, snapshot_hash)
            DO UPDATE SET
                entity_count = excluded.entity_count,
                alias_count = excluded.alias_count,
                appearance_count = excluded.appearance_count,
                relationship_count = excluded.relationship_count
            """,
            (
                snapshot.snapshot_id,
                snapshot.release_id,
                snapshot.snapshot_hash,
                snapshot.graph_db_path,
                snapshot.entity_count,
                snapshot.alias_count,
                snapshot.appearance_count,
                snapshot.relationship_count,
                snapshot.schema_version,
            ),
        )


def save_graph_extraction_draft(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    chapter_number: int,
    chapter_source_hash: str,
    prompt_version: str,
    payload: dict[str, object],
) -> GraphExtractionDraftRecord:
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    record = GraphExtractionDraftRecord(
        draft_id=_draft_id(
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            chapter_source_hash=chapter_source_hash,
            prompt_version=prompt_version,
        ),
        release_id=release_id,
        run_id=run_id,
        chapter_number=chapter_number,
        chapter_source_hash=chapter_source_hash,
        prompt_version=prompt_version,
        payload_json=payload_json,
        schema_version=1,
    )
    with conn:
        conn.execute(
            """
            INSERT INTO graph_extraction_drafts(
                draft_id, release_id, run_id, chapter_number, chapter_source_hash,
                prompt_version, payload_json, schema_version, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(release_id, run_id, chapter_number, chapter_source_hash, prompt_version)
            DO UPDATE SET
                payload_json = excluded.payload_json,
                schema_version = excluded.schema_version,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                record.draft_id,
                record.release_id,
                record.run_id,
                record.chapter_number,
                record.chapter_source_hash,
                record.prompt_version,
                record.payload_json,
                record.schema_version,
            ),
        )
    return record


def get_graph_extraction_draft(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    chapter_number: int,
    chapter_source_hash: str,
    prompt_version: str,
) -> GraphExtractionDraftRecord | None:
    row = conn.execute(
        """
        SELECT draft_id, release_id, run_id, chapter_number, chapter_source_hash,
               prompt_version, payload_json, schema_version
        FROM graph_extraction_drafts
        WHERE release_id = ?
          AND run_id = ?
          AND chapter_number = ?
          AND chapter_source_hash = ?
          AND prompt_version = ?
        LIMIT 1
        """,
        (release_id, run_id, chapter_number, chapter_source_hash, prompt_version),
    ).fetchone()
    return None if row is None else _draft_from_row(row)


def delete_graph_extraction_drafts(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    chapter_numbers: Sequence[int] | None = None,
) -> None:
    with conn:
        if chapter_numbers is None:
            conn.execute(
                "DELETE FROM graph_extraction_drafts WHERE release_id = ? AND run_id = ?",
                (release_id, run_id),
            )
            return
        numbers = list(chapter_numbers)
        if not numbers:
            return
        placeholders = ",".join("?" for _ in numbers)
        conn.execute(
            f"DELETE FROM graph_extraction_drafts "
            f"WHERE release_id = ? AND run_id = ? AND chapter_number IN ({placeholders})",
            (release_id, run_id, *numbers),
        )


def list_graph_snapshots(conn: sqlite3.Connection, *, release_id: str) -> list[GraphSnapshotRecord]:
    rows = conn.execute(
        """
        SELECT snapshot_id, release_id, snapshot_hash, graph_db_path,
               entity_count, alias_count, appearance_count, relationship_count,
               schema_version, created_at
        FROM graph_snapshots
        WHERE release_id = ?
        ORDER BY created_at, snapshot_id
        """,
        (release_id,),
    ).fetchall()
    return [_snapshot_from_row(row) for row in rows]
