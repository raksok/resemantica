from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Optional

from resemantica.tracking.models import Event
from resemantica.tracking.repo import ensure_tracking_db, save_event

_EventCallback = Callable[[Event], None]
_subscribers: dict[str, list[_EventCallback]] = defaultdict(list)


def subscribe(event_type: str, callback: _EventCallback) -> None:
    _subscribers[event_type].append(callback)


def unsubscribe(event_type: str, callback: _EventCallback) -> None:
    _subscribers[event_type].remove(callback)


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

    for cb in _subscribers.get(event_type, []):
        cb(event)

    return event
