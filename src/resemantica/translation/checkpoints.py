from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from resemantica.db.sqlite import apply_migrations


@dataclass(slots=True)
class CheckpointRecord:
    release_id: str
    run_id: str
    chapter_number: int
    pass_name: str
    source_hash: str
    prompt_version: str
    status: str
    artifact_path: str
    updated_at: str

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def ensure_checkpoint_schema(conn: sqlite3.Connection) -> None:
    migrations_dir = Path(__file__).resolve().parents[1] / "db" / "migrations"
    apply_migrations(conn, migrations_dir)


def load_checkpoint(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    chapter_number: int,
    pass_name: str,
    source_hash: str,
    prompt_version: str,
) -> CheckpointRecord | None:
    row = conn.execute(
        """
        SELECT release_id, run_id, chapter_number, pass_name,
               source_hash, prompt_version, status, artifact_path, updated_at
        FROM translation_checkpoints
        WHERE release_id = ?
          AND run_id = ?
          AND chapter_number = ?
          AND pass_name = ?
          AND source_hash = ?
          AND prompt_version = ?
        """,
        (release_id, run_id, chapter_number, pass_name, source_hash, prompt_version),
    ).fetchone()
    if row is None:
        return None
    return CheckpointRecord(
        release_id=str(row["release_id"]),
        run_id=str(row["run_id"]),
        chapter_number=int(row["chapter_number"]),
        pass_name=str(row["pass_name"]),
        source_hash=str(row["source_hash"]),
        prompt_version=str(row["prompt_version"]),
        status=str(row["status"]),
        artifact_path=str(row["artifact_path"]),
        updated_at=str(row["updated_at"]),
    )


def save_checkpoint(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    chapter_number: int,
    pass_name: str,
    source_hash: str,
    prompt_version: str,
    status: str,
    artifact_path: str,
) -> CheckpointRecord:
    updated_at = datetime.now(UTC).isoformat()
    with conn:
        conn.execute(
            """
            INSERT INTO translation_checkpoints(
                release_id, run_id, chapter_number, pass_name,
                source_hash, prompt_version, status, artifact_path, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(release_id, run_id, chapter_number, pass_name)
            DO UPDATE SET
                source_hash = excluded.source_hash,
                prompt_version = excluded.prompt_version,
                status = excluded.status,
                artifact_path = excluded.artifact_path,
                updated_at = excluded.updated_at
            """,
            (
                release_id,
                run_id,
                chapter_number,
                pass_name,
                source_hash,
                prompt_version,
                status,
                artifact_path,
                updated_at,
            ),
        )
    return CheckpointRecord(
        release_id=release_id,
        run_id=run_id,
        chapter_number=chapter_number,
        pass_name=pass_name,
        source_hash=source_hash,
        prompt_version=prompt_version,
        status=status,
        artifact_path=artifact_path,
        updated_at=updated_at,
    )

