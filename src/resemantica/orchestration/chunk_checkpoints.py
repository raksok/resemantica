from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from resemantica.db.sqlite import ensure_schema


@dataclass(slots=True)
class ChunkCheckpoint:
    release_id: str
    run_id: str
    stage_name: str
    chunk_index: int
    chapter_start: int
    chapter_end: int
    status: str
    metadata: dict[str, Any]
    updated_at: str

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def ensure_chunk_checkpoint_schema(conn: sqlite3.Connection) -> None:
    ensure_schema(conn, "chunk_checkpoints")


def _from_row(row: sqlite3.Row) -> ChunkCheckpoint:
    metadata = json.loads(str(row["metadata_json"] or "{}"))
    if not isinstance(metadata, dict):
        metadata = {}
    return ChunkCheckpoint(
        release_id=str(row["release_id"]),
        run_id=str(row["run_id"]),
        stage_name=str(row["stage_name"]),
        chunk_index=int(row["chunk_index"]),
        chapter_start=int(row["chapter_start"]),
        chapter_end=int(row["chapter_end"]),
        status=str(row["status"]),
        metadata=metadata,
        updated_at=str(row["updated_at"]),
    )


def save_chunk_checkpoint(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    stage_name: str,
    chunk_index: int,
    chapter_start: int,
    chapter_end: int,
    status: str,
    metadata: dict[str, Any] | None = None,
) -> ChunkCheckpoint:
    ensure_chunk_checkpoint_schema(conn)
    updated_at = datetime.now(UTC).isoformat()
    metadata_json = json.dumps(metadata or {}, sort_keys=True)
    with conn:
        conn.execute(
            """
            INSERT INTO chunk_checkpoints(
                release_id, run_id, stage_name, chunk_index,
                chapter_start, chapter_end, status, metadata_json, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(release_id, run_id, stage_name, chunk_index)
            DO UPDATE SET
                chapter_start = excluded.chapter_start,
                chapter_end = excluded.chapter_end,
                status = excluded.status,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                release_id,
                run_id,
                stage_name,
                chunk_index,
                chapter_start,
                chapter_end,
                status,
                metadata_json,
                updated_at,
            ),
        )
    return ChunkCheckpoint(
        release_id=release_id,
        run_id=run_id,
        stage_name=stage_name,
        chunk_index=chunk_index,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
        status=status,
        metadata=metadata or {},
        updated_at=updated_at,
    )


def load_chunk_checkpoint(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    stage_name: str,
    chunk_index: int,
) -> ChunkCheckpoint | None:
    ensure_chunk_checkpoint_schema(conn)
    row = conn.execute(
        """
        SELECT release_id, run_id, stage_name, chunk_index, chapter_start,
               chapter_end, status, metadata_json, updated_at
        FROM chunk_checkpoints
        WHERE release_id = ?
          AND run_id = ?
          AND stage_name = ?
          AND chunk_index = ?
        """,
        (release_id, run_id, stage_name, chunk_index),
    ).fetchone()
    return None if row is None else _from_row(row)


def list_chunk_checkpoints(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    stage_name: str,
) -> list[ChunkCheckpoint]:
    ensure_chunk_checkpoint_schema(conn)
    rows = conn.execute(
        """
        SELECT release_id, run_id, stage_name, chunk_index, chapter_start,
               chapter_end, status, metadata_json, updated_at
        FROM chunk_checkpoints
        WHERE release_id = ?
          AND run_id = ?
          AND stage_name = ?
        ORDER BY chunk_index
        """,
        (release_id, run_id, stage_name),
    ).fetchall()
    return [_from_row(row) for row in rows]


def last_completed_chunk(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    stage_name: str,
) -> ChunkCheckpoint | None:
    ensure_chunk_checkpoint_schema(conn)
    row = conn.execute(
        """
        SELECT release_id, run_id, stage_name, chunk_index, chapter_start,
               chapter_end, status, metadata_json, updated_at
        FROM chunk_checkpoints
        WHERE release_id = ?
          AND run_id = ?
          AND stage_name = ?
          AND status = 'completed'
        ORDER BY chunk_index DESC
        LIMIT 1
        """,
        (release_id, run_id, stage_name),
    ).fetchone()
    return None if row is None else _from_row(row)
