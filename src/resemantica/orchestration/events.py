from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Optional

from loguru import logger

from resemantica.settings import EventsConfig, load_config
from resemantica.tracking.models import Event
from resemantica.tracking.repo import ensure_tracking_db, save_event

_EventCallback = Callable[[Event], None]

_STANDARD_TYPE_ALIASES: dict[str, str] = {
    "stage_started": "orchestration.stage_started",
    "stage_completed": "orchestration.stage_completed",
    "stage_failed": "orchestration.stage_failed",
    "stage_stopped": "orchestration.stage_stopped",
    "run_finalized": "orchestration.run_finalized",
    "paragraph_started": "translate.paragraph_started",
    "paragraph_completed": "translate.paragraph_completed",
    "risk_detected": "translate.risk_detected",
}


class EventBus:
    def __init__(
        self,
        *,
        persistence_mode: str | None = None,
        progress_sample_every: int | None = None,
    ) -> None:
        self._subscribers: dict[str, list[_EventCallback]] = defaultdict(list)
        self._persistence_mode = persistence_mode
        self._progress_sample_every = progress_sample_every
        self._progress_counts: dict[tuple[str, str], int] = defaultdict(int)

    def subscribe(self, event_type: str, callback: _EventCallback) -> None:
        callbacks = self._subscribers[event_type]
        if callback not in callbacks:
            callbacks.append(callback)

    def unsubscribe(self, event_type: str, callback: _EventCallback) -> None:
        callbacks = self._subscribers.get(event_type, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def publish(self, event: Event) -> Event:
        if self._should_persist(event):
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
                logger.opt(exception=True).error(
                    "Event subscriber {} failed for {}", callback.__name__, event.event_type
                )
        return event

    def _events_config(self) -> EventsConfig:
        if self._persistence_mode is not None and self._progress_sample_every is not None:
            return EventsConfig(
                persistence_mode=self._persistence_mode,
                progress_sample_every=self._progress_sample_every,
            )
        try:
            return load_config().events
        except Exception:
            return EventsConfig()

    def _should_persist(self, event: Event) -> bool:
        config = self._events_config()
        if config.persistence_mode == "normal":
            return True
        if _is_critical_event(event):
            return True
        if not _is_sampled_progress_event(event.event_type):
            return True

        key = (event.run_id, event.event_type)
        self._progress_counts[key] += 1
        count = self._progress_counts[key]
        return count == 1 or count % config.progress_sample_every == 0


def _is_critical_event(event: Event) -> bool:
    event_type = event.event_type
    if event.severity in {"warning", "error"}:
        return True
    if event_type in {"validation_failed", "risk_detected"}:
        return True
    if event_type.endswith("_failed") or event_type.endswith(".failed"):
        return True
    if event_type.endswith("_stopped") or event_type.endswith(".stopped"):
        return True
    if event_type.endswith("_skipped") or event_type.endswith(".chapter_skipped"):
        return True
    if event_type.endswith("_artifact_written") or event_type.endswith(".artifact_written"):
        return True
    if _is_sampled_progress_event(event_type):
        return False
    return (
        event_type.endswith("_started")
        or event_type.endswith("_completed")
        or event_type.endswith(".started")
        or event_type.endswith(".completed")
    )


def _is_sampled_progress_event(event_type: str) -> bool:
    return (
        ".paragraph_" in event_type
        or ".chapter_" in event_type
        or event_type in {"paragraph_started", "paragraph_completed", "chapter_started", "chapter_completed"}
    )


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
    result = default_event_bus.publish(event)

    alias = _STANDARD_TYPE_ALIASES.get(event_type)
    if alias is not None:
        alias_event = Event(
            event_type=alias,
            run_id=run_id,
            release_id=release_id,
            stage_name=stage_name,
            severity=severity,
            message=message,
            chapter_number=chapter_number,
            block_id=block_id,
            payload=payload or {},
        )
        default_event_bus.publish(alias_event)

    _loguru_level = {"error": "ERROR", "warning": "WARNING"}.get(severity, "DEBUG")
    logger.log(
        _loguru_level,
        "[{}] {} | {}",
        event_type,
        stage_name,
        message,
        event_type=event_type,
        stage_name=stage_name,
        chapter_number=chapter_number,
        block_id=block_id,
        run_id=run_id,
        release_id=release_id,
    )

    return result
