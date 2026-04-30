from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import sqlite3
from typing import Any


def ensure_extraction_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS extracted_chapters (
            chapter_id TEXT PRIMARY KEY,
            release_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            chapter_number INTEGER NOT NULL,
            source_document_path TEXT NOT NULL,
            chapter_source_hash TEXT NOT NULL,
            placeholder_map_ref TEXT NOT NULL,
            created_by_stage TEXT NOT NULL,
            validation_status TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS extracted_blocks (
            block_id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL,
            release_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            chapter_number INTEGER NOT NULL,
            segment_id TEXT,
            parent_block_id TEXT NOT NULL,
            block_order INTEGER NOT NULL,
            segment_order INTEGER,
            source_text_zh TEXT NOT NULL,
            placeholder_map_ref TEXT NOT NULL,
            chapter_source_hash TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_extracted_blocks_release_chapter
            ON extracted_blocks(release_id, chapter_number);
        CREATE INDEX IF NOT EXISTS idx_extracted_chapters_release_run
            ON extracted_chapters(release_id, run_id);
        """
    )
    conn.commit()


class ExtractionRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        ensure_extraction_schema(conn)

    def record_extraction_metadata(
        self,
        *,
        release_id: str,
        run_id: str,
        chapter_result: Any,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        records = list(chapter_result.records)
        placeholder_map_ref = records[0].placeholder_map_ref if records else ""
        with self.conn:
            self.conn.execute(
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
                self.conn.execute(
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

    def list_chapter_blocks(self, *, release_id: str, chapter_number: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM extracted_blocks
            WHERE release_id = ? AND chapter_number = ?
            ORDER BY block_order, COALESCE(segment_order, 0)
            """,
            (release_id, chapter_number),
        ).fetchall()
        return [dict(row) for row in rows]
