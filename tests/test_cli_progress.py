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
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress(), verbosity=4)

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
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress(), verbosity=4)

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


def test_cli_progress_completes_indeterminate_task() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress(), verbosity=4)

    subscriber._on_event(
        Event(
            event_type="preprocess-glossary.promote.started",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-glossary",
        )
    )
    subscriber._on_event(
        Event(
            event_type="preprocess-glossary.promote.completed",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-glossary",
        )
    )

    task = subscriber.progress.tasks[subscriber.tasks_by_stage["preprocess-glossary.promote"]]
    assert task.finished
    assert task.total == 1
    assert task.completed == 1


def test_cli_progress_counter_text_is_global() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress())
    subscriber.warning_count = 1
    subscriber.skip_count = 2
    subscriber.retry_count = 3
    subscriber.artifact_count = 4

    assert subscriber._counter_text() == "run warn 1 run skip 2 run retry 3 run artifacts 4"


def test_cli_progress_filters_events_by_cli_verbosity() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress(), verbosity=0)

    subscriber._on_event(
        Event(
            event_type="preprocess-summaries.chapter_completed",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-summaries",
            chapter_number=1,
        )
    )

    assert subscriber.tasks_by_stage == {}
