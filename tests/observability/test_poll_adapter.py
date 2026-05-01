from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from resemantica.observability.adapter import PollAdapter
from resemantica.tracking.models import Event


def _iso(hour: int, minute: int) -> str:
    return datetime(2026, 4, 24, hour, minute, tzinfo=timezone.utc).isoformat()


def _make_event(
    *,
    event_type: str,
    event_time: str,
    severity: str = "info",
    event_id: str | None = None,
) -> Event:
    return Event(
        event_id=event_id or f"evt-{event_type}-{event_time}",
        event_type=event_type,
        event_time=event_time,
        run_id="run-1",
        release_id="rel-1",
        stage_name="test-stage",
        severity=severity,
    )


def _write_log_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _log_line(*, time_value: str, level: str, message: str) -> str:
    return json.dumps(
        {
            "text": message,
            "record": {
                "time": {"repr": time_value},
                "level": {"name": level},
                "name": "test",
                "message": message,
                "extra": {},
                "function": "fn",
                "line": 1,
                "file": {"name": "test.py"},
            },
        }
    )


def test_poll_returns_persisted_events(monkeypatch, tmp_path: Path) -> None:
    events = [
        _make_event(event_type="stage_started", event_time=_iso(10, 0), event_id="e1"),
        _make_event(event_type="chapter_completed", event_time=_iso(10, 1), event_id="e2"),
    ]

    monkeypatch.setattr(
        "resemantica.tracking.repo.ensure_tracking_db",
        lambda release_id: _FakeConn(events),
    )
    monkeypatch.setattr(
        "resemantica.tracking.repo.load_events",
        lambda conn, **kwargs: events,
    )

    adapter = PollAdapter(release_id="rel-1", run_id="run-1")
    monkeypatch.setattr(adapter, "_resolve_log_path", lambda: None)

    snapshot = adapter.snapshot()
    assert len(snapshot.persisted_records) == 2


def test_poll_position_tracking(monkeypatch, tmp_path: Path) -> None:
    events_batch1 = [
        _make_event(event_type="stage_started", event_time=_iso(10, 0), event_id="e1"),
    ]
    events_batch2 = [
        _make_event(event_type="stage_started", event_time=_iso(10, 0), event_id="e1"),
        _make_event(event_type="chapter_completed", event_time=_iso(10, 1), event_id="e2"),
    ]

    call_count = 0

    def fake_load_events(conn, **kwargs):
        nonlocal call_count
        call_count += 1
        return events_batch1 if call_count == 1 else events_batch2

    monkeypatch.setattr(
        "resemantica.tracking.repo.ensure_tracking_db",
        lambda release_id: _FakeConn(events_batch1),
    )
    monkeypatch.setattr(
        "resemantica.tracking.repo.load_events",
        fake_load_events,
    )

    adapter = PollAdapter(release_id="rel-1", run_id="run-1")
    monkeypatch.setattr(adapter, "_resolve_log_path", lambda: None)

    snap1 = adapter.snapshot()
    assert len(snap1.persisted_records) == 1
    assert adapter._last_event_id == "e1"

    snap2 = adapter.snapshot()
    assert len(snap2.persisted_records) == 1
    assert snap2.persisted_records[0].event_type == "chapter_completed"


def test_poll_empty_db(monkeypatch) -> None:
    monkeypatch.setattr(
        "resemantica.tracking.repo.ensure_tracking_db",
        lambda release_id: _FakeConn([]),
    )
    monkeypatch.setattr(
        "resemantica.tracking.repo.load_events",
        lambda conn, **kwargs: [],
    )

    adapter = PollAdapter(release_id="rel-1", run_id="run-1")
    monkeypatch.setattr(adapter, "_resolve_log_path", lambda: None)

    snapshot = adapter.snapshot()
    assert snapshot.persisted_records == []
    assert snapshot.counters.warnings == 0


def test_poll_log_records(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "run-1.jsonl"
    _write_log_lines(log_path, [
        _log_line(time_value=_iso(10, 0), level="INFO", message="test log"),
    ])

    monkeypatch.setattr(
        "resemantica.tracking.repo.ensure_tracking_db",
        lambda release_id: _FakeConn([]),
    )
    monkeypatch.setattr(
        "resemantica.tracking.repo.load_events",
        lambda conn, **kwargs: [],
    )

    adapter = PollAdapter(release_id="rel-1", run_id="run-1")
    monkeypatch.setattr(adapter, "_resolve_log_path", lambda: log_path)

    snapshot = adapter.snapshot()
    assert len(snapshot.log_records) == 1
    assert snapshot.log_records[0].message == "test log"


class _FakeConn:
    def __init__(self, events: list[Event]) -> None:
        self.events = events

    def close(self) -> None:
        pass
