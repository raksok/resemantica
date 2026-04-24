from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Sequence

from resemantica.db.sqlite import apply_migrations
from resemantica.graph.models import DeferredEntityRecord, GraphSnapshotRecord


def ensure_graph_schema(conn: sqlite3.Connection) -> None:
    migrations_dir = Path(__file__).resolve().parent / "migrations"
    apply_migrations(conn, migrations_dir)


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

