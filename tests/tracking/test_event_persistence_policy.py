from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from resemantica.orchestration.events import EventBus
from resemantica.tracking.models import Event
from resemantica.tracking.repo import (
    _SQLITE_BUSY_TIMEOUT_MS,
    _SQLITE_TIMEOUT_SECONDS,
    ensure_tracking_db,
    get_tracking_db_path,
    load_events,
    save_event,
)


class _LockingConn:
    def __init__(self, failures_before_success: int | None) -> None:
        self.failures_before_success = failures_before_success
        self.execute_calls = 0

    def __enter__(self) -> _LockingConn:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        return False

    def execute(self, query: str, params: tuple[object, ...]) -> None:  # noqa: ARG002
        self.execute_calls += 1
        if self.failures_before_success is None:
            raise sqlite3.OperationalError("database is locked")
        if self.execute_calls <= self.failures_before_success:
            raise sqlite3.OperationalError("database is locked")


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


def test_reduced_policy_samples_generic_progress_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bus = EventBus(persistence_mode="reduced", progress_sample_every=3)
    delivered: list[Event] = []
    bus.subscribe("*", delivered.append)

    for index in range(10):
        bus.publish(
            Event(
                event_type="preprocess-glossary.discover.scoring.progress",
                run_id="run",
                release_id="rel",
                stage_name="preprocess-glossary",
                payload={"processed_count": index + 1, "total_count": 10},
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


def test_concurrent_event_emission_persists_every_event_without_lock_tracebacks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    bus = EventBus()
    delivered: list[Event] = []
    bus.subscribe("*", delivered.append)

    def publish(index: int) -> None:
        bus.publish(
            Event(
                event_type="preprocess-summaries.chapter_skipped",
                run_id="run",
                release_id="rel",
                stage_name="preprocess-summaries",
                chapter_number=index,
            )
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(publish, range(30)))

    assert len(delivered) == 30
    conn = ensure_tracking_db("rel")
    try:
        persisted = load_events(conn, run_id="run", limit=100)
    finally:
        conn.close()
    assert len(persisted) == 30


def test_tracking_connection_uses_short_busy_timeout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    conn = ensure_tracking_db("rel")
    try:
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    finally:
        conn.close()

    assert _SQLITE_TIMEOUT_SECONDS <= 0.1
    assert busy_timeout == _SQLITE_BUSY_TIMEOUT_MS
    assert busy_timeout <= 100


def test_persistent_real_sqlite_lock_returns_quickly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    locker = ensure_tracking_db("rel")
    locked_writer = ensure_tracking_db("rel")
    sleeps: list[float] = []
    monkeypatch.setattr("resemantica.tracking.repo.time.sleep", sleeps.append)

    locker.execute("BEGIN IMMEDIATE")
    try:
        started = time.monotonic()
        save_event(
            locked_writer,
            Event(
                event_type="preprocess-summaries.chapter_skipped",
                run_id="run",
                release_id="rel",
                stage_name="preprocess-summaries",
                chapter_number=1,
            ),
        )
        elapsed = time.monotonic() - started
    finally:
        locker.rollback()
        locked_writer.close()
        locker.close()

    assert elapsed < 1.0
    assert sleeps == [0.05, 0.1, 0.2]
    verifier = sqlite3.connect(str(get_tracking_db_path("rel")))
    try:
        count = verifier.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        verifier.close()
    assert count == 0


def test_save_event_retries_transient_sqlite_lock(monkeypatch) -> None:
    conn = _LockingConn(failures_before_success=2)
    sleeps: list[float] = []
    monkeypatch.setattr("resemantica.tracking.repo.time.sleep", sleeps.append)

    save_event(
        conn,  # type: ignore[arg-type]
        Event(event_type="event", run_id="run", release_id="rel", stage_name="stage"),
    )

    assert conn.execute_calls == 3
    assert sleeps == [0.05, 0.1]


def test_persistent_sqlite_lock_is_swallowed_after_retries(monkeypatch) -> None:
    conn = _LockingConn(failures_before_success=None)
    sleeps: list[float] = []
    monkeypatch.setattr("resemantica.tracking.repo.time.sleep", sleeps.append)

    save_event(
        conn,  # type: ignore[arg-type]
        Event(event_type="event", run_id="run", release_id="rel", stage_name="stage"),
    )

    assert conn.execute_calls == 4
    assert sleeps == [0.05, 0.1, 0.2]


def test_event_persistence_failure_still_notifies_subscribers(monkeypatch) -> None:
    bus = EventBus()
    delivered: list[Event] = []
    bus.subscribe("*", delivered.append)

    monkeypatch.setattr(
        "resemantica.orchestration.events.ensure_tracking_db",
        lambda release_id: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )

    event = bus.publish(
        Event(
            event_type="preprocess-summaries.chapter_skipped",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-summaries",
            chapter_number=1,
        )
    )

    assert delivered == [event]
