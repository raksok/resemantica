from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Optional

from .models import Event, RunState


def _init_tracking_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS run_state (
            run_id TEXT PRIMARY KEY,
            release_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            checkpoint_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            event_time TEXT NOT NULL,
            run_id TEXT NOT NULL,
            release_id TEXT,
            stage_name TEXT NOT NULL,
            chapter_number INTEGER,
            block_id TEXT,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            schema_version TEXT NOT NULL DEFAULT '1.0'
        );

        CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);
        CREATE INDEX IF NOT EXISTS idx_events_release_id ON events(release_id);
        CREATE INDEX IF NOT EXISTS idx_events_event_time ON events(event_time);
    """)
    conn.commit()


def get_tracking_db_path(release_id: str) -> Path:
    from resemantica.settings import derive_paths, load_config
    cfg = load_config()
    return derive_paths(cfg, release_id=release_id).release_root / "tracking.db"


def ensure_tracking_db(release_id: str) -> sqlite3.Connection:
    db_path = get_tracking_db_path(release_id)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _init_tracking_schema(conn)
    return conn


def save_run_state(conn: sqlite3.Connection, state: RunState) -> None:
    import json
    with conn:
        conn.execute("""
            INSERT INTO run_state(
                run_id, release_id, stage_name, status,
                started_at, finished_at, checkpoint_json, metadata_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                stage_name = excluded.stage_name,
                status = excluded.status,
                finished_at = excluded.finished_at,
                checkpoint_json = excluded.checkpoint_json,
                metadata_json = excluded.metadata_json
        """, (
            state.run_id,
            state.release_id,
            state.stage_name,
            state.status,
            state.started_at,
            state.finished_at,
            json.dumps(state.checkpoint),
            json.dumps(state.metadata),
        ))


def load_run_state(conn: sqlite3.Connection, run_id: str) -> Optional[RunState]:
    import json
    row = conn.execute(
        "SELECT * FROM run_state WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        return None
    return RunState(
        run_id=row["run_id"],
        release_id=row["release_id"],
        stage_name=row["stage_name"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        checkpoint=json.loads(row["checkpoint_json"]),
        metadata=json.loads(row["metadata_json"]),
    )


def save_event(conn: sqlite3.Connection, event: Event) -> None:
    import json
    with conn:
        conn.execute("""
            INSERT INTO events(
                event_id, event_type, event_time, run_id, release_id,
                stage_name, chapter_number, block_id, severity, message,
                payload_json, schema_version
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.event_id,
            event.event_type,
            event.event_time,
            event.run_id,
            event.release_id,
            event.stage_name,
            event.chapter_number,
            event.block_id,
            event.severity,
            event.message,
            json.dumps(event.payload),
            event.schema_version,
        ))


def load_events(
    conn: sqlite3.Connection,
    run_id: Optional[str] = None,
    release_id: Optional[str] = None,
    limit: int = 100,
) -> list[Event]:
    import json
    query = "SELECT * FROM events WHERE 1=1"
    params: list[Any] = []
    if run_id:
        query += " AND run_id = ?"
        params.append(run_id)
    if release_id:
        query += " AND release_id = ?"
        params.append(release_id)
    query += " ORDER BY event_time DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [
        Event(
            event_id=row["event_id"],
            event_type=row["event_type"],
            event_time=row["event_time"],
            run_id=row["run_id"],
            release_id=row["release_id"],
            stage_name=row["stage_name"],
            chapter_number=row["chapter_number"],
            block_id=row["block_id"],
            severity=row["severity"],
            message=row["message"],
            payload=json.loads(row["payload_json"]),
            schema_version=row["schema_version"],
        )
        for row in rows
    ]
