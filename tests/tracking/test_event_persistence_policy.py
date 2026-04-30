from __future__ import annotations

from pathlib import Path

from resemantica.orchestration.events import EventBus
from resemantica.tracking.models import Event
from resemantica.tracking.repo import ensure_tracking_db, load_events


def test_reduced_policy_samples_progress_but_delivers_all(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bus = EventBus(persistence_mode="reduced", progress_sample_every=3)
    delivered: list[Event] = []
    bus.subscribe("*", delivered.append)

    for index in range(10):
        bus.publish(
            Event(
                event_type="translate-chapter.paragraph_completed",
                run_id="run",
                release_id="rel",
                stage_name="translate-chapter",
                block_id=f"b{index}",
            )
        )

    assert len(delivered) == 10
    conn = ensure_tracking_db("rel")
    try:
        persisted = load_events(conn, run_id="run", limit=20)
    finally:
        conn.close()
    assert len(persisted) == 4


def test_reduced_policy_always_persists_warning_and_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bus = EventBus(persistence_mode="reduced", progress_sample_every=100)
    bus.publish(
        Event(
            event_type="validation_failed",
            run_id="run",
            release_id="rel",
            stage_name="validation",
            severity="error",
        )
    )
    bus.publish(
        Event(
            event_type="preprocess-summaries.chapter_skipped",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-summaries",
        )
    )

    conn = ensure_tracking_db("rel")
    try:
        event_types = {event.event_type for event in load_events(conn, run_id="run", limit=20)}
    finally:
        conn.close()

    assert event_types == {"validation_failed", "preprocess-summaries.chapter_skipped"}
