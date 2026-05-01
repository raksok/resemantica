from __future__ import annotations

from collections import defaultdict

from resemantica.observability.adapter import LiveAdapter, NullAdapter
from resemantica.tracking.models import Event


def _make_event(*, event_type: str, severity: str = "info") -> Event:
    return Event(
        event_type=event_type,
        run_id="run-1",
        release_id="rel-1",
        stage_name="test-stage",
        severity=severity,
    )


def _make_live_adapter() -> LiveAdapter:
    adapter = LiveAdapter.__new__(LiveAdapter)
    adapter._subscriptions = defaultdict(list)
    adapter._buffer = []
    return adapter


def test_null_adapter_returns_empty_snapshot() -> None:
    adapter = NullAdapter()
    snapshot = adapter.snapshot()
    assert snapshot.live_records == []
    assert snapshot.persisted_records == []
    assert snapshot.log_records == []
    assert snapshot.counters.warnings == 0


def test_null_adapter_close_is_noop() -> None:
    adapter = NullAdapter()
    adapter.close()


def test_live_adapter_level0_receives_all() -> None:
    adapter = _make_live_adapter()
    received: list[Event] = []
    adapter.subscribe(0, received.append)

    adapter._on_event(_make_event(event_type="chapter_completed"))
    adapter._on_event(_make_event(event_type="paragraph_started"))

    assert len(received) == 2


def test_live_adapter_high_level_receives_only_detailed() -> None:
    adapter = _make_live_adapter()
    received: list[Event] = []
    adapter.subscribe(4, received.append)

    adapter._on_event(_make_event(event_type="stage_started"))
    adapter._on_event(_make_event(event_type="risk_detected"))

    assert len(received) == 1
    assert received[0].event_type == "risk_detected"


def test_live_adapter_filters_coarse_from_high_subscription() -> None:
    adapter = _make_live_adapter()
    received: list[Event] = []
    adapter.subscribe(3, received.append)

    adapter._on_event(_make_event(event_type="stage_started"))
    adapter._on_event(_make_event(event_type="paragraph_completed"))

    assert len(received) == 1
    assert received[0].event_type == "paragraph_completed"


def test_live_adapter_multiple_subscribers() -> None:
    adapter = _make_live_adapter()
    level0_events: list[Event] = []
    level3_events: list[Event] = []
    adapter.subscribe(0, level0_events.append)
    adapter.subscribe(3, level3_events.append)

    stage_event = _make_event(event_type="stage_completed")
    para_event = _make_event(event_type="paragraph_completed")

    adapter._on_event(stage_event)
    adapter._on_event(para_event)

    assert len(level0_events) == 2
    assert len(level3_events) == 1
    assert level3_events[0].event_type == "paragraph_completed"


def test_live_adapter_snapshot_returns_buffered_events() -> None:
    adapter = _make_live_adapter()
    event = _make_event(event_type="chapter_started")
    adapter._on_event(event)

    snapshot = adapter.snapshot()
    assert len(snapshot.live_records) == 1


def test_live_adapter_close_stops_delivery() -> None:
    adapter = _make_live_adapter()
    received: list[Event] = []
    adapter.subscribe(0, received.append)
    adapter.close()

    adapter._on_event(_make_event(event_type="stage_started"))

    assert len(received) == 0


def test_live_adapter_error_delivered_to_level0() -> None:
    adapter = _make_live_adapter()
    received: list[Event] = []
    adapter.subscribe(0, received.append)

    error_event = _make_event(event_type="stage_failed", severity="error")
    adapter._on_event(error_event)

    assert len(received) == 1


def test_live_adapter_error_not_delivered_to_high_level() -> None:
    adapter = _make_live_adapter()
    received: list[Event] = []
    adapter.subscribe(3, received.append)

    error_event = _make_event(event_type="stage_failed", severity="error")
    adapter._on_event(error_event)

    assert len(received) == 0
