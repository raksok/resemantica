from __future__ import annotations

from io import StringIO

from rich.console import Console
from rich.progress import Progress

from resemantica.cli_progress import CliProgressSubscriber
from resemantica.orchestration.events import EventBus
from resemantica.tracking.models import Event


def _progress() -> Progress:
    return Progress(console=Console(file=StringIO(), force_terminal=False), auto_refresh=False)


def test_cli_progress_subscribes_and_unsubscribes() -> None:
    bus = EventBus()
    subscriber = CliProgressSubscriber(event_bus=bus, progress=_progress())

    with subscriber:
        assert subscriber._on_event in bus._subscribers["*"]

    assert subscriber._on_event not in bus._subscribers["*"]


def test_cli_progress_creates_and_advances_chapter_task() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress())

    subscriber._on_event(
        Event(
            event_type="preprocess-summaries.started",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-summaries",
            payload={"total_chapters": 2},
        )
    )
    subscriber._on_event(
        Event(
            event_type="preprocess-summaries.chapter_completed",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-summaries",
            chapter_number=1,
        )
    )

    task_id = subscriber.tasks_by_stage["preprocess-summaries"]
    task = subscriber.progress.tasks[task_id]
    assert task.total == 2
    assert task.completed == 1


def test_cli_progress_counts_warnings_and_skips() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress())

    subscriber._on_event(
        Event(
            event_type="preprocess-summaries.started",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-summaries",
        )
    )
    subscriber._on_event(
        Event(
            event_type="validation_failed",
            run_id="run",
            release_id="rel",
            stage_name="validation",
        )
    )
    subscriber._on_event(
        Event(
            event_type="preprocess-summaries.chapter_skipped",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-summaries",
        )
    )

    assert subscriber.warning_count == 1
    assert subscriber.skip_count == 1
