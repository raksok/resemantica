from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from resemantica.observability.granularity import classify_event_level
from resemantica.tracking.models import Event

if TYPE_CHECKING:
    from resemantica.tui.observability import ObservabilitySnapshot


class ObservabilityAdapter(Protocol):
    def subscribe(self, level: int, callback: Callable[[Event], None]) -> None: ...
    def unsubscribe(self, level: int, callback: Callable[[Event], None]) -> None: ...
    def snapshot(self) -> ObservabilitySnapshot: ...
    def close(self) -> None: ...


class NullAdapter:
    def subscribe(self, level: int, callback: Callable[[Event], None]) -> None:
        pass

    def unsubscribe(self, level: int, callback: Callable[[Event], None]) -> None:
        pass

    def snapshot(self) -> ObservabilitySnapshot:
        from resemantica.tui.observability import ObservabilityCounters, ObservabilitySnapshot

        return ObservabilitySnapshot(
            counters=ObservabilityCounters(),
            latest_failure=None,
            live_records=[],
            persisted_records=[],
            log_records=[],
        )

    def close(self) -> None:
        pass


class LiveAdapter:
    def __init__(self) -> None:
        self._subscriptions: dict[int, list[Callable[[Event], None]]] = defaultdict(list)
        self._buffer: deque[Event] = deque(maxlen=1000)
        from resemantica.orchestration.events import subscribe as bus_subscribe

        bus_subscribe("*", self._on_event)

    def subscribe(self, level: int, callback: Callable[[Event], None]) -> None:
        self._subscriptions[level].append(callback)

    def unsubscribe(self, level: int, callback: Callable[[Event], None]) -> None:
        callbacks = self._subscriptions.get(level, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def snapshot(self) -> ObservabilitySnapshot:
        from resemantica.tui.observability import build_snapshot

        return build_snapshot(
            live_events=list(self._buffer),
            persisted_events=[],
            log_records=[],
        )

    def close(self) -> None:
        from resemantica.orchestration.events import unsubscribe as bus_unsubscribe

        bus_unsubscribe("*", self._on_event)
        self._subscriptions.clear()

    def _on_event(self, event: Event) -> None:
        self._buffer.append(event)
        event_level = classify_event_level(event)
        for sub_level, callbacks in self._subscriptions.items():
            if event_level >= sub_level:
                for cb in callbacks:
                    try:
                        cb(event)
                    except Exception:
                        pass


class PollAdapter:
    def __init__(self, release_id: str, run_id: str, poll_interval: float = 2.0) -> None:
        self._release_id = release_id
        self._run_id = run_id
        self._poll_interval = poll_interval
        self._last_event_id: str | None = None
        self._last_log_offset: int = 0
        self._subscriptions: dict[int, list[Callable[[Event], None]]] = defaultdict(list)
        self._buffer: deque[Event] = deque(maxlen=1000)
        self._log_path: Path | None = None

    def subscribe(self, level: int, callback: Callable[[Event], None]) -> None:
        self._subscriptions[level].append(callback)

    def unsubscribe(self, level: int, callback: Callable[[Event], None]) -> None:
        callbacks = self._subscriptions.get(level, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def snapshot(self) -> ObservabilitySnapshot:
        from resemantica.tracking.repo import ensure_tracking_db, load_events
        from resemantica.tui.observability import build_snapshot, load_log_records

        events: list[Event] = []
        conn = ensure_tracking_db(self._release_id)
        try:
            all_events = load_events(conn, run_id=self._run_id, release_id=self._release_id, limit=10000)
            if self._last_event_id is None:
                events = all_events
            else:
                found_last = False
                for ev in all_events:
                    if not found_last:
                        if ev.event_id == self._last_event_id:
                            found_last = True
                        continue
                    events.append(ev)
        finally:
            conn.close()

        if events:
            self._last_event_id = events[-1].event_id

        log_records = []
        log_path = self._resolve_log_path()
        if log_path is not None and log_path.exists():
            records = load_log_records(log_path, limit=1000)
            log_records = records

        for event in events:
            self._buffer.append(event)

        return build_snapshot(
            live_events=[],
            persisted_events=events,
            log_records=log_records,
        )

    def close(self) -> None:
        self._subscriptions.clear()

    def _resolve_log_path(self) -> Path | None:
        if self._log_path is not None:
            return self._log_path
        try:
            from resemantica.settings import derive_paths, load_config

            config = load_config()
            paths = derive_paths(config, release_id=self._release_id)
            self._log_path = paths.artifact_root / "logs" / f"{self._run_id}.jsonl"
            return self._log_path
        except Exception:
            return None
