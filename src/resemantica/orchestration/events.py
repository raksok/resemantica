from __future__ import annotations

from typing import Any, Optional

from resemantica.tracking.models import Event
from resemantica.tracking.repo import ensure_tracking_db, save_event


def emit_event(
    run_id: str,
    release_id: str,
    event_type: str,
    stage_name: str,
    *,
    severity: str = "info",
    message: str = "",
    chapter_number: Optional[int] = None,
    block_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> Event:
    event = Event(
        event_type=event_type,
        run_id=run_id,
        release_id=release_id,
        stage_name=stage_name,
        severity=severity,
        message=message,
        chapter_number=chapter_number,
        block_id=block_id,
        payload=payload or {},
    )
    conn = ensure_tracking_db(release_id)
    try:
        save_event(conn, event)
    finally:
        conn.close()
    return event
