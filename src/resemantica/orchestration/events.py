from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Optional

from loguru import logger

from resemantica.settings import EventsConfig, load_config
from resemantica.tracking.models import Event
from resemantica.tracking.repo import ensure_tracking_db, save_event

_EventCallback = Callable[[Event], None]

_STAGE_LABELS: dict[str, str] = {
    "epub-extract": "EPUB extraction",
    "epub-rebuild": "EPUB rebuild",
    "packets-build": "Packet build",
    "preprocess-glossary": "Glossary preprocessing",
    "preprocess-glossary.discover": "Glossary discovery",
    "preprocess-glossary.translate": "Glossary translation",
    "preprocess-glossary.promote": "Glossary promotion",
    "preprocess-summaries": "Summaries preprocessing",
    "preprocess-idioms": "Idiom preprocessing",
    "preprocess-graph": "Graph extraction",
    "translate-range": "Translation range",
    "translate-chapter": "Chapter translation",
    "production": "Production run",
}

_CHAPTER_ACTIONS: dict[str, str] = {
    "epub-extract": "Extracting chapter",
    "packets-build": "Building packets for chapter",
    "preprocess-glossary.discover": "Discovering glossary candidates in chapter",
    "preprocess-glossary.translate": "Translating glossary candidates in chapter",
    "preprocess-summaries": "Generating summaries for chapter",
    "preprocess-idioms": "Extracting idioms in chapter",
    "preprocess-graph": "Extracting graph entities in chapter",
    "translate-chapter": "Translating chapter",
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
    if event_type.endswith(".validation_failed") or event_type.endswith(".risk_detected"):
        return True
    if event_type.endswith(".failed"):
        return True
    if event_type.endswith(".stopped"):
        return True
    if event_type.endswith(".chapter_skipped"):
        return True
    if event_type.endswith(".artifact_written"):
        return True
    if _is_sampled_progress_event(event_type):
        return False
    return (
        event_type.endswith(".started")
        or event_type.endswith(".completed")
    )


def _is_sampled_progress_event(event_type: str) -> bool:
    return (
        ".paragraph_" in event_type
        or ".chapter_" in event_type
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
    resolved_message = message or _default_message(
        event_type=event_type,
        stage_name=stage_name,
        chapter_number=chapter_number,
        block_id=block_id,
        payload=payload or {},
    )
    event = Event(
        event_type=event_type,
        run_id=run_id,
        release_id=release_id,
        stage_name=stage_name,
        severity=severity,
        message=resolved_message,
        chapter_number=chapter_number,
        block_id=block_id,
        payload=payload or {},
    )
    result = default_event_bus.publish(event)

    _loguru_level = {"error": "ERROR", "warning": "WARNING"}.get(severity, "DEBUG")
    logger.log(
        _loguru_level,
        "[{}] {} | {}",
        event_type,
        stage_name,
        resolved_message,
        event_type=event_type,
        stage_name=stage_name,
        chapter_number=chapter_number,
        block_id=block_id,
        run_id=run_id,
        release_id=release_id,
    )

    return result


def _default_message(
    *,
    event_type: str,
    stage_name: str,
    chapter_number: Optional[int],
    block_id: Optional[str],
    payload: dict[str, Any],
) -> str:
    if event_type.endswith(".started"):
        return _started_message(event_type=event_type, payload=payload)
    if event_type.endswith(".chapter_started"):
        if chapter_number is None:
            return ""
        return f"{_chapter_action(event_type)} {chapter_number}"
    if event_type.endswith(".chapter_skipped"):
        if chapter_number is None:
            return ""
        reason = _humanize_reason(payload.get("reason"))
        suffix = f": {reason}" if reason else ""
        return f"Skipped {_stage_label(_stage_key_for_event(event_type)).lower()} for chapter {chapter_number}{suffix}"
    if event_type.endswith(".chapter_completed"):
        if chapter_number is None:
            return ""
        count_suffix = _count_suffix(payload)
        label = _stage_label(_stage_key_for_event(event_type)).lower()
        return f"Completed {label} for chapter {chapter_number}{count_suffix}"
    if event_type.endswith(".completed"):
        count_suffix = _count_suffix(payload)
        return f"{_stage_label(_stage_key_for_event(event_type))} completed{count_suffix}"
    if event_type.endswith(".failed"):
        return f"{_stage_label(_stage_key_for_event(event_type))} failed"
    if event_type.endswith(".stopped"):
        return f"{_stage_label(_stage_key_for_event(event_type))} stopped"
    if event_type.endswith(".term_found"):
        term = payload.get("term")
        if isinstance(term, str) and term:
            return f"Found glossary term {term}"
    if event_type.endswith(".entity_extracted"):
        entity_name = payload.get("entity_name")
        if isinstance(entity_name, str) and entity_name:
            return f"Extracted graph entity {entity_name}"
    if event_type.endswith(".artifact_written"):
        return "Artifact written"
    if event_type.endswith(".retry"):
        if block_id:
            return f"Retrying {block_id}"
        return "Retrying step"
    if event_type.endswith(".paragraph_started"):
        return f"Translating paragraph {block_id or '?'}"
    if event_type.endswith(".paragraph_completed"):
        return f"Translated paragraph {block_id or '?'}"
    if event_type.endswith(".validation_failed"):
        target = f"paragraph {block_id}" if block_id else f"chapter {chapter_number}"
        return f"Validation failed for {target}: {payload.get('message', 'Unknown error')}"
    if event_type.endswith(".risk_detected"):
        return f"Risk detected in paragraph {block_id}: {payload.get('message', 'High drift')}"

    return ""


def _stage_key_for_event(event_type: str) -> str:
    if "." in event_type:
        return event_type.rsplit(".", 1)[0]
    return event_type


def _stage_label(stage_key: str) -> str:
    label = _STAGE_LABELS.get(stage_key)
    if label is not None:
        return label
    return stage_key.replace(".", " ").replace("-", " ").title()


def _chapter_action(event_type: str) -> str:
    stage_key = _stage_key_for_event(event_type)
    action = _CHAPTER_ACTIONS.get(stage_key)
    if action is not None:
        return action
    return f"Processing {_stage_label(stage_key).lower()} in chapter"


def _started_message(*, event_type: str, payload: dict[str, Any]) -> str:
    stage_key = _stage_key_for_event(event_type)
    label = _stage_label(stage_key)
    total = payload.get("total_chapters")
    if isinstance(total, int):
        return f"{label} started for {total} chapters"
    return f"{label} started"


def _humanize_reason(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    return value.replace("_", " ").replace("-", " ")


def _count_suffix(payload: dict[str, Any]) -> str:
    count_fields = (
        ("term_count", "terms found"),
        ("discovered_count", "terms found"),
        ("candidate_count", "candidates"),
        ("summary_count", "summaries"),
        ("translated_count", "translations"),
        ("promoted_count", "promoted"),
        ("entity_count", "entities"),
        ("completed_blocks", "blocks completed"),
    )
    for key, label in count_fields:
        value = payload.get(key)
        if isinstance(value, int):
            return f": {value} {label}"
    return ""
