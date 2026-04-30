from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Optional

from loguru import logger

from resemantica.tracking.models import Event
from resemantica.tracking.repo import ensure_tracking_db, save_event

_EventCallback = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[_EventCallback]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: _EventCallback) -> None:
        callbacks = self._subscribers[event_type]
        if callback not in callbacks:
            callbacks.append(callback)

    def unsubscribe(self, event_type: str, callback: _EventCallback) -> None:
        callbacks = self._subscribers.get(event_type, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def publish(self, event: Event) -> Event:
        conn = ensure_tracking_db(event.release_id or "")
        try:
            save_event(conn, event)
        finally:
            conn.close()

        callbacks = [
            *self._subscribers.get(event.event_type, []),
            *self._subscribers.get("*", []),
        ]
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                logger.opt(exception=True).warning(
                    "Event subscriber failed for {}", event.event_type
                )
        return event


default_event_bus = EventBus()
_subscribers = default_event_bus._subscribers


def subscribe(event_type: str, callback: _EventCallback) -> None:
    default_event_bus.subscribe(event_type, callback)


def unsubscribe(event_type: str, callback: _EventCallback) -> None:
    default_event_bus.unsubscribe(event_type, callback)


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
    return default_event_bus.publish(event)
