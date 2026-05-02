from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from resemantica.db.sqlite import ensure_schema


def record_extraction_metadata(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    chapter_result: Any,
) -> None:
    ensure_schema(conn, "extraction")
    now = datetime.now(timezone.utc).isoformat()
    records = list(chapter_result.records)
    placeholder_map_ref = records[0].placeholder_map_ref if records else ""
    with conn:
        conn.execute(
            """
            INSERT INTO extracted_chapters(
                chapter_id, release_id, run_id, chapter_number,
                source_document_path, chapter_source_hash, placeholder_map_ref,
                created_by_stage, validation_status, schema_version,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chapter_id) DO UPDATE SET
                run_id = excluded.run_id,
                source_document_path = excluded.source_document_path,
                chapter_source_hash = excluded.chapter_source_hash,
                placeholder_map_ref = excluded.placeholder_map_ref,
                validation_status = excluded.validation_status,
                updated_at = excluded.updated_at
            """,
            (
                chapter_result.chapter_id,
                release_id,
                run_id,
                chapter_result.chapter_number,
                chapter_result.source_document_path,
                chapter_result.chapter_source_hash,
                placeholder_map_ref,
                "epub-extract",
                "failed" if chapter_result.errors else "success",
                "1.0",
                now,
                now,
            ),
        )
        for record in records:
            payload = asdict(record)
            conn.execute(
                """
                INSERT INTO extracted_blocks(
                    block_id, chapter_id, release_id, run_id, chapter_number,
                    segment_id, parent_block_id, block_order, segment_order,
                    source_text_zh, placeholder_map_ref, chapter_source_hash,
                    schema_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(block_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    source_text_zh = excluded.source_text_zh,
                    placeholder_map_ref = excluded.placeholder_map_ref,
                    chapter_source_hash = excluded.chapter_source_hash,
                    updated_at = excluded.updated_at
                """,
                (
                    payload["block_id"],
                    payload["chapter_id"],
                    release_id,
                    run_id,
                    payload["chapter_number"],
                    payload["segment_id"],
                    payload["parent_block_id"],
                    payload["block_order"],
                    payload["segment_order"],
                    payload["source_text_zh"],
                    payload["placeholder_map_ref"],
                    payload["chapter_source_hash"],
                    str(payload["schema_version"]),
                    now,
                    now,
                ),
            )


def list_chapter_blocks(conn: sqlite3.Connection, *, release_id: str, chapter_number: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM extracted_blocks
        WHERE release_id = ? AND chapter_number = ?
        ORDER BY block_order, COALESCE(segment_order, 0)
        """,
        (release_id, chapter_number),
    ).fetchall()
    return [dict(row) for row in rows]
