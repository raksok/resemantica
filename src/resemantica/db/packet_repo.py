from __future__ import annotations

from pathlib import Path
import sqlite3

from resemantica.db.sqlite import apply_migrations
from resemantica.packets.models import PacketMetadataRecord


def ensure_packet_schema(conn: sqlite3.Connection) -> None:
    migrations_dir = Path(__file__).resolve().parent / "migrations"
    apply_migrations(conn, migrations_dir)


def _metadata_from_row(row: sqlite3.Row) -> PacketMetadataRecord:
    return PacketMetadataRecord(
        packet_id=str(row["packet_id"]),
        release_id=str(row["release_id"]),
        chapter_number=int(row["chapter_number"]),
        run_id=str(row["run_id"]),
        packet_path=str(row["packet_path"]),
        bundle_path=str(row["bundle_path"]),
        packet_hash=str(row["packet_hash"]),
        chapter_source_hash=str(row["chapter_source_hash"]),
        glossary_version_hash=str(row["glossary_version_hash"]),
        summary_version_hash=str(row["summary_version_hash"]),
        graph_snapshot_hash=str(row["graph_snapshot_hash"]),
        idiom_policy_hash=str(row["idiom_policy_hash"]),
        packet_builder_version=str(row["packet_builder_version"]),
        packet_schema_version=int(row["packet_schema_version"]),
        built_at=str(row["built_at"]),
    )


def save_packet_metadata(conn: sqlite3.Connection, *, metadata: PacketMetadataRecord) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO packet_metadata(
                packet_id, release_id, chapter_number, run_id, packet_path, bundle_path,
                packet_hash, chapter_source_hash, glossary_version_hash, summary_version_hash,
                graph_snapshot_hash, idiom_policy_hash, packet_builder_version,
                packet_schema_version, built_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(release_id, chapter_number, packet_hash)
            DO UPDATE SET
                run_id = excluded.run_id,
                packet_path = excluded.packet_path,
                bundle_path = excluded.bundle_path,
                packet_builder_version = excluded.packet_builder_version,
                packet_schema_version = excluded.packet_schema_version,
                built_at = CURRENT_TIMESTAMP
            """,
            (
                metadata.packet_id,
                metadata.release_id,
                metadata.chapter_number,
                metadata.run_id,
                metadata.packet_path,
                metadata.bundle_path,
                metadata.packet_hash,
                metadata.chapter_source_hash,
                metadata.glossary_version_hash,
                metadata.summary_version_hash,
                metadata.graph_snapshot_hash,
                metadata.idiom_policy_hash,
                metadata.packet_builder_version,
                metadata.packet_schema_version,
            ),
        )


def get_latest_packet_metadata(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    chapter_number: int,
) -> PacketMetadataRecord | None:
    row = conn.execute(
        """
        SELECT packet_id, release_id, chapter_number, run_id, packet_path, bundle_path,
               packet_hash, chapter_source_hash, glossary_version_hash, summary_version_hash,
               graph_snapshot_hash, idiom_policy_hash, packet_builder_version,
               packet_schema_version, built_at
        FROM packet_metadata
        WHERE release_id = ?
          AND chapter_number = ?
        ORDER BY built_at DESC, packet_id DESC
        LIMIT 1
        """,
        (release_id, chapter_number),
    ).fetchone()
    if row is None:
        return None
    return _metadata_from_row(row)

